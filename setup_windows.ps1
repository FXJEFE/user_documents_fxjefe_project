# Create two per-user venvs under PROJECT_ROOT:
#   fxjefe    Python 3.11  (pipeline, golden server, MT5)
#   fxjefe38  Python 3.8.10 (TA-Lib + TensorFlow 2.10.1)
# Does not create PROJECT_ROOT.
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

function Resolve-ProjectRoot {
    if ($env:FXJEFE_PROJECT_DIR -and $env:FXJEFE_PROJECT_DIR.Trim()) {
        return $env:FXJEFE_PROJECT_DIR.Trim()
    }
    return (Join-Path $env:USERPROFILE "Documents\FXJEFE_Project")
}

function Find-PythonVersion {
    param([string]$MajorMinor, [string]$Exact, [string]$LocalFolder)
    $launcher = Get-Command py -ErrorAction SilentlyContinue
    if ($launcher) {
        $script = "import sys; print(sys.executable); raise SystemExit(0 if sys.version.startswith('{0}') else 1)" -f $Exact
        if (-not $Exact) {
            $script = "import sys; print(sys.executable); raise SystemExit(0 if sys.version.startswith('{0}') else 1)" -f $MajorMinor
        }
        $exe = & py "-$MajorMinor" -c $script 2>$null
        if ($LASTEXITCODE -eq 0 -and $exe) {
            return ($exe | Select-Object -Last 1).Trim()
        }
    }
    $candidate = Join-Path $env:LOCALAPPDATA "Programs\Python\$LocalFolder\python.exe"
    if (Test-Path $candidate) {
        $ver = (& $candidate -c "import sys; print(sys.version.split()[0])").Trim()
        if ($Exact -and $ver -eq $Exact) { return $candidate }
        if (-not $Exact -and $ver.StartsWith($MajorMinor)) { return $candidate }
    }
    return $null
}

function Install-Python {
    param([string]$Version, [string]$FolderName)
    $installer = Join-Path $env:TEMP "python-$Version-amd64.exe"
    $uri = "https://www.python.org/ftp/python/$Version/python-$Version-amd64.exe"
    Write-Host "Downloading $uri"
    Invoke-WebRequest -Uri $uri -OutFile $installer -UseBasicParsing
    $proc = Start-Process -FilePath $installer -ArgumentList @(
        "/quiet", "InstallAllUsers=0", "PrependPath=1", "Include_launcher=1", "Include_pip=1", "Include_test=0"
    ) -Wait -PassThru
    if ($proc.ExitCode -ne 0 -and $proc.ExitCode -ne 3010) {
        Write-Host "Python $Version installer failed with exit $($proc.ExitCode)"
        exit 1
    }
    return (Join-Path $env:LOCALAPPDATA "Programs\Python\$FolderName\python.exe")
}

function New-ProjectVenv {
    param([string]$Python, [string]$VenvPath, [string]$Requirements)
    $venvPython = Join-Path $VenvPath "Scripts\python.exe"
    if (-not (Test-Path $venvPython)) {
        Write-Host "Creating $VenvPath"
        & $Python -m venv $VenvPath
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
    & $venvPython -m pip install -U pip setuptools wheel
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & $venvPython -m pip install -r $Requirements
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

$ProjectRoot = Resolve-ProjectRoot
Write-Host "PROJECT_ROOT=$ProjectRoot"
if (-not (Test-Path -LiteralPath $ProjectRoot)) {
    Write-Host "PROJECT_ROOT does not exist: $ProjectRoot"
    Write-Host "Clone this repo to $env:USERPROFILE\Documents\FXJEFE_Project or set FXJEFE_PROJECT_DIR."
    exit 1
}
foreach ($name in @("run_pipeline.py", "requirements.txt", "requirements-fxjefe38.txt")) {
    if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot $name))) {
        Write-Host "$name is not in PROJECT_ROOT: $ProjectRoot"
        exit 1
    }
}

$Python311 = Find-PythonVersion -MajorMinor "3.11" -Exact "" -LocalFolder "Python311"
if (-not $Python311) {
    $Python311 = Install-Python -Version "3.11.9" -FolderName "Python311"
}
if (-not (Test-Path $Python311)) {
    Write-Host "Python 3.11 was not found after install."
    exit 1
}
Write-Host "Using Python 3.11 at $Python311"

$Python3810 = Find-PythonVersion -MajorMinor "3.8" -Exact "3.8.10" -LocalFolder "Python38"
if (-not $Python3810) {
    $Python3810 = Install-Python -Version "3.8.10" -FolderName "Python38"
}
& $Python3810 -c "import sys; raise SystemExit(0 if sys.version.split()[0]=='3.8.10' else 1)"
if ($LASTEXITCODE -ne 0) {
    Write-Host "Python 3.8.10 check failed: $Python3810"
    exit 1
}
Write-Host "Using Python 3.8.10 at $Python3810"

New-ProjectVenv -Python $Python311 -VenvPath (Join-Path $ProjectRoot "fxjefe") -Requirements (Join-Path $ProjectRoot "requirements.txt")
New-ProjectVenv -Python $Python3810 -VenvPath (Join-Path $ProjectRoot "fxjefe38") -Requirements (Join-Path $ProjectRoot "requirements-fxjefe38.txt")
Write-Host "Setup complete. Run run_pipeline.bat from $ProjectRoot"
exit 0
