# Far Far West Save Studio

Modern Windows desktop utility for transferring and editing **Far Far West** save files between Steam accounts.

The game save encryption appears to use the save filename / SteamID as part of its key material. This tool decrypts a source `.save`, optionally rewrites old SteamID text occurrences inside the payload, and re-encrypts the save for the destination SteamID.

> Unofficial tool. Keep backups of important saves.

## Features

- Modern Tauri v2 + React + TypeScript desktop app
- Small, snappy Windows `.exe` with Rust backend commands
- Polished sidebar layout for transfer, save editing, and activity logs
- Fast virtualized editor table for save values
- Command-line mode for advanced users
- Source SteamID detection from `.save` filename
- Local Steam account discovery from the Steam registry install path and `config/loginusers.vdf`
- SteamID discovery from existing Far Far West save filenames
- Steam profile URL / vanity name resolution
- Steam account avatars where Steam Community profile data is available
- Scrollable account picker embedded directly in the transfer screen
- Real runtimeInventory editor for editable integer values found in the decrypted save
- Category filters for currency, items, fragments, jokers, skins, mounts, quests, music, map, and other values
- Category rail with counts, search, and inline numeric editing
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
3. Choose the target account from the account picker, or enter/resolve a SteamID64/profile URL manually.
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
- Rust + Cargo
- Node.js 20+
- Python 3.11+

Build the modern Tauri app and legacy command-line build:

```powershell
.\build_release.ps1
```

Manual setup:

```powershell
npm install --prefix app
npm run build --prefix app
.\app\node_modules\.bin\tauri.cmd build
Copy-Item .\src-tauri\target\release\FarFarWestSaveStudio.exe .\dist\FarFarWestSaveStudio.exe -Force
python -m pip install -r requirements.txt
python -m PyInstaller --onefile --name FarFarWestSaveTransfer ffw_save_transfer.py
```

The old Python and WPF sources remain in the repo as legacy tooling, but the recommended UI is the Tauri app in `app/` and `src-tauri/`.

## Technical Notes

- The source save filename should start with the old SteamID64, for example `7656119xxxxxxxxxx.save`.
- The default party suffix is `NicoArnoEvilRaptorFireshineRobbo`.
- If your party composition differs, pass a custom suffix with `--party-suffix`.
- If the game only needs re-encryption and does not like payload SteamID replacement, retry with `--no-payload-rewrite`.
- The tool tries multiple AES-256-CBC key/IV layouts and validates the decrypted payload against the Unreal `GVAS` save header.
- Steam installation is detected from `HKCU\Software\Valve\Steam`, `HKLM\SOFTWARE\WOW6432Node\Valve\Steam`, and `HKLM\SOFTWARE\Valve\Steam`, so non-default installs such as `D:\Steam` are supported.
- The Save Editor currently edits integer values in the `runtimeInventory` block. This covers discovered values such as currency, owned items, fragments, jokers, skins, quests, mounts, music, and map entries.
- Item XP/level and challenge-stat editing require more schema mapping and are intentionally not written yet.

## Legal

This project is not affiliated with Far Far West, its developers, Steam, or Valve.
