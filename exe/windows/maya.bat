@REM @echo off
:: MAYA

set "MAYA_VERSION=2024"
set "MAYA_PATH=C:/Program Files/Autodesk/Maya%MAYA_VERSION%"

:: --- PATH ---
set "PROJECT_ROOT=D:\personal\advance_python\python\final\my_asset_loader"
@REM set "PROJECT_PATH=%PROJECT_ROOT%/_my_project"

:: Find and add script folder to PYTHONPATH
set "APP_PATH=%PROJECT_ROOT%"
set "SCRIPT_PATH=%APP_PATH%/scripts"
set "PYTHONPATH=%APP_PATH%;%SCRIPT_PATH%;%PYTHONPATH%"

:: Add scripts folder to MAYA_SCRIPT_PATH so userSetup.py auto-runs on startup
set "MAYA_SCRIPT_PATH=%SCRIPT_PATH%;%MAYA_SCRIPT_PATH%"

:: --- PLUGIN ---
set "MAYA_PLUG_IN_PATH=%PLUGINS_PATH%;%MAYA_PLUG_IN_PATH%"

:: --- SHELF ---
set "MAYA_SHELF_PATH=%SOFTWARE_PATH%/shelf;%MAYA_SHELF_PATH%"

:: --- DISABLE REPORT ---
set "MAYA_DISABLE_CIP=1"
set "MAYA_DISABLE_CER=1"

:: --- CALL MAYA ---
set "PATH=%MAYA_PATH%/bin;%PATH%"

if "%1"=="" (
  start "" "%MAYA_PATH%\bin\maya.exe"
) else (
  start "" "%MAYA_PATH%\bin\maya.exe" -file "%1"
)

@REM pause

@REM exit