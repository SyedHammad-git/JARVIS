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

foreach ($name in @("DB_BACKEND", "JARVIS_HOST", "JARVIS_PORT", "ALLOW_PUBLIC_BIND", "PYTHONUTF8", "JARVIS_DATA_DIR", "JARVIS_SKIP_DOTENV")) {
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
    Remove-Item Env:JARVIS_SKIP_DOTENV -ErrorAction SilentlyContinue

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

    foreach ($check in @(
        @{ name = "weather"; message = "Faisalabad ka weather batao" },
        @{ name = "plain_chat"; message = "In one sentence, what does an application factory do?" }
    )) {
        try {
            $body = @{ message = $check.message; session_id = "live-check-$($check.name)" } | ConvertTo-Json
            $response = Invoke-RestMethod -Uri "$baseUrl/api/agent" -Method Post `
                -ContentType "application/json" -Body $body -TimeoutSec 150
            $toolNames = @($response.steps | ForEach-Object { $_.tool } | Where-Object { $_ } | Select-Object -Unique)
            $replySummary = ([string]$response.reply -split "[\r\n]")[0].Trim()
            $replySummary = $replySummary -replace "(?i)(api[_ -]?key|token|password|secret)\s*[:=]\s*[^\s,;]+", '$1=[REDACTED]'
            $replySummary = $replySummary -replace "https?://[^\s?]+\?[^\s]+", "[URL]"
            $replySummary = $replySummary -replace "\b[A-Za-z0-9_-]{32,}\b", "[REDACTED]"
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
