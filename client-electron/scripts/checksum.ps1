$ErrorActionPreference = 'Stop'

$package = Get-Content -Raw (Join-Path $PSScriptRoot '..\package.json') | ConvertFrom-Json
$installerName = "JARVIS-Device-Client-Setup-$($package.version).exe"
$installerPath = Join-Path $PSScriptRoot "..\release\$installerName"

if (-not (Test-Path -LiteralPath $installerPath -PathType Leaf)) {
    throw "Installer was not produced: $installerPath"
}

$hash = (Get-FileHash -LiteralPath $installerPath -Algorithm SHA256).Hash.ToLowerInvariant()
$checksumPath = "$installerPath.sha256"
[System.IO.File]::WriteAllText($checksumPath, "$hash *$installerName`n", [System.Text.Encoding]::ASCII)
Write-Output "SHA-256 file: $checksumPath"