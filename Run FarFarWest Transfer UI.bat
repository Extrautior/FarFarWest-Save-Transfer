@echo off
setlocal
cd /d "%~dp0"
if exist "%~dp0dist\FarFarWestSaveTransferUI.exe" (
  start "" "%~dp0dist\FarFarWestSaveTransferUI.exe"
) else (
  python ffw_save_transfer_gui.py
)
