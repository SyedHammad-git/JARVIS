$ErrorActionPreference = "Stop"
$backendDir = Split-Path -Parent $PSScriptRoot
$listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 0)
$listener.Start()
$port = $listener.LocalEndpoint.Port
$listener.Stop()
$baseUrl = "http://127.0.0.1:$port"
$logRoot = Join-Path $env:TEMP ("jarvis-smoke-" + [guid]::NewGuid().ToString("N"))
$stdoutPath = Join-Path $logRoot "stdout.log"
$stderrPath = Join-Path $logRoot "stderr.log"
$dataDir = Join-Path $logRoot "data"
$process = $null
$failed = $false
$originalEnvironment = @{}

foreach ($name in @("DB_BACKEND", "JARVIS_HOST", "JARVIS_PORT", "ALLOW_PUBLIC_BIND", "PYTHONUTF8", "JARVIS_DATA_DIR", "JARVIS_SKIP_DOTENV", "GROQ_KEY", "GEMINI_KEY", "OPENROUTER_KEY", "WEATHER_KEY")) {
    $originalEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
}

try {
    New-Item -ItemType Directory -Path $logRoot | Out-Null
    $env:DB_BACKEND = "sqlite"
    $env:JARVIS_HOST = "127.0.0.1"
    $env:JARVIS_PORT = "$port"
    $env:ALLOW_PUBLIC_BIND = "0"
    $env:PYTHONUTF8 = "1"
    $env:JARVIS_DATA_DIR = $dataDir
    $env:JARVIS_SKIP_DOTENV = "1"
    $env:GROQ_KEY = "test-groq-key"
    $env:GEMINI_KEY = "test-gemini-key"
    $env:OPENROUTER_KEY = "test-openrouter-key"
    $env:WEATHER_KEY = "test-weather-key"

    $process = Start-Process -FilePath "py" -ArgumentList @("wsgi.py") `
        -WorkingDirectory $backendDir -PassThru -WindowStyle Hidden `
        -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath

    $ready = $false
    $deadline = [DateTime]::UtcNow.AddSeconds(30)
    while ([DateTime]::UtcNow -lt $deadline -and -not $ready) {
        if ($process.HasExited) {
            throw "Backend process exited before becoming ready (exit $($process.ExitCode))."
        }
        try {
            $ping = Invoke-WebRequest -UseBasicParsing -Uri "$baseUrl/api/ping" -TimeoutSec 2
            $ready = $ping.StatusCode -eq 200
        }
        catch {
            [Threading.Thread]::Sleep(300)
        }
    }
    if (-not $ready) {
        throw "Backend did not become ready within 30 seconds."
    }
    Write-Output "PASS /api/ping status=$($ping.StatusCode)"

    foreach ($route in @("/", "/mobile")) {
        $response = Invoke-WebRequest -UseBasicParsing -Uri "$baseUrl$route" -TimeoutSec 5
        if ($response.StatusCode -ne 200 -or $response.Headers["Content-Type"] -notlike "text/html*") {
            throw "$route returned status=$($response.StatusCode), content-type=$($response.Headers['Content-Type'])."
        }
        if ($response.Content -notmatch "JARVIS" -or $response.Content.TrimStart().StartsWith("{")) {
            throw "$route did not return the expected JARVIS HTML document."
        }
        Write-Output "PASS $route status=$($response.StatusCode) content-type=text/html"
    }
}
catch {
    $failed = $true
    Write-Output "FAIL $($_.Exception.Message)"
}
finally {
    if ($process -and -not $process.HasExited) {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        $process.WaitForExit()
    }
    foreach ($name in $originalEnvironment.Keys) {
        [Environment]::SetEnvironmentVariable($name, $originalEnvironment[$name], "Process")
    }
    Remove-Item -LiteralPath $logRoot -Recurse -Force -ErrorAction SilentlyContinue
}

if ($failed) {
    exit 1
}
Write-Output "PASS real-start smoke"
exit 0
