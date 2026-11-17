@echo off
setlocal EnableExtensions
set "ROOT=%FXJEFE_PROJECT_DIR%"
if "%ROOT%"=="" set "ROOT=%USERPROFILE%\Documents\FXJEFE_Project"
if not exist "%ROOT%\run_pipeline.py" (
    echo PROJECT_ROOT does not exist or has no run_pipeline.py: %ROOT%
    echo Clone this repo to %%USERPROFILE%%\Documents\FXJEFE_Project or set FXJEFE_PROJECT_DIR.
    exit /b 1
)
if not exist "%ROOT%\.venv\Scripts\activate.bat" (
    echo Virtualenv not found at %ROOT%\.venv
    echo Run setup_windows.bat first.
    exit /b 1
)
call "%ROOT%\.venv\Scripts\activate.bat"
cd /d "%ROOT%"
python run_pipeline.py --project-dir "%ROOT%" %*
exit /b %ERRORLEVEL%
