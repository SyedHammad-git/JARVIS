$ErrorActionPreference = "Stop"

$repoRoot = $PSScriptRoot
$backendDir = Join-Path $repoRoot "backend-cloud"
$landingDir = Join-Path $repoRoot "landing"
$backendUrl = "http://127.0.0.1:5000/api/ping"
$landingUrl = "http://localhost:3000"

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
    $backendCommand = "Set-Location -LiteralPath `"$backendDir`"; `$env:DB_BACKEND='sqlite'; `$env:JARVIS_HOST='127.0.0.1'; py wsgi.py"
    Start-Process -FilePath "powershell.exe" -ArgumentList @("-NoExit", "-Command", $backendCommand) | Out-Null
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

if (-not (Test-HttpReady $landingUrl)) {
    $landingCommand = "Set-Location -LiteralPath `"$landingDir`"; npm run dev"
    Start-Process -FilePath "powershell.exe" -ArgumentList @("-NoExit", "-Command", $landingCommand) | Out-Null
    Write-Output "Started landing development server."
} else {
    Write-Output "Using the running landing server."
}

$landingReady = $false
for ($attempt = 0; $attempt -lt 120; $attempt++) {
    if (Test-HttpReady $landingUrl) {
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
