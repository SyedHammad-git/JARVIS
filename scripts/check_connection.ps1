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

function Get-ClerkFrontendApiDomain {
    $publishableKey = Get-EnvironmentValue "NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY"
    if ($publishableKey -notmatch '^pk_(?:test|live)_([A-Za-z0-9_-]+)\$?$') {
        return $null
    }

    $encodedDomain = $Matches[1].Replace("-", "+").Replace("_", "/")
    switch ($encodedDomain.Length % 4) {
        2 { $encodedDomain += "==" }
        3 { $encodedDomain += "=" }
    }
    try {
        $domain = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($encodedDomain)).TrimEnd('$')
        $domainUri = ConvertTo-AbsoluteUri "https://$domain"
        if ($null -eq $domainUri -or $domainUri.Host -ne $domain -or
            $domainUri.AbsolutePath -ne "/" -or $domainUri.Query -or $domainUri.Fragment) {
            return $null
        }
        return $domainUri.Host
    } catch {
        return $null
    }
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
    "CLERK_SECRET_KEY",
    "NEXT_PUBLIC_SITE_URL"
)
foreach ($name in $landingSecretNames) {
    $state = Get-EnvironmentState $name
    Write-Check "Landing process variable $name" ($state -eq "set") $state
}

$backendRequiredNames = @(
    "API_KEY_ENCRYPTION_KEY",
    "DATABASE_URL",
    "FLASK_SECRET",
    "ALLOWED_CLERK_SUBJECTS",
    "CLERK_ISSUER",
    "CLERK_JWKS_URL",
    "CLERK_AUTHORIZED_PARTIES",
    "CORS_ORIGINS",
    "LANDING_URL",
    "BACKEND_URL",
    "NEXT_PUBLIC_BACKEND_URL"
)
foreach ($name in $backendRequiredNames) {
    $state = Get-EnvironmentState $name
    Write-Check "Backend process variable $name" ($state -eq "set") $state
}

$production = (Get-EnvironmentValue "JARVIS_ENV") -eq "production"
$dbBackend = Get-EnvironmentValue "DB_BACKEND"
if (-not $production -and [string]::IsNullOrWhiteSpace($dbBackend)) {
    $dbBackend = "sqlite"
}
$dbBackendValid = if ($production) { $dbBackend -eq "postgres" } else { $dbBackend -in @("sqlite", "postgres") }
Write-Check "DB_BACKEND" ([bool]$dbBackendValid) `
    $(if ($dbBackendValid) { "configured backend is valid for this environment" } else { "production requires postgres; local mode allows sqlite or postgres" })

$authMode = Get-EnvironmentValue "AUTH_MODE"
$authModeMatches = $authMode -eq "clerk"
Write-Check "Backend AUTH_MODE=clerk" $authModeMatches `
    $(if ($authModeMatches) { "configured mode is clerk" } else { "set AUTH_MODE=clerk" })

$fallbackKeys = Get-EnvironmentValue "SERVER_FALLBACK_KEYS"
$fallbackKeysValid = -not ($production -and $fallbackKeys -eq "1")
Write-Check "SERVER_FALLBACK_KEYS production policy" ([bool]$fallbackKeysValid) `
    $(if ($fallbackKeysValid) { "fallback is not enabled in production" } else { "disable server-wide provider-key fallback" })

$issuer = ConvertTo-AbsoluteUri (Get-EnvironmentValue "CLERK_ISSUER")
$jwks = ConvertTo-AbsoluteUri (Get-EnvironmentValue "CLERK_JWKS_URL")
$frontendApiDomain = Get-ClerkFrontendApiDomain
$clerkUrlsValid = $null -ne $issuer -and $null -ne $jwks -and
    $issuer.Scheme -eq "https" -and $jwks.Scheme -eq "https" -and
    $issuer.Host -eq $jwks.Host -and $jwks.AbsolutePath -eq "/.well-known/jwks.json"
Write-Check "Clerk issuer and JWKS URL shape" ([bool]$clerkUrlsValid) `
    $(if ($clerkUrlsValid) { "HTTPS endpoints are structurally consistent" } else { "configure matching HTTPS CLERK_ISSUER and CLERK_JWKS_URL values" })
$issuerMatchesPublishableKey = $null -ne $frontendApiDomain -and $null -ne $issuer -and
    $issuer.Host -eq $frontendApiDomain
Write-Check "Clerk issuer matches publishable key" ([bool]$issuerMatchesPublishableKey) `
    $(if ($issuerMatchesPublishableKey) { "issuer host matches the publishable-key Frontend API domain" } else { "match CLERK_ISSUER to NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY" })

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
    $(if ($partiesValid) { "explicit HTTPS origins configured" } else { "configure CLERK_AUTHORIZED_PARTIES with explicit HTTPS origins" })

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
    $(if ($corsValid) { "origin shape is valid" } else { "configure CORS_ORIGINS; production origins must use HTTPS" })

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
$desktopBackendUrlValue = Get-EnvironmentValue "BACKEND_URL"
$backendUri = ConvertTo-AbsoluteUri $backendUrlValue
$backendUrlValid = $null -ne $backendUri -and -not $backendUri.UserInfo -and
    $backendUri.AbsolutePath -eq "/" -and -not $backendUri.Query -and -not $backendUri.Fragment -and
    ($backendUri.Scheme -eq "https" -or (
        -not $production -and $backendUri.Scheme -eq "http" -and (
            $backendUri.Host -eq "localhost" -or
            [System.Net.IPAddress]::TryParse($backendUri.Host, [ref]$hostAddress) -and
            [System.Net.IPAddress]::IsLoopback($hostAddress)
        )
    ))
Write-Check "NEXT_PUBLIC_BACKEND_URL shape" ([bool]$backendUrlValid) `
    $(if ($backendUrlValid) { "absolute HTTPS URL or development loopback" } else { "configure NEXT_PUBLIC_BACKEND_URL as HTTPS; HTTP is limited to development loopback" })
$desktopBackendUri = ConvertTo-AbsoluteUri $desktopBackendUrlValue
$sharedBackendUrl = $backendUrlValid -and $null -ne $desktopBackendUri -and
    -not $desktopBackendUri.UserInfo -and $desktopBackendUri.AbsolutePath -eq "/" -and
    -not $desktopBackendUri.Query -and -not $desktopBackendUri.Fragment -and
    $backendUri.GetLeftPart([UriPartial]::Authority) -eq $desktopBackendUri.GetLeftPart([UriPartial]::Authority)
Write-Check "Shared landing and desktop backend URL" ([bool]$sharedBackendUrl) `
    $(if ($sharedBackendUrl) { "both clients use the same configured backend origin" } else { "set BACKEND_URL and NEXT_PUBLIC_BACKEND_URL to the same origin" })

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
} else {
    $jwksStatus = "configure CLERK_ISSUER and CLERK_JWKS_URL first"
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
    Write-Check "Backend /api/ping" $false "backend is not listening on loopback port 5000"
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
    Write-Check "CORS preflight from landing" $false "backend is not listening on loopback port 5000"
}

if ($script:failureCount -gt 0) {
    Write-Output "FAIL Connection check: $($script:failureCount) check(s) failed"
    exit 1
}
Write-Output "PASS Connection check: all checks passed"
