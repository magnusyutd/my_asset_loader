@echo off
setlocal

REM Resolve paths
set "APP_ROOT=%~dp0..\.."
for %%I in ("%APP_ROOT%") do set "APP_ROOT=%%~fI"
set "REPO_ROOT=%APP_ROOT%\.."
for %%I in ("%REPO_ROOT%") do set "REPO_ROOT=%%~fI"

set "RCC_EXE=C:\Autodesk\Autodesk_Maya_2020_ML_Windows_64bit_dlm\x64\Maya\ADSK\MAYA\bin\pyside2-rcc.exe"
if not "%~1"=="" set "RCC_EXE=%~1"

if not exist "%RCC_EXE%" (
    echo ERROR: pyside2-rcc not found at: "%RCC_EXE%"
    echo Pass a custom path as the first argument if needed.
    exit /b 1
)

echo Generating my_asset_loader_rc.py with: %RCC_EXE%
"%RCC_EXE%" -o "%APP_ROOT%\my_asset_loader_rc.py" "%APP_ROOT%\my_asset_loader.qrc"
if errorlevel 1 (
    echo ERROR: rcc generation failed.
    exit /b 1
)

echo Applying standalone-safe import patch...
py -3 "%APP_ROOT%\tools\patch_rc_import.py"
if errorlevel 1 (
    echo ERROR: post-patch step failed.
    exit /b 1
)

echo Done: %APP_ROOT%\my_asset_loader_rc.py
exit /b 0
