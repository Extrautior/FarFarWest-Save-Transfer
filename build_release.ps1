$ErrorActionPreference = "Stop"

python -m pip install -r requirements.txt
python -m PyInstaller --onefile --name FarFarWestSaveTransfer ffw_save_transfer.py
python -m PyInstaller --onefile --windowed --name FarFarWestSaveTransferUI ffw_save_transfer_gui.py

Write-Host ""
Write-Host "Build complete:"
Write-Host "  dist\FarFarWestSaveTransfer.exe"
Write-Host "  dist\FarFarWestSaveTransferUI.exe"
