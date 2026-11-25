# Read-only stage of models and CSV data for the FXJEFE Linux image.
# Default source is the FullSend project tree. This script never deletes or
# edits a file under that source. It copies into -Destination and writes
# manifest.sha256.json there.
param(
    [string]$Source = "C:\Users\FullSend\Documents\FXJEFE_Project",
    [string]$Destination = ".\stage"
)

$ErrorActionPreference = "Stop"

function Get-FileSha256([string]$Path) {
    $sha = [System.Security.Cryptography.SHA256]::Create()
    $stream = [System.IO.File]::Open($Path, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
    try {
        $hash = $sha.ComputeHash($stream)
    } finally {
        $stream.Dispose()
        $sha.Dispose()
    }
    return ([System.BitConverter]::ToString($hash)).Replace("-", "").ToLowerInvariant()
}

function Test-SecretName([string]$Name) {
    $lower = $Name.ToLowerInvariant()
    if ($lower.StartsWith(".env")) { return $true }
    foreach ($token in @("password", "secret", "credential", "id_rsa", ".pem", ".key")) {
        if ($lower.Contains($token)) { return $true }
    }
    return $false
}

function Test-JsonSecret([string]$Path) {
    $text = [System.IO.File]::ReadAllText($Path)
    if ($text -match '(?i)"(password|passwd|secret|apiKey|api_key|token|mt5_password)"\s*:') {
        return $true
    }
    return $false
}

if (-not (Test-Path -LiteralPath $Source -PathType Container)) {
    Write-Error "Source directory does not exist: $Source"
    exit 1
}

$sourceRoot = (Resolve-Path -LiteralPath $Source).Path
$destRoot = $Destination
if (-not [System.IO.Path]::IsPathRooted($destRoot)) {
    $destRoot = Join-Path (Get-Location) $destRoot
}
New-Item -ItemType Directory -Force -Path $destRoot | Out-Null
$destRoot = (Resolve-Path -LiteralPath $destRoot).Path

if ($destRoot.TrimEnd('\') -eq $sourceRoot.TrimEnd('\')) {
    Write-Error "Destination must be a different directory from the source."
    exit 1
}

$planned = New-Object System.Collections.Generic.List[object]
function Add-Tree([string]$RelativeFolder) {
    $folder = Join-Path $sourceRoot $RelativeFolder
    if (-not (Test-Path -LiteralPath $folder -PathType Container)) {
        Write-Host "source has no $RelativeFolder directory; nothing copied from it"
        return
    }
    Get-ChildItem -LiteralPath $folder -Recurse -File | ForEach-Object {
        $rel = $_.FullName.Substring($sourceRoot.Length).TrimStart('\')
        $planned.Add([pscustomobject]@{ Source = $_.FullName; Relative = $rel }) | Out-Null
    }
}

Add-Tree "models"
Add-Tree "data"

$rules = Join-Path $sourceRoot "configftmo.json"
if (Test-Path -LiteralPath $rules -PathType Leaf) {
    $planned.Add([pscustomobject]@{ Source = $rules; Relative = "configftmo.json" }) | Out-Null
}

$before = @{}
foreach ($item in $planned) {
    $before[$item.Source] = Get-FileSha256 $item.Source
}

$manifestFiles = New-Object System.Collections.Generic.List[object]
foreach ($item in $planned) {
    $name = [System.IO.Path]::GetFileName($item.Source)
    if (Test-SecretName $name) {
        Write-Host "skipped $($item.Relative): name looks like a credential; value not printed"
        continue
    }
    if ($name.ToLowerInvariant().EndsWith(".json") -and (Test-JsonSecret $item.Source)) {
        Write-Host "skipped $($item.Relative): credential field present; value not printed"
        continue
    }
    $target = Join-Path $destRoot $item.Relative
    $targetDir = Split-Path -Parent $target
    New-Item -ItemType Directory -Force -Path $targetDir | Out-Null
    [System.IO.File]::Copy($item.Source, $target, $true)
    $again = Get-FileSha256 $item.Source
    if ($again -ne $before[$item.Source]) {
        Write-Error "Source file changed while staging: $($item.Relative)"
        exit 1
    }
    $info = Get-Item -LiteralPath $target
    $manifestFiles.Add([ordered]@{
        path = ($item.Relative -replace '\\', '/')
        sha256 = $again
        bytes = [int64]$info.Length
    }) | Out-Null
}

$manifest = [ordered]@{
    source = $sourceRoot
    destination = $destRoot
    read_only = $true
    source_unchanged = $true
    staged_at = [DateTime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ")
    file_count = $manifestFiles.Count
    files = $manifestFiles
}
$manifestPath = Join-Path $destRoot "manifest.sha256.json"
$json = $manifest | ConvertTo-Json -Depth 6
[System.IO.File]::WriteAllText($manifestPath, $json + "`n")
Write-Host "staged $($manifestFiles.Count) files into $destRoot"
Write-Host "manifest $manifestPath"
Write-Host "source was not modified: $sourceRoot"
exit 0
