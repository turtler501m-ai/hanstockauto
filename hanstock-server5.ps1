$ErrorActionPreference = "Stop"

$ssh = Join-Path $env:WINDIR "System32\OpenSSH\ssh.exe"
$key = Join-Path $env:USERPROFILE ".ssh\google_compute_engine"
$user = "turtler800"
$instance = "hanstock-server5"
$zone = "us-central1-b"
$project = "hanstock-server"
$gcloud = Join-Path $env:LOCALAPPDATA "Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd"

if (-not (Test-Path $ssh)) {
    Write-Error "OpenSSH client was not found: $ssh"
    exit 1
}

if (-not (Test-Path $key)) {
    Write-Error "Google Cloud SSH key was not found: $key"
    exit 1
}

if (-not (Test-Path $gcloud)) {
    Write-Error "gcloud command was not found: $gcloud"
    exit 1
}

$hostName = & $gcloud compute instances describe $instance `
    --zone $zone `
    --project $project `
    --format "value(networkInterfaces[0].accessConfigs[0].natIP)"

if (-not $hostName) {
    Write-Error "Could not find an external IP for $instance."
    exit 1
}

Write-Host "Opening SSH in this terminal: $user@$instance ($hostName)"
& $ssh -t `
    -i $key `
    -o StrictHostKeyChecking=accept-new `
    -o ConnectTimeout=15 `
    "$user@$hostName"
