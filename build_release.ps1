$ErrorActionPreference = "Stop"

New-Item -ItemType Directory -Force -Path dist | Out-Null

npm install --prefix app
$env:Path = "$env:USERPROFILE\.cargo\bin;$env:Path"
.\app\node_modules\.bin\tauri.cmd build
Copy-Item .\src-tauri\target\release\FarFarWestSaveStudio.exe .\dist\FarFarWestSaveStudio.exe -Force

python -m pip install -r requirements.txt
python -m PyInstaller --onefile --name FarFarWestSaveTransfer ffw_save_transfer.py --clean --noconfirm

Write-Host ""
Write-Host "Build complete:"
Write-Host "  dist\FarFarWestSaveStudio.exe"
Write-Host "  dist\FarFarWestSaveTransfer.exe"
