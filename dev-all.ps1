$ErrorActionPreference = "Stop"

$repoRoot = $PSScriptRoot
$backendDir = Join-Path $repoRoot "backend-cloud"
$landingDir = Join-Path $repoRoot "landing"
$backendUrl = "http://127.0.0.1:5000/api/ping"
$backendOrigin = "http://127.0.0.1:5000"
$landingUrl = "http://localhost:3000"
$landingOrigin = "http://localhost:3000"
$landingHealthUrl = "http://127.0.0.1:3000/manifest.webmanifest"

function Test-HttpReady {
    param([string]$Url)
    try {
        $response = Invoke-WebRequest -Uri $Url -Method Get -TimeoutSec 2 -UseBasicParsing
        return [int]$response.StatusCode -eq 200
    } catch {
        return $false
    }
}

if (-not (Test-HttpReady $backendUrl)) {
    $env:JARVIS_SKIP_DOTENV = "1"
    $env:PYTHONIOENCODING = "utf-8"
    $env:DB_BACKEND = "sqlite"
    $env:JARVIS_HOST = "127.0.0.1"
    $env:BACKEND_URL = $backendOrigin
    $env:NEXT_PUBLIC_BACKEND_URL = $backendOrigin
    $env:LANDING_URL = $landingOrigin
    $env:CORS_ORIGINS = $landingOrigin
    Start-Process -FilePath "py.exe" -ArgumentList @("wsgi.py") `
        -WorkingDirectory $backendDir | Out-Null
    Write-Output "Started backend development server."
} else {
    Write-Output "Using the running backend."
}

$backendReady = $false
for ($attempt = 0; $attempt -lt 90; $attempt++) {
    if (Test-HttpReady $backendUrl) {
        $backendReady = $true
        break
    }
    Start-Sleep -Seconds 1
}
if (-not $backendReady) {
    throw "Backend /api/ping did not become ready within 90 seconds."
}
Write-Output "Backend /api/ping is ready."

if (-not (Test-HttpReady $landingHealthUrl)) {
    $env:BACKEND_URL = $backendOrigin
    $env:NEXT_PUBLIC_BACKEND_URL = $backendOrigin
    $env:NEXT_PUBLIC_SITE_URL = $landingOrigin
    Start-Process -FilePath "npm.cmd" `
        -ArgumentList @("run", "dev", "--", "--hostname", "127.0.0.1", "--port", "3000") `
        -WorkingDirectory $landingDir | Out-Null
    Write-Output "Started landing development server."
} else {
    Write-Output "Using the running landing server."
}

$landingReady = $false
for ($attempt = 0; $attempt -lt 120; $attempt++) {
    if (Test-HttpReady $landingHealthUrl) {
        $landingReady = $true
        break
    }
    Start-Sleep -Seconds 1
}
if (-not $landingReady) {
    throw "Landing page did not become ready within 120 seconds."
}

Start-Process $landingUrl
Write-Output "Opened $landingUrl."
