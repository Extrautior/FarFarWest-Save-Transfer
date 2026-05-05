# Far Far West Save Transfer

Windows utility for transferring **Far Far West** save files from one Steam account to another.

The game save encryption appears to use the save filename / SteamID as part of its key material. This tool decrypts a source `.save`, optionally rewrites old SteamID text occurrences inside the payload, and re-encrypts the save for the destination SteamID.

> Unofficial tool. Keep backups of important saves.

## Features

- Simple Windows UI
- Command-line mode for advanced users
- Source SteamID detection from `.save` filename
- Local Steam account discovery from `loginusers.vdf`
- SteamID discovery from existing Far Far West save filenames
- Steam profile URL / vanity name resolution
- Re-encrypts transferred saves for the target Steam account
- Writes a new output file instead of overwriting the original

## Download

Download the latest Windows build from the [Releases](https://github.com/Extrautior/FarFarWest-Save-Transfer/releases) page.

Recommended file:

```text
FarFarWestSaveTransferUI.exe
```

## Usage

1. Open `FarFarWestSaveTransferUI.exe`.
2. Click **Browse** and choose the old account `.save`.
3. Choose or enter the target SteamID64.
4. Click **Transfer Save**.
5. Copy the generated `<target SteamID>.save` into the target account save folder.

Default Far Far West save folder:

```text
%LOCALAPPDATA%\FarFarWest\Saved\SaveGames
```

## Command Line

```powershell
python ffw_save_transfer.py "C:\path\to\7656119OLD.save" 7656119NEW
```

Useful options:

```powershell
python ffw_save_transfer.py "old.save" 7656119NEW --no-payload-rewrite
python ffw_save_transfer.py "old.save" 7656119NEW --party-suffix "YourPartySuffixHere"
python ffw_save_transfer.py "old.save" 7656119NEW -o "C:\path\to\7656119NEW.save"
```

## Build From Source

Requirements:

- Windows
- Python 3.11+

Build both executables:

```powershell
.\build_release.ps1
```

Manual setup:

```powershell
python -m pip install -r requirements.txt
python -m PyInstaller --onefile --name FarFarWestSaveTransfer ffw_save_transfer.py
python -m PyInstaller --onefile --windowed --name FarFarWestSaveTransferUI ffw_save_transfer_gui.py
```

## Technical Notes

- The source save filename should start with the old SteamID64, for example `7656119xxxxxxxxxx.save`.
- The default party suffix is `NicoArnoEvilRaptorFireshineRobbo`.
- If your party composition differs, pass a custom suffix with `--party-suffix`.
- If the game only needs re-encryption and does not like payload SteamID replacement, retry with `--no-payload-rewrite`.
- The tool tries multiple AES-256-CBC key/IV layouts and validates the decrypted payload against the Unreal `GVAS` save header.

## Legal

This project is not affiliated with Far Far West, its developers, Steam, or Valve.
