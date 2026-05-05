@echo off
setlocal
cd /d "%~dp0"
if "%~1"=="" (
  echo Drag your old .save file onto this BAT, or run:
  echo python ffw_save_transfer.py "old.save" TARGET_STEAMID64
  pause
  exit /b 1
)
set /p TARGET_STEAMID=Enter target SteamID64:
if exist "%~dp0dist\FarFarWestSaveTransfer.exe" (
  "%~dp0dist\FarFarWestSaveTransfer.exe" "%~1" "%TARGET_STEAMID%"
) else (
  python ffw_save_transfer.py "%~1" "%TARGET_STEAMID%"
)
pause
