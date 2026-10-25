param(
    [string]$BaseUrl = "http://127.0.0.1:5000"
)

function Invoke-SnapshotCheck {
    param([string]$Label)

    $body = @{
        message = "Take one camera snapshot and briefly describe what is visible."
        session_id = "manual-camera-check"
    } | ConvertTo-Json -Compress
    $response = Invoke-RestMethod -Method Post -Uri "$BaseUrl/api/agent" `
        -ContentType "application/json" -Body $body
    $stepSummary = @($response.steps | ForEach-Object {
        "{0}: {1}" -f $_.tool, ([string]$_.result).Substring(0, [Math]::Min(200, ([string]$_.result).Length))
    })

    [PSCustomObject]@{
        Check = $Label
        Reply = $response.reply
        Steps = ($stepSummary -join " | ")
    } | Format-List
}

Write-Host "Set Camera allowed OFF in the Electron tray, then press Enter."
[void](Read-Host)
Invoke-SnapshotCheck -Label "Camera OFF (expect camera_disabled refusal)"

Write-Host "Set Camera allowed ON in the Electron tray, then press Enter."
[void](Read-Host)
Invoke-SnapshotCheck -Label "Camera ON (expect saved snapshot and vision description)"