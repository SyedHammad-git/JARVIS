param(
    [switch]$RunLiveCheck
)

$ErrorActionPreference = "Stop"
if (-not $RunLiveCheck) {
    Write-Output "Opt-in required: .\scripts\live_llm_check.ps1 -RunLiveCheck"
    exit 2
}

$backendDir = Split-Path -Parent $PSScriptRoot
$listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 0)
$listener.Start()
$port = $listener.LocalEndpoint.Port
$listener.Stop()
$baseUrl = "http://127.0.0.1:$port"
$tempRoot = Join-Path $env:TEMP ("jarvis-live-check-" + [guid]::NewGuid().ToString("N"))
$stdoutPath = Join-Path $tempRoot "stdout.log"
$stderrPath = Join-Path $tempRoot "stderr.log"
$process = $null
$failed = $false
$originalEnvironment = @{}

foreach ($name in @("DB_BACKEND", "JARVIS_HOST", "JARVIS_PORT", "ALLOW_PUBLIC_BIND", "PYTHONUTF8", "JARVIS_DATA_DIR", "JARVIS_SKIP_DOTENV", "PYTHONPATH", "GROQ_KEY", "GEMINI_KEY", "OPENROUTER_KEY", "WEATHER_KEY")) {
    $originalEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
}

try {
    New-Item -ItemType Directory -Path $tempRoot | Out-Null
    $env:DB_BACKEND = "sqlite"
    $env:JARVIS_HOST = "127.0.0.1"
    $env:JARVIS_PORT = "$port"
    $env:ALLOW_PUBLIC_BIND = "0"
    $env:PYTHONUTF8 = "1"
    $env:JARVIS_DATA_DIR = Join-Path $tempRoot "data"
    $env:PYTHONPATH = $backendDir
    Remove-Item Env:JARVIS_SKIP_DOTENV -ErrorAction SilentlyContinue
    foreach ($name in @("GROQ_KEY", "GEMINI_KEY", "OPENROUTER_KEY", "WEATHER_KEY")) {
        Remove-Item "Env:$name" -ErrorAction SilentlyContinue
    }

    $seedCode = @'
import contextlib
import io
import json
import os
import secrets
import sys

sys.path.insert(0, os.getcwd())
from app.authentication import create_user
from app.db import init_db
import pyotp

with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
    init_db()
    username = "livecheck_" + secrets.token_hex(8)
    password = secrets.token_urlsafe(24)
    totp_secret = pyotp.random_base32()
    if not create_user(username, password, totp_secret):
        raise RuntimeError("Could not create isolated live-check user")

print(json.dumps({
    "username": username,
    "password": password,
    "totp_secret": totp_secret,
}))
'@
    $authJson = $seedCode | py -
    if ($LASTEXITCODE -ne 0 -or -not $authJson) {
        throw "Could not initialize the isolated live-check account."
    }
    $auth = $authJson | ConvertFrom-Json

    $process = Start-Process -FilePath "py" -ArgumentList @("wsgi.py") `
        -WorkingDirectory $backendDir -PassThru -WindowStyle Hidden `
        -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath

    $ready = $false
    $deadline = [DateTime]::UtcNow.AddSeconds(35)
    while ([DateTime]::UtcNow -lt $deadline -and -not $ready) {
        if ($process.HasExited) {
            throw "Backend exited before readiness."
        }
        try {
            $null = Invoke-RestMethod -Uri "$baseUrl/api/ping" -TimeoutSec 2
            $ready = $true
        }
        catch {
            [Threading.Thread]::Sleep(300)
        }
    }
    if (-not $ready) {
        throw "Backend readiness timed out."
    }

    $webSession = $null
    $loginBootstrap = Invoke-RestMethod -Uri "$baseUrl/api/auth/login" `
        -Method Get -SessionVariable webSession -TimeoutSec 5
    foreach ($cookie in $webSession.Cookies.GetCookies([uri]$baseUrl)) {
        if ($cookie.Secure) {
            $cookie.Secure = $false
        }
    }
    $totpCode = $auth.totp_secret | py -c "import sys,pyotp; print(pyotp.TOTP(sys.stdin.read().strip()).now())"
    if ($LASTEXITCODE -ne 0 -or -not $totpCode) {
        throw "Could not generate the isolated live-check login code."
    }
    $loginBody = @{
        username = $auth.username
        password = $auth.password
        totp = $totpCode.Trim()
    } | ConvertTo-Json
    $loginResponse = Invoke-RestMethod -Uri "$baseUrl/api/auth/login" -Method Post `
        -ContentType "application/json" -Body $loginBody -WebSession $webSession `
        -Headers @{ "X-CSRF-Token" = $loginBootstrap.csrf_token } -TimeoutSec 10
    foreach ($cookie in $webSession.Cookies.GetCookies([uri]$baseUrl)) {
        if ($cookie.Secure) {
            $cookie.Secure = $false
        }
    }

    foreach ($check in @(
        @{ name = "weather"; message = "Faisalabad ka weather batao" },
        @{ name = "plain_chat"; message = "In one sentence, what does an application factory do?" }
    )) {
        try {
            $body = @{ message = $check.message; session_id = "live-check-$($check.name)" } | ConvertTo-Json
            $response = Invoke-RestMethod -Uri "$baseUrl/api/agent" -Method Post `
                -ContentType "application/json" -Body $body -WebSession $webSession `
                -Headers @{ "X-CSRF-Token" = $loginResponse.csrf_token } -TimeoutSec 150
            $toolNames = @($response.steps | ForEach-Object { $_.tool } | Where-Object { $_ } | Select-Object -Unique)
            $replySummary = ([string]$response.reply -split "[\r\n]")[0].Trim()
            $replySummary = $replySummary -replace "(?i)(api[_ -]?key|token|password|secret)\s*[:=]\s*[^\s,;]+", '$1=[REDACTED]'
            $replySummary = $replySummary -replace "https?://[^\s?]+\?[^\s]+", "[URL]"
            $replySummary = $replySummary -replace "\b(?:sk-[A-Za-z0-9_-]{8,}|gsk_[A-Za-z0-9_-]{8,}|AIza[A-Za-z0-9_-]{8,}|[A-Za-z0-9_-]{32,})\b", "[REDACTED]"
            if ($replySummary.Length -gt 120) {
                $replySummary = $replySummary.Substring(0, 117) + "..."
            }
            Write-Output ("check={0} ok={1} model={2} tools=[{3}] reply_summary={4}" -f `
                $check.name, [bool]$response.ok, $response.model, ($toolNames -join ","), $replySummary)
        }
        catch {
            Write-Output ("check={0} ok=False model=none tools=[] reply_summary=error:{1}" -f `
                $check.name, $_.Exception.GetType().Name)
            $failed = $true
        }
    }
}
catch {
    Write-Output ("check=setup ok=False model=none tools=[] reply_summary=error:{0}" -f $_.Exception.GetType().Name)
    $failed = $true
}
finally {
    if ($process -and -not $process.HasExited) {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        $process.WaitForExit()
    }
    foreach ($name in $originalEnvironment.Keys) {
        [Environment]::SetEnvironmentVariable($name, $originalEnvironment[$name], "Process")
    }
    Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
}

if ($failed) {
    exit 1
}
exit 0
