$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$landingEnvPath = Join-Path $repoRoot "landing\.env.local"
$backendEnvPath = Join-Path $repoRoot "backend-cloud\.env"
$script:failureCount = 0

function Write-Check {
    param(
        [string]$Name,
        [bool]$Passed,
        [string]$Detail
    )

    $status = if ($Passed) { "PASS" } else { "FAIL" }
    Write-Output ("{0} {1}: {2}" -f $status, $Name, $Detail)
    if (-not $Passed) {
        $script:failureCount++
    }
}

function Read-EnvValues {
    param(
        [string]$Path,
        [string[]]$Names
    )

    $values = @{}
    foreach ($name in $Names) {
        $values[$name] = @{ State = "EMPTY"; Value = "" }
    }
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return $values
    }

    $lines = [System.IO.File]::ReadAllLines($Path)
    foreach ($name in $Names) {
        $namePattern = [regex]::Escape($name)
        $activePattern = "^\s*$namePattern\s*=(.*)$"
        $commentPattern = "^\s*#\s*$namePattern\s*="
        foreach ($line in $lines) {
            if ($line -match $activePattern) {
                $value = $Matches[1].Trim()
                if ($value.Length -ge 2 -and
                    (($value.StartsWith('"') -and $value.EndsWith('"')) -or
                    ($value.StartsWith("'") -and $value.EndsWith("'")))) {
                    $value = $value.Substring(1, $value.Length - 2)
                }
                if ($value) {
                    $values[$name] = @{ State = "set"; Value = $value }
                } else {
                    $values[$name] = @{ State = "EMPTY"; Value = "" }
                }
                break
            }
            if ($line -match $commentPattern) {
                $values[$name] = @{ State = "COMMENTED"; Value = "" }
            }
        }
    }
    return $values
}

function Test-ListeningPort {
    param([int]$Port)
    return [bool](Test-NetConnection -ComputerName "127.0.0.1" -Port $Port `
        -InformationLevel Quiet -WarningAction SilentlyContinue)
}

function Get-FrontendApiDomain {
    param([string]$PublishableKey)

    $match = [regex]::Match($PublishableKey, '^pk_(?:test|live)_(.+)$')
    if (-not $match.Success) {
        return $null
    }
    $encoded = $match.Groups[1].Value.TrimEnd('$').Replace('-', '+').Replace('_', '/')
    $encoded = $encoded.PadRight([int][Math]::Ceiling($encoded.Length / 4.0) * 4, '=')
    try {
        $domain = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($encoded)).TrimEnd('$')
        $parsed = $null
        if ([Uri]::TryCreate("https://$domain", [UriKind]::Absolute, [ref]$parsed) -and
            $parsed.Host -eq $domain -and $parsed.IsDefaultPort -and $parsed.AbsolutePath -eq "/") {
            return $parsed.Host
        }
    } catch {
        return $null
    }
    return $null
}

$landing = Read-EnvValues -Path $landingEnvPath -Names @(
    "NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY",
    "CLERK_SECRET_KEY",
    "NEXT_PUBLIC_BACKEND_URL"
)
$backend = Read-EnvValues -Path $backendEnvPath -Names @(
    "AUTH_MODE",
    "CLERK_ISSUER",
    "CLERK_JWKS_URL",
    "CLERK_AUTHORIZED_PARTIES",
    "CORS_ORIGINS",
    "API_KEY_ENCRYPTION_KEY",
    "JARVIS_HOST"
)

foreach ($name in @(
    "NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY",
    "CLERK_SECRET_KEY",
    "NEXT_PUBLIC_BACKEND_URL"
)) {
    $state = $landing[$name].State
    Write-Check "landing/.env.local $name" ($state -eq "set") $state
}
foreach ($name in @(
    "CLERK_ISSUER",
    "CLERK_JWKS_URL",
    "CLERK_AUTHORIZED_PARTIES",
    "CORS_ORIGINS",
    "API_KEY_ENCRYPTION_KEY"
)) {
    $state = if ($backend[$name].State -eq "set") { "set" } else { "EMPTY" }
    Write-Check "backend-cloud/.env $name" ($state -eq "set") $state
}
$authModeMatches = $backend.AUTH_MODE.Value -eq "clerk"
$authModeDetail = if ($authModeMatches) { "configured mode is clerk" } else { "configured mode is not clerk" }
Write-Check "backend-cloud/.env AUTH_MODE=clerk" $authModeMatches $authModeDetail

$frontendApiDomain = Get-FrontendApiDomain $landing.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY.Value
$issuerUri = $null
$issuerMatches = $frontendApiDomain -and
    [Uri]::TryCreate($backend.CLERK_ISSUER.Value, [UriKind]::Absolute, [ref]$issuerUri) -and
    $issuerUri.Scheme -eq "https" -and $issuerUri.Host -eq $frontendApiDomain
Write-Check "Clerk publishable domain matches CLERK_ISSUER" ([bool]$issuerMatches) `
    $(if ($frontendApiDomain -and $issuerUri) { "domain comparison completed" } else { "publishable key or issuer is not usable" })

$jwksStatus = "request unavailable"
$jwksPassed = $false
if ($backend.CLERK_JWKS_URL.Value) {
    try {
        $jwksResponse = Invoke-WebRequest -Uri $backend.CLERK_JWKS_URL.Value -Method Get `
            -TimeoutSec 10 -UseBasicParsing
        $jwksPassed = [int]$jwksResponse.StatusCode -eq 200
        $jwksStatus = "HTTP $([int]$jwksResponse.StatusCode)"
    } catch {
        if ($_.Exception.Response -and $_.Exception.Response.StatusCode) {
            $jwksStatus = "HTTP $([int]$_.Exception.Response.StatusCode)"
        }
    }
}
Write-Check "Public Clerk JWKS endpoint" $jwksPassed $jwksStatus

$jarvisHost = $backend.JARVIS_HOST.Value
if (-not $jarvisHost) {
    $jarvisHost = "127.0.0.1"
}
$hostAddress = $null
$loopback = $jarvisHost -eq "localhost" -or
    ([System.Net.IPAddress]::TryParse($jarvisHost, [ref]$hostAddress) -and
    [System.Net.IPAddress]::IsLoopback($hostAddress))
Write-Check "JARVIS_HOST loopback" ([bool]$loopback) `
    $(if ($backend.JARVIS_HOST.Value) { "configured host checked" } else { "default loopback applies" })

$backendRunning = Test-ListeningPort 5000
$landingRunning = Test-ListeningPort 3000
Write-Check "Port 3000" $landingRunning $(if ($landingRunning) { "listening" } else { "not listening" })
Write-Check "Port 5000" $backendRunning $(if ($backendRunning) { "listening" } else { "not listening" })

$backendUri = $null
if ($landing.NEXT_PUBLIC_BACKEND_URL.Value) {
    [void][Uri]::TryCreate($landing.NEXT_PUBLIC_BACKEND_URL.Value, [UriKind]::Absolute, [ref]$backendUri)
}
if (-not $backendUri) {
    $backendUri = [Uri]"http://127.0.0.1:5000"
}
$backendBase = $backendUri.GetLeftPart([UriPartial]::Authority)
$pingPassed = $false
$pingDetail = "SKIP backend is not running"
if ($backendRunning) {
    try {
        $pingResponse = Invoke-WebRequest -Uri "$backendBase/api/ping" -Method Get `
            -TimeoutSec 5 -UseBasicParsing
        $pingPassed = [int]$pingResponse.StatusCode -eq 200
        $pingDetail = "HTTP $([int]$pingResponse.StatusCode)"
    } catch {
        $pingDetail = "request failed"
    }
}
if ($backendRunning) {
    Write-Check "Backend /api/ping" $pingPassed $pingDetail
} else {
    Write-Output "SKIP Backend /api/ping: backend is not running"
}

if ($backendRunning) {
    $preflightPassed = $false
    $preflightDetail = "preflight request failed"
    try {
        $preflight = Invoke-WebRequest -Uri "$backendBase/api/ping" -Method Options `
            -Headers @{
                Origin = "http://localhost:3000"
                "Access-Control-Request-Method" = "GET"
                "Access-Control-Request-Headers" = "authorization,content-type"
            } -TimeoutSec 5 -UseBasicParsing
        $allowedOrigin = [string]$preflight.Headers["Access-Control-Allow-Origin"]
        $allowedMethods = [string]$preflight.Headers["Access-Control-Allow-Methods"]
        $allowedHeaders = [string]$preflight.Headers["Access-Control-Allow-Headers"]
        $allowCredentials = [string]$preflight.Headers["Access-Control-Allow-Credentials"]
        $preflightPassed = $allowedOrigin -eq "http://localhost:3000" -and
            $allowedMethods -match "(?i)(^|,\s*)GET(,|$)" -and
            $allowedHeaders -match "(?i)authorization" -and
            $allowedHeaders -match "(?i)content-type" -and
            $allowCredentials -eq "true"
        $preflightDetail = if ($preflightPassed) { "allow-origin, methods, headers, credentials verified" } else { "required CORS headers missing or incorrect" }
    } catch {
        $preflightDetail = "preflight request failed"
    }
    Write-Check "CORS preflight from landing" $preflightPassed $preflightDetail
} else {
    Write-Output "SKIP CORS preflight: backend is not running"
}

if ($script:failureCount -gt 0) {
    Write-Output "FAIL Connection check: $($script:failureCount) check(s) failed"
    exit 1
}
Write-Output "PASS Connection check: all checks passed"
