# Build the personal FXJEFE image on Windows.
# Copies models and CSV data out of the source tree without modifying it,
# writes bundle\manifest.sha256.json, then builds and tags the image.
param(
    [string]$Source = "C:\Users\FullSend\Documents\FXJEFE_Project",
    [string]$Image = "fxjefe:latest",
    [string]$Registry = "",
    [switch]$Push
)

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $here) { $here = (Get-Location).Path }
Set-Location $here

$bundle = Join-Path $here "bundle"
& (Join-Path $here "stage_bundle.ps1") -Source $Source -Destination $bundle
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Error "docker was not found on PATH. Install Docker Desktop, then run this script again."
    exit 1
}

Write-Host "docker build -t $Image"
& docker build -t $Image $here
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$tagged = @($Image)
if ($Registry) {
    $remote = $Registry
    if ($remote.EndsWith("/")) { $remote = $remote.TrimEnd("/") }
    if ($remote -notmatch ":") { $remote = "$remote:latest" }
    Write-Host "docker tag $Image $remote"
    & docker tag $Image $remote
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    $tagged += $remote
    if ($Push) {
        Write-Host "docker push $remote"
        & docker push $remote
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    } else {
        Write-Host "Tagged $remote. Push with: docker push $remote"
        Write-Host "Or rerun this script with -Registry $remote -Push"
    }
}

Write-Host "image tags: $($tagged -join ', ')"
Write-Host "manifest: $(Join-Path $bundle 'manifest.sha256.json')"
docker image inspect $Image --format "image_bytes={{.Size}}"
exit 0
