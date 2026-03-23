@echo off
setlocal

REM Resolve app root (from exe\windows -> app root)
set "APP_ROOT=%~dp0..\.."
for %%I in ("%APP_ROOT%") do set "APP_ROOT=%%~fI"

REM App root is now the project root (5_app folder removed)
set "REPO_ROOT=%APP_ROOT%"

REM search.py expands $PROJECT_ROOT from config/project.yaml
set "PROJECT_ROOT=%REPO_ROOT%"

REM Ensure project modules (scripts/, search.py, load.py) are importable
if defined PYTHONPATH (
    set "PYTHONPATH=%APP_ROOT%;%PYTHONPATH%"
) else (
    set "PYTHONPATH=%APP_ROOT%"
)

REM Prefer py launcher; fall back to python if unavailable
where py >nul 2>&1
if %ERRORLEVEL%==0 (
    start "" py -3 "%APP_ROOT%\my_asset_loader.py"
) else (
    start "" python "%APP_ROOT%\my_asset_loader.py"
)

endlocal
