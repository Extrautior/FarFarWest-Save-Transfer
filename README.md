# Far Far West Save Transfer

Windows utility for transferring and editing **Far Far West** save files.

The game save encryption appears to use the save filename / SteamID as part of its key material. This tool decrypts a source `.save`, optionally rewrites old SteamID text occurrences inside the payload, and re-encrypts the save for the destination SteamID.

> Unofficial tool. Keep backups of important saves.

## Features

- Native Windows UI built with WPF / .NET
- Fast virtualized editor grid for save values
- Sidebar navigation for transfer, runtime inventory editing, and activity logs
- Command-line mode for advanced users
- Source SteamID detection from `.save` filename
- Local Steam account discovery from `loginusers.vdf`
- SteamID discovery from existing Far Far West save filenames
- Steam profile URL / vanity name resolution
- Steam account avatars where Steam Community profile data is available
- Account picker embedded directly in the transfer screen
- Real runtimeInventory editor for editable integer values found in the decrypted save
- Category filters for currency, items, fragments, jokers, skins, mounts, quests, music, map, and other values
- Category rail with counts and grouped editor rows
- Safe backup creation before overwriting existing edited output
- Re-encrypts transferred saves for the target Steam account
- Writes a new output file instead of overwriting the original

## Download

Download the latest Windows build from the [Releases](https://github.com/Extrautior/FarFarWest-Save-Transfer/releases) page.

Recommended file:

```text
FarFarWestSaveStudio.exe
```

## Transfer Usage

1. Open `FarFarWestSaveStudio.exe`.
2. Click **Browse** and choose the old account `.save`.
3. Choose the target account from the Steam Accounts tab, or enter/resolve a SteamID64 manually.
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
- .NET SDK 9.0+ for the native WPF app

Build the native WPF app and legacy Python builds:

```powershell
.\build_release.ps1
```

Manual setup:

```powershell
python -m pip install -r requirements.txt
python -m PyInstaller --onefile --name FarFarWestSaveTransfer ffw_save_transfer.py
python -m PyInstaller --onefile --windowed --name FarFarWestSaveTransferUI ffw_save_transfer_gui.py
dotnet publish src\FarFarWestSaveStudio\FarFarWestSaveStudio.csproj -c Release -r win-x64 --self-contained true -p:PublishSingleFile=true -p:IncludeNativeLibrariesForSelfExtract=true -p:EnableCompressionInSingleFile=true -o dist\wpf
```

## Technical Notes

- The source save filename should start with the old SteamID64, for example `7656119xxxxxxxxxx.save`.
- The default party suffix is `NicoArnoEvilRaptorFireshineRobbo`.
- If your party composition differs, pass a custom suffix with `--party-suffix`.
- If the game only needs re-encryption and does not like payload SteamID replacement, retry with `--no-payload-rewrite`.
- The tool tries multiple AES-256-CBC key/IV layouts and validates the decrypted payload against the Unreal `GVAS` save header.
- The Save Editor currently edits integer values in the `runtimeInventory` block. This covers discovered values such as currency, owned items, fragments, jokers, skins, quests, mounts, music, and map entries.
- Item XP/level and challenge-stat editing require more schema mapping and are intentionally not written yet.

## Legal

This project is not affiliated with Far Far West, its developers, Steam, or Valve.
