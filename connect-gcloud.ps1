param(
    [string]$Instance = "hanstock-server4",
    [string]$Zone = "asia-northeast3-a",
    [string]$Project = "hanstock-server"
)

$ErrorActionPreference = "Stop"

$gcloud = Get-Command gcloud -ErrorAction SilentlyContinue
if (-not $gcloud) {
    $localGcloud = Join-Path $env:LOCALAPPDATA "Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd"
    if (Test-Path $localGcloud) {
        $gcloud = $localGcloud
    } else {
        Write-Error "gcloud command was not found. Install Google Cloud CLI first."
        exit 1
    }
} else {
    $gcloud = $gcloud.Source
}

Write-Host "Connecting to $Instance ($Zone) in project $Project..."
& $gcloud compute ssh $Instance --zone $Zone --project $Project
