# Far Far West Save Transfer

Small Windows tool for transferring Far Far West saves from one Steam account to another.

This is a transfer-only helper for moving a `.save` from one Steam account to another.

It does not expose inventory/stat editing. It decrypts the source save, optionally replaces old SteamID text occurrences with the new SteamID, then re-encrypts with the destination SteamID-derived filename seed.

## Download / Run

Use the UI exe:

```text
dist\FarFarWestSaveTransferUI.exe
```

Or run the launcher:

```text
Run FarFarWest Transfer UI.bat
```

## Usage

CLI:

```powershell
python ffw_save_transfer.py "C:\path\to\7656119OLD.save" 7656119NEW
```

Or drag the old `.save` onto `Transfer FarFarWest Save.bat` and paste the new SteamID64 when prompted.

For the UI build, run:

```text
dist\FarFarWestSaveTransferUI.exe
```

The UI can discover SteamID candidates from:

- Steam's local `loginusers.vdf`
- Far Far West save filenames in `%LOCALAPPDATA%\FarFarWest\Saved\SaveGames`
- A pasted SteamID64, Steam profile URL, or Steam vanity name

The output defaults to:

```text
<target SteamID>.save
```

next to the source file. Your original save is not overwritten.

## Notes

- Default save folder: `%LOCALAPPDATA%\FarFarWest\Saved\SaveGames`
- The source filename should start with the old SteamID.
- The default party suffix is `NicoArnoEvilRaptorFireshineRobbo`, matching the public save-editor description.
- If your party composition differs, pass `--party-suffix "YourSuffixHere"`.
- If the game only needs re-encryption and dislikes payload SteamID replacement, retry with `--no-payload-rewrite`.
- This is an unofficial tool. Keep your own backup of important saves.
