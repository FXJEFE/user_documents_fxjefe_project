# Install Python 3.8.10 (64-bit, per-user) if needed, then create <PROJECT_ROOT>\.venv
# and pip-install requirements.txt. Does not create PROJECT_ROOT.
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

function Resolve-ProjectRoot {
    if ($env:FXJEFE_PROJECT_DIR -and $env:FXJEFE_PROJECT_DIR.Trim()) {
        return $env:FXJEFE_PROJECT_DIR.Trim()
    }
    return (Join-Path $env:USERPROFILE "Documents\FXJEFE_Project")
}

function Get-Python3810Executable {
    $launcher = Get-Command py -ErrorAction SilentlyContinue
    if ($launcher) {
        $exe = & py -3.8 -c "import sys; print(sys.executable); raise SystemExit(0 if sys.version.split()[0]=='3.8.10' else 1)" 2>$null
        if ($LASTEXITCODE -eq 0 -and $exe) {
            return ($exe | Select-Object -Last 1).Trim()
        }
    }
    $candidate = Join-Path $env:LOCALAPPDATA "Programs\Python\Python38\python.exe"
    if (Test-Path $candidate) {
        $ver = & $candidate -c "import sys; print(sys.version.split()[0])"
        if ($ver.Trim() -eq "3.8.10") {
            return $candidate
        }
    }
    return $null
}

$ProjectRoot = Resolve-ProjectRoot
Write-Host "PROJECT_ROOT=$ProjectRoot"
if (-not (Test-Path -LiteralPath $ProjectRoot)) {
    Write-Host "PROJECT_ROOT does not exist: $ProjectRoot"
    Write-Host "Clone this repo to $env:USERPROFILE\Documents\FXJEFE_Project or set FXJEFE_PROJECT_DIR."
    exit 1
}
if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot "run_pipeline.py"))) {
    Write-Host "run_pipeline.py is not in PROJECT_ROOT: $ProjectRoot"
    exit 1
}
if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot "requirements.txt"))) {
    Write-Host "requirements.txt is not in PROJECT_ROOT: $ProjectRoot"
    exit 1
}

$Python = Get-Python3810Executable
if (-not $Python) {
    $installer = Join-Path $env:TEMP "python-3.8.10-amd64.exe"
    $uri = "https://www.python.org/ftp/python/3.8.10/python-3.8.10-amd64.exe"
    Write-Host "Downloading $uri"
    Invoke-WebRequest -Uri $uri -OutFile $installer -UseBasicParsing
    Write-Host "Installing Python 3.8.10 per-user"
    $proc = Start-Process -FilePath $installer -ArgumentList @(
        "/quiet", "InstallAllUsers=0", "PrependPath=1", "Include_launcher=1", "Include_pip=1", "Include_test=0"
    ) -Wait -PassThru
    if ($proc.ExitCode -ne 0 -and $proc.ExitCode -ne 3010) {
        Write-Host "Python installer failed with exit $($proc.ExitCode)"
        exit 1
    }
    $Python = Get-Python3810Executable
    if (-not $Python) {
        $fallback = Join-Path $env:LOCALAPPDATA "Programs\Python\Python38\python.exe"
        if (Test-Path $fallback) { $Python = $fallback }
    }
}
if (-not $Python) {
    Write-Host "Python 3.8.10 was not found after install."
    exit 1
}
Write-Host "Using $Python"
& $Python -c "import sys; raise SystemExit(0 if sys.version.split()[0]=='3.8.10' else 1)"
if ($LASTEXITCODE -ne 0) {
    Write-Host "Interpreter is not Python 3.8.10: $Python"
    exit 1
}

$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $VenvPython)) {
    Write-Host "Creating virtualenv $ProjectRoot\.venv"
    & $Python -m venv (Join-Path $ProjectRoot ".venv")
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
& $VenvPython -m pip install -U pip setuptools wheel
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $VenvPython -m pip install -r (Join-Path $ProjectRoot "requirements.txt")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host "Setup complete. Run run_pipeline.bat from $ProjectRoot"
exit 0
