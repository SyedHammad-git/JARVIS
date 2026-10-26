$ErrorActionPreference = "Stop"
$script:failureCount = 0

# Inspect only exported process variables. Never load dotenv files or print configuration values.
function Get-EnvironmentValue {
    param([string]$Name)
    return [Environment]::GetEnvironmentVariable($Name, "Process")
}

function Get-EnvironmentState {
    param([string]$Name)
    if ([string]::IsNullOrWhiteSpace((Get-EnvironmentValue $Name))) {
        return "EMPTY"
    }
    return "set"
}

function ConvertTo-AbsoluteUri {
    param([string]$Value)
    $uri = $null
    if ([Uri]::TryCreate($Value, [UriKind]::Absolute, [ref]$uri)) {
        return $uri
    }
    return $null
}

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

function Test-ListeningPort {
    param([int]$Port)
    return [bool](Test-NetConnection -ComputerName "127.0.0.1" -Port $Port `
        -InformationLevel Quiet -WarningAction SilentlyContinue)
}

$landingSecretNames = @(
    "NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY",
    "CLERK_SECRET_KEY"
)
foreach ($name in $landingSecretNames) {
    $state = Get-EnvironmentState $name
    Write-Check "Landing process variable $name" ($state -eq "set") $state
}

$backendRequiredNames = @(
    "API_KEY_ENCRYPTION_KEY",
    "DATABASE_URL",
    "FLASK_SECRET",
    "ALLOWED_CLERK_SUBJECTS"
)
foreach ($name in $backendRequiredNames) {
    $state = Get-EnvironmentState $name
    Write-Check "Backend process variable $name" ($state -eq "set") $state
}

$production = (Get-EnvironmentValue "JARVIS_ENV") -eq "production"
$dbBackend = Get-EnvironmentValue "DB_BACKEND"
$dbBackendValid = if ($production) { $dbBackend -eq "postgres" } else { $dbBackend -in @("sqlite", "postgres") }
Write-Check "DB_BACKEND" ([bool]$dbBackendValid) `
    $(if ($dbBackendValid) { "configured backend is valid for this environment" } else { "production requires postgres; local mode allows sqlite or postgres" })

$authMode = Get-EnvironmentValue "AUTH_MODE"
$authModeMatches = $authMode -eq "clerk"
Write-Check "Backend AUTH_MODE=clerk" $authModeMatches `
    $(if ($authModeMatches) { "configured mode is clerk" } else { "configured mode is not clerk" })

$fallbackKeys = Get-EnvironmentValue "SERVER_FALLBACK_KEYS"
Write-Check "SERVER_FALLBACK_KEYS disabled" ($fallbackKeys -ne "1") `
    $(if ($fallbackKeys -eq "1") { "disable server-wide provider-key fallback" } else { "fallback is off" })

$issuer = ConvertTo-AbsoluteUri (Get-EnvironmentValue "CLERK_ISSUER")
$jwks = ConvertTo-AbsoluteUri (Get-EnvironmentValue "CLERK_JWKS_URL")
$clerkUrlsValid = $null -ne $issuer -and $null -ne $jwks -and
    $issuer.Scheme -eq "https" -and $jwks.Scheme -eq "https" -and
    $issuer.Host -eq $jwks.Host -and $jwks.AbsolutePath -eq "/.well-known/jwks.json"
Write-Check "Clerk issuer and JWKS URL shape" ([bool]$clerkUrlsValid) `
    $(if ($clerkUrlsValid) { "HTTPS endpoints are structurally consistent" } else { "expected matching HTTPS issuer and JWKS endpoints" })

$partyValue = Get-EnvironmentValue "CLERK_AUTHORIZED_PARTIES"
$parties = @($partyValue -split "," | ForEach-Object { $_.Trim() } | Where-Object { $_ })
$partiesValid = $parties.Count -gt 0
foreach ($party in $parties) {
    $partyUri = ConvertTo-AbsoluteUri $party
    if ($null -eq $partyUri -or $partyUri.Scheme -ne "https" -or
        $partyUri.AbsolutePath -ne "/" -or $partyUri.Query -or $partyUri.Fragment -or
        $partyUri.UserInfo -or $party.Contains("*")) {
        $partiesValid = $false
    }
}
Write-Check "Clerk authorized-party origins" ([bool]$partiesValid) `
    $(if ($partiesValid) { "explicit HTTPS origins configured" } else { "configure explicit HTTPS origins without wildcards" })

$corsValue = Get-EnvironmentValue "CORS_ORIGINS"
$corsOrigins = @($corsValue -split "," | ForEach-Object { $_.Trim() } | Where-Object { $_ })
$corsValid = $corsOrigins.Count -gt 0
foreach ($origin in $corsOrigins) {
    $originUri = ConvertTo-AbsoluteUri $origin
    if ($null -eq $originUri -or $originUri.AbsolutePath -ne "/" -or
        $originUri.Query -or $originUri.Fragment -or $originUri.UserInfo -or
        $origin.Contains("*") -or ($production -and $originUri.Scheme -ne "https")) {
        $corsValid = $false
    }
}
Write-Check "Explicit CORS origins" ([bool]$corsValid) `
    $(if ($corsValid) { "origin shape is valid" } else { "configure explicit origins; production origins must use HTTPS" })

$hostValue = Get-EnvironmentValue "JARVIS_HOST"
if ([string]::IsNullOrWhiteSpace($hostValue)) {
    $hostValue = "127.0.0.1"
}
$hostAddress = $null
$loopback = $hostValue -eq "localhost" -or
    ([System.Net.IPAddress]::TryParse($hostValue, [ref]$hostAddress) -and
    [System.Net.IPAddress]::IsLoopback($hostAddress))
Write-Check "JARVIS_HOST loopback" ([bool]$loopback) `
    $(if ($loopback) { "loopback bind configured" } else { "refusing a non-loopback bind" })

$backendUrlValue = Get-EnvironmentValue "NEXT_PUBLIC_BACKEND_URL"
$backendUri = ConvertTo-AbsoluteUri $backendUrlValue
$backendUrlValid = $null -ne $backendUri -and -not $backendUri.UserInfo -and
    ($backendUri.Scheme -eq "https" -or (
        -not $production -and $backendUri.Scheme -eq "http" -and (
            $backendUri.Host -eq "localhost" -or
            [System.Net.IPAddress]::TryParse($backendUri.Host, [ref]$hostAddress) -and
            [System.Net.IPAddress]::IsLoopback($hostAddress)
        )
    ))
Write-Check "NEXT_PUBLIC_BACKEND_URL shape" ([bool]$backendUrlValid) `
    $(if ($backendUrlValid) { "absolute HTTPS URL or development loopback" } else { "configure an HTTPS URL; HTTP is limited to development loopback" })

$jwksPassed = $false
$jwksStatus = "SKIP endpoint shape is invalid"
if ($clerkUrlsValid) {
    $jwksStatus = "request unavailable"
    try {
        $jwksResponse = Invoke-WebRequest -Uri $jwks.AbsoluteUri -Method Get `
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

$backendRunning = Test-ListeningPort 5000
$landingRunning = Test-ListeningPort 3000
Write-Check "Local port 3000" $landingRunning $(if ($landingRunning) { "listening" } else { "not listening" })
Write-Check "Local port 5000" $backendRunning $(if ($backendRunning) { "listening" } else { "not listening" })

$pingBase = if ($backendUrlValid) {
    $backendUri.GetLeftPart([UriPartial]::Authority)
} else {
    "http://127.0.0.1:5000"
}
$pingPassed = $false
$pingDetail = "SKIP backend is not listening"
if ($backendRunning) {
    try {
        $pingResponse = Invoke-WebRequest -Uri "$pingBase/api/ping" -Method Get `
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
    Write-Output "SKIP Backend /api/ping: backend is not listening"
}

if ($backendRunning) {
    $preflightPassed = $false
    $preflightDetail = "preflight request failed"
    try {
        $preflight = Invoke-WebRequest -Uri "$pingBase/api/ping" -Method Options `
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
        $preflightDetail = if ($preflightPassed) { "required CORS headers verified" } else { "required CORS headers missing or incorrect" }
    } catch {
        $preflightDetail = "preflight request failed"
    }
    Write-Check "CORS preflight from landing" $preflightPassed $preflightDetail
} else {
    Write-Output "SKIP CORS preflight: backend is not listening"
}

if ($script:failureCount -gt 0) {
    Write-Output "FAIL Connection check: $($script:failureCount) check(s) failed"
    exit 1
}
Write-Output "PASS Connection check: all checks passed"
