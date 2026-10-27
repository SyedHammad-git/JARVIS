$ErrorActionPreference = 'Stop'

$clientDir = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$configPath = Join-Path $clientDir 'src\backend-config.json'
$configCreated = $false
$backendUrl = [string]$env:BACKEND_URL

if ([string]::IsNullOrWhiteSpace($backendUrl)) {
    throw 'BACKEND_URL is required to build the desktop client.'
}

try {
    $uri = [Uri]$backendUrl.Trim()
} catch {
    throw 'BACKEND_URL must be an absolute HTTPS origin.'
}

$loopback = $uri.Host -in @('localhost', '127.0.0.1', '::1')
$https = $uri.Scheme -eq 'https'
$devHttp = $env:JARVIS_DEV -eq '1' -and $loopback -and $uri.Scheme -eq 'http'
if ((-not $https -and -not $devHttp) -or $uri.UserInfo -or $uri.Query -or $uri.Fragment -or $uri.AbsolutePath -ne '/') {
    throw 'BACKEND_URL must be an HTTPS origin (HTTP is limited to loopback with JARVIS_DEV=1).'
}
if (Test-Path -LiteralPath $configPath) {
    throw 'Refusing to overwrite existing src/backend-config.json.'
}

$buildConfig = @{ backendUrl = $uri.GetLeftPart([System.UriPartial]::Authority) } | ConvertTo-Json -Compress
[System.IO.File]::WriteAllText($configPath, $buildConfig, [System.Text.Encoding]::ASCII)
$configCreated = $true

try {
    Push-Location $clientDir
    & npx electron-builder --win nsis
    if ($LASTEXITCODE -ne 0) { throw 'electron-builder failed.' }
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/checksum.ps1
    if ($LASTEXITCODE -ne 0) { throw 'Installer checksum generation failed.' }
} finally {
    Pop-Location
    if ($configCreated) {
        Remove-Item -LiteralPath $configPath -Force -ErrorAction SilentlyContinue
    }
}