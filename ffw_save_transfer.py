#!/usr/bin/env python3
"""
Transfer a Far Far West .save file from one SteamID filename seed to another.

The tool decrypts with the source SteamID-derived seed, optionally rewrites
SteamID text occurrences inside the decrypted payload, then re-encrypts with
the destination SteamID-derived seed.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import struct
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


DEFAULT_PARTY_SUFFIX = "NicoArnoEvilRaptorFireshineRobbo"
STEAM_ID_RE = re.compile(r"^(\d{15,20})")
BLOCK_SIZE = 16
SAVE_DIR = Path(os.environ.get("LOCALAPPDATA", "")) / "FarFarWest" / "Saved" / "SaveGames"


class TransferError(RuntimeError):
    pass


@dataclass(frozen=True)
class CryptoProfile:
    name: str
    derive: Callable[[str], tuple[bytes, bytes]]


@dataclass(frozen=True)
class SteamAccount:
    steam_id: str
    label: str
    source: str
    persona_name: str = ""
    avatar_url: str = ""


@dataclass(frozen=True)
class SaveInspection:
    source_steam_id: str
    crypto_profile: str
    plaintext_size: int
    encrypted_size: int
    steamid_ascii_count: int
    steamid_utf16_count: int
    gvas_offset: int


@dataclass(frozen=True)
class InventoryEntry:
    name: str
    value: int
    offset: int
    category: str


def sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def md5(data: bytes) -> bytes:
    return hashlib.md5(data).digest()


def seed_text(steam_id: str, party_suffix: str) -> str:
    return f"{steam_id}{party_suffix}"


def seed_variants(steam_id: str, party_suffix: str) -> Iterable[tuple[str, bytes]]:
    seed = seed_text(steam_id, party_suffix)
    yield "utf8", seed.encode("utf-8")
    yield "utf16le", seed.encode("utf-16le")


def crypto_profiles(steam_id: str, party_suffix: str) -> list[CryptoProfile]:
    profiles: list[CryptoProfile] = []
    for label, seed in seed_variants(steam_id, party_suffix):
        profiles.extend(
            [
                CryptoProfile(
                    f"sha256({label}) key, zero iv",
                    lambda _unused, seed=seed: (sha256(seed), bytes(16)),
                ),
                CryptoProfile(
                    f"sha256({label}) key, md5(seed) iv",
                    lambda _unused, seed=seed: (sha256(seed), md5(seed)),
                ),
                CryptoProfile(
                    f"sha256({label}) key, sha256(seed)[:16] iv",
                    lambda _unused, seed=seed: (sha256(seed), sha256(seed)[:16]),
                ),
                CryptoProfile(
                    f"sha256({label}) key, sha256(iv+seed)[:16] iv",
                    lambda _unused, seed=seed: (sha256(seed), sha256(b"iv" + seed)[:16]),
                ),
            ]
        )
    return profiles


def pkcs7_unpad(data: bytes) -> bytes | None:
    if not data:
        return None
    pad = data[-1]
    if pad < 1 or pad > BLOCK_SIZE or pad > len(data):
        return None
    if data[-pad:] != bytes([pad]) * pad:
        return None
    return data[:-pad]


def pkcs7_pad(data: bytes) -> bytes:
    pad = BLOCK_SIZE - (len(data) % BLOCK_SIZE)
    return data + bytes([pad]) * pad


def aes_cbc_decrypt(ciphertext: bytes, key: bytes, iv: bytes) -> bytes:
    if len(ciphertext) % BLOCK_SIZE:
        raise TransferError("Encrypted save length is not a multiple of AES block size.")
    decryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    return decryptor.update(ciphertext) + decryptor.finalize()


def aes_cbc_encrypt(plaintext: bytes, key: bytes, iv: bytes) -> bytes:
    encryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    return encryptor.update(pkcs7_pad(plaintext)) + encryptor.finalize()


def looks_like_save(plaintext: bytes) -> bool:
    if plaintext.startswith(b"GVAS"):
        return True
    return b"GVAS" in plaintext[:64]


def infer_steam_id(path: Path) -> str:
    match = STEAM_ID_RE.match(path.name)
    if not match:
        raise TransferError(
            f"Could not infer source SteamID from filename '{path.name}'. "
            "Rename it like 7656119xxxxxxxxxx.save or pass --source-steamid."
        )
    return match.group(1)


def parse_loginusers_vdf(path: Path) -> list[SteamAccount]:
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8", errors="ignore")
    accounts: list[SteamAccount] = []
    for match in re.finditer(r'"(?P<steamid>\d{15,20})"\s*\{(?P<body>.*?)\n\s*\}', text, re.S):
        steam_id = match.group("steamid")
        body = match.group("body")
        fields = dict(re.findall(r'"([^"]+)"\s+"([^"]*)"', body))
        name = fields.get("PersonaName") or fields.get("AccountName") or "Steam account"
        recent = " (most recent)" if fields.get("MostRecent") == "1" else ""
        accounts.append(SteamAccount(steam_id, f"{name}{recent} - {steam_id}", str(path)))
    return accounts


def steam_install_candidates() -> list[Path]:
    paths: list[Path] = []
    try:
        import winreg

        for root, key_name, value_name in [
            (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", "InstallPath"),
        ]:
            try:
                with winreg.OpenKey(root, key_name) as key:
                    value, _kind = winreg.QueryValueEx(key, value_name)
                    if value:
                        paths.append(Path(value))
            except OSError:
                pass
    except ImportError:
        pass

    for env_name in ("PROGRAMFILES(X86)", "PROGRAMFILES"):
        base = os.environ.get(env_name)
        if base:
            paths.append(Path(base) / "Steam")
    paths.append(Path.home() / "AppData" / "Local" / "Steam")

    unique: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path).lower()
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique


def discover_steam_accounts() -> list[SteamAccount]:
    accounts: list[SteamAccount] = []
    seen: set[str] = set()

    for steam_path in steam_install_candidates():
        for account in parse_loginusers_vdf(steam_path / "config" / "loginusers.vdf"):
            if account.steam_id not in seen:
                seen.add(account.steam_id)
                accounts.append(account)

    if SAVE_DIR.exists():
        for save in sorted(SAVE_DIR.glob("*.save"), key=lambda p: p.stat().st_mtime, reverse=True):
            match = STEAM_ID_RE.match(save.name)
            if match and match.group(1) not in seen:
                steam_id = match.group(1)
                seen.add(steam_id)
                accounts.append(SteamAccount(steam_id, f"Save file - {steam_id}", str(save)))

    return accounts


def fetch_steam_profile(steam_id: str, timeout: float = 8.0) -> SteamAccount:
    if not re.fullmatch(r"\d{15,20}", steam_id):
        raise TransferError("Steam profile lookup needs a SteamID64.")
    url = f"https://steamcommunity.com/profiles/{steam_id}/?xml=1"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="ignore")
    except urllib.error.URLError as exc:
        raise TransferError(f"Could not contact Steam Community for {steam_id}: {exc}") from exc
    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        raise TransferError(f"Steam Community returned invalid profile XML for {steam_id}.") from exc
    persona = root.findtext("steamID") or "Steam account"
    avatar = root.findtext("avatarMedium") or root.findtext("avatarFull") or root.findtext("avatarIcon") or ""
    return SteamAccount(steam_id, f"{persona} - {steam_id}", "steamcommunity.com", persona, avatar)


def resolve_steam_id_from_text(text: str, timeout: float = 10.0) -> str:
    value = text.strip()
    if not value:
        raise TransferError("Enter a SteamID64, Steam profile URL, or vanity name.")
    if re.fullmatch(r"\d{15,20}", value):
        return value

    parsed = urllib.parse.urlparse(value if "://" in value else f"https://steamcommunity.com/id/{value}")
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) >= 2 and parts[0].lower() == "profiles" and re.fullmatch(r"\d{15,20}", parts[1]):
        return parts[1]
    if len(parts) >= 2 and parts[0].lower() == "id":
        vanity = parts[1]
    else:
        vanity = value.strip("/")

    url = f"https://steamcommunity.com/id/{urllib.parse.quote(vanity)}/?xml=1"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="ignore")
    except urllib.error.URLError as exc:
        raise TransferError(f"Could not contact Steam Community to resolve '{value}': {exc}") from exc

    match = re.search(r"<steamID64>(\d{15,20})</steamID64>", body)
    if not match:
        raise TransferError(f"Steam Community did not return a SteamID64 for '{value}'.")
    return match.group(1)


def decrypt_save_file(path: str | Path, source_steam_id: str | None = None, party_suffix: str = DEFAULT_PARTY_SUFFIX) -> tuple[bytes, CryptoProfile, str]:
    source_path = Path(path).expanduser().resolve()
    if not source_path.exists():
        raise TransferError(f"Save does not exist: {source_path}")
    steam_id = source_steam_id or infer_steam_id(source_path)
    plaintext, profile = decrypt_with_detect(source_path.read_bytes(), steam_id, party_suffix)
    return plaintext, profile, steam_id


def encrypt_plaintext_for_steam_id(plaintext: bytes, steam_id: str, party_suffix: str, profile_name: str) -> bytes:
    target_profile = next((p for p in crypto_profiles(steam_id, party_suffix) if p.name == profile_name), None)
    if target_profile is None:
        raise TransferError(f"Unknown crypto profile: {profile_name}")
    key, iv = target_profile.derive(steam_id)
    return aes_cbc_encrypt(plaintext, key, iv)


def inventory_category(name: str) -> str:
    if name.startswith("money"):
        return "Currency"
    if name.startswith("item") and "Fragment" in name:
        return "Fragments"
    if name.startswith("item"):
        return "Items"
    if name.startswith("joker"):
        return "Jokers"
    if name.startswith("skin"):
        return "Skins"
    if name.startswith("mount"):
        return "Mounts"
    if name.startswith("quest"):
        return "Quests"
    if name.startswith("musicDisc"):
        return "Music"
    if name.startswith("map"):
        return "Map"
    return "Other"


def parse_runtime_inventory(plaintext: bytes) -> list[InventoryEntry]:
    start = plaintext.find(b"runtimeInventory")
    if start < 0:
        return []
    end_candidates = []
    for token in (b"challenge", b"stats", b"reward"):
        pos = plaintext.find(token, start + 1)
        if pos > start:
            end_candidates.append(pos)
    end = min(end_candidates) if end_candidates else len(plaintext)
    section = plaintext[start:end]
    pattern = re.compile(
        rb"name_2_.*?NameProperty\x00.*?([A-Za-z][A-Za-z0-9_]+)\x00"
        rb".*?amount_5_.*?IntProperty\x00(.{9})(.{4})",
        re.S,
    )
    entries: list[InventoryEntry] = []
    for match in pattern.finditer(section):
        name = match.group(1).decode("ascii", errors="ignore")
        offset = start + match.start(3)
        value = struct.unpack("<i", match.group(3))[0]
        if -1_000_000_000 <= value <= 1_000_000_000:
            entries.append(InventoryEntry(name, value, offset, inventory_category(name)))
    return entries


def write_inventory_values(plaintext: bytes, updates: dict[int, int]) -> bytes:
    data = bytearray(plaintext)
    for offset, value in updates.items():
        if offset < 0 or offset + 4 > len(data):
            raise TransferError(f"Invalid inventory offset: {offset}")
        data[offset : offset + 4] = struct.pack("<i", int(value))
    return bytes(data)


def save_edited_plaintext(
    output_save: str | Path,
    plaintext: bytes,
    steam_id: str,
    party_suffix: str,
    profile_name: str,
    create_backup: bool = True,
) -> Path:
    output_path = Path(output_save).expanduser().resolve()
    if create_backup and output_path.exists():
        backup = output_path.with_name(f"{output_path.name}.backup_{datetime.now():%Y%m%d_%H%M%S}")
        shutil.copy2(output_path, backup)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(encrypt_plaintext_for_steam_id(plaintext, steam_id, party_suffix, profile_name))
    return output_path


def inspect_save(path: str | Path, source_steam_id: str | None = None, party_suffix: str = DEFAULT_PARTY_SUFFIX) -> SaveInspection:
    source_path = Path(path).expanduser().resolve()
    plaintext, profile, steam_id = decrypt_save_file(source_path, source_steam_id, party_suffix)
    ciphertext = source_path.read_bytes()
    ascii_id = steam_id.encode("ascii")
    utf16_id = steam_id.encode("utf-16le")
    return SaveInspection(
        source_steam_id=steam_id,
        crypto_profile=profile.name,
        plaintext_size=len(plaintext),
        encrypted_size=len(ciphertext),
        steamid_ascii_count=plaintext.count(ascii_id),
        steamid_utf16_count=plaintext.count(utf16_id),
        gvas_offset=plaintext.find(b"GVAS"),
    )


def decrypt_with_detect(ciphertext: bytes, source_steam_id: str, party_suffix: str) -> tuple[bytes, CryptoProfile]:
    failures: list[str] = []
    for profile in crypto_profiles(source_steam_id, party_suffix):
        key, iv = profile.derive(source_steam_id)
        try:
            raw = aes_cbc_decrypt(ciphertext, key, iv)
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{profile.name}: {exc}")
            continue
        candidates = [raw]
        unpadded = pkcs7_unpad(raw)
        if unpadded is not None:
            candidates.insert(0, unpadded)
        for plaintext in candidates:
            if looks_like_save(plaintext):
                return plaintext, profile
        failures.append(f"{profile.name}: decrypted, but plaintext was not GVAS")
    raise TransferError(
        "Could not decrypt this save with the built-in filename-derived profiles.\n"
        "This usually means the party suffix differs, the game changed crypto, or the save is already corrupted.\n"
        "Tried:\n- " + "\n- ".join(failures)
    )


def rewrite_steam_id_payload(payload: bytes, old_id: str, new_id: str) -> tuple[bytes, int]:
    if len(old_id) != len(new_id):
        raise TransferError("Payload SteamID rewrite requires old and new SteamID strings to have the same length.")
    replacements = 0
    old_ascii = old_id.encode("ascii")
    new_ascii = new_id.encode("ascii")
    payload, count = payload.replace(old_ascii, new_ascii), payload.count(old_ascii)
    replacements += count

    old_utf16 = old_id.encode("utf-16le")
    new_utf16 = new_id.encode("utf-16le")
    count = payload.count(old_utf16)
    payload = payload.replace(old_utf16, new_utf16)
    replacements += count
    return payload, replacements


def unique_output_path(path: Path) -> Path:
    if not path.exists():
        return path
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return path.with_name(f"{path.stem}.transferred_{stamp}{path.suffix}")


def transfer_save(args: argparse.Namespace) -> int:
    source_path = Path(args.source_save).expanduser().resolve()
    if not source_path.exists():
        raise TransferError(f"Source save does not exist: {source_path}")
    if source_path.suffix.lower() != ".save":
        raise TransferError("Source file must end in .save")

    source_steam_id = args.source_steamid or infer_steam_id(source_path)
    target_steam_id = args.target_steamid
    if not STEAM_ID_RE.match(target_steam_id):
        raise TransferError("Target SteamID should be a SteamID64-style number.")

    output_path = Path(args.output).expanduser().resolve() if args.output else source_path.with_name(f"{target_steam_id}.save")
    output_path = unique_output_path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    ciphertext = source_path.read_bytes()
    plaintext, profile = decrypt_with_detect(ciphertext, source_steam_id, args.party_suffix)

    replacements = 0
    if not args.no_payload_rewrite:
        plaintext, replacements = rewrite_steam_id_payload(plaintext, source_steam_id, target_steam_id)

    target_profile = next(p for p in crypto_profiles(target_steam_id, args.party_suffix) if p.name == profile.name)
    key, iv = target_profile.derive(target_steam_id)
    transferred = aes_cbc_encrypt(plaintext, key, iv)
    output_path.write_bytes(transferred)

    if args.copy_original_backup:
        backup_path = source_path.with_name(f"{source_path.name}.transfer_backup_{datetime.now():%Y%m%d_%H%M%S}")
        shutil.copy2(source_path, backup_path)
        print(f"Original backup: {backup_path}")

    print(f"Source SteamID: {source_steam_id}")
    print(f"Target SteamID: {target_steam_id}")
    print(f"Crypto profile: {profile.name}")
    print(f"Payload SteamID replacements: {replacements}")
    print(f"Wrote transferred save: {output_path}")
    print("Put that file in %LOCALAPPDATA%\\FarFarWest\\Saved\\SaveGames for the target account.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Re-encrypt a Far Far West .save file for another Steam account.",
    )
    parser.add_argument("source_save", help="Path to the old account .save file")
    parser.add_argument("target_steamid", help="Destination account SteamID64")
    parser.add_argument("-o", "--output", help="Output .save path. Defaults to <target_steamid>.save next to source.")
    parser.add_argument("--source-steamid", help="Override source SteamID. Defaults to the digits at the start of the source filename.")
    parser.add_argument("--party-suffix", default=DEFAULT_PARTY_SUFFIX, help=f"Party suffix seed. Default: {DEFAULT_PARTY_SUFFIX}")
    parser.add_argument("--no-payload-rewrite", action="store_true", help="Only re-encrypt; do not replace old SteamID text inside decrypted payload.")
    parser.add_argument("--copy-original-backup", action="store_true", help="Also copy the original save next to itself before writing output.")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return transfer_save(args)
    except TransferError as exc:
        print(f"Transfer failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
