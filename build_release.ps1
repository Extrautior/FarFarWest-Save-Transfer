$ErrorActionPreference = "Stop"

python -m pip install -r requirements.txt
python -m PyInstaller --onefile --name FarFarWestSaveTransfer ffw_save_transfer.py --clean --noconfirm
python -m PyInstaller --onefile --windowed --name FarFarWestSaveTransferUI ffw_save_transfer_gui.py --clean --noconfirm
dotnet publish src\FarFarWestSaveStudio\FarFarWestSaveStudio.csproj -c Release -r win-x64 --self-contained true -p:PublishSingleFile=true -p:IncludeNativeLibrariesForSelfExtract=true -p:EnableCompressionInSingleFile=true -o dist\wpf

Write-Host ""
Write-Host "Build complete:"
Write-Host "  dist\wpf\FarFarWestSaveStudio.exe"
Write-Host "  dist\FarFarWestSaveTransfer.exe"
Write-Host "  dist\FarFarWestSaveTransferUI.exe"
