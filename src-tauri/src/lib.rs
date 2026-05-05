use aes::Aes256;
use cbc::{Decryptor, Encryptor};
use cipher::block_padding::{NoPadding, Pkcs7};
use cipher::{BlockDecryptMut, BlockEncryptMut, KeyIvInit};
use md5::Md5;
use regex::Regex;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::{HashMap, HashSet};
use std::fs;
use std::path::{Path, PathBuf};
use tauri::Manager;
use time::format_description::well_known::Rfc3339;
use winreg::enums::{HKEY_CURRENT_USER, HKEY_LOCAL_MACHINE};
use winreg::RegKey;

const DEFAULT_PARTY_SUFFIX: &str = "NicoArnoEvilRaptorFireshineRobbo";
type Aes256CbcDec = Decryptor<Aes256>;
type Aes256CbcEnc = Encryptor<Aes256>;

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Account {
    pub steam_id: String,
    pub name: String,
    pub source: String,
    pub avatar_url: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct InventoryEntry {
    pub name: String,
    pub category: String,
    pub value: i32,
    pub offset: usize,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct SaveSummary {
    pub source_steam_id: String,
    pub crypto_profile: String,
    pub encrypted_size: usize,
    pub plaintext_size: usize,
    pub gvas_offset: Option<usize>,
    pub inventory_count: usize,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct TransferRequest {
    pub source_path: String,
    pub source_steam_id: Option<String>,
    pub target_steam_id: String,
    pub output_path: String,
    pub party_suffix: String,
    pub rewrite_payload: bool,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct InventoryUpdate {
    pub offset: usize,
    pub value: i32,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SaveInventoryRequest {
    pub source_path: String,
    pub output_path: String,
    pub steam_id: Option<String>,
    pub party_suffix: String,
    pub updates: Vec<InventoryUpdate>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct WriteResult {
    pub output_path: String,
    pub backup_path: Option<String>,
}

#[tauri::command]
fn discover_accounts() -> Result<Vec<Account>, String> {
    Ok(discover_accounts_impl())
}

#[tauri::command]
fn resolve_account(input: String) -> Result<Account, String> {
    let steam_id = resolve_steam_id(&input)?;
    fetch_steam_profile(&steam_id).or_else(|_| {
        Ok(Account {
            steam_id,
            name: "Steam account".to_string(),
            source: "manual".to_string(),
            avatar_url: None,
        })
    })
}

#[tauri::command]
fn load_save(path: String, steam_id: Option<String>, party_suffix: String) -> Result<SaveSummary, String> {
    let source_steam_id = steam_id.filter(|s| !s.trim().is_empty()).unwrap_or_else(|| infer_steam_id(&path).unwrap_or_default());
    if source_steam_id.is_empty() {
        return Err("Could not infer SteamID from save filename.".to_string());
    }
    let cipher = fs::read(&path).map_err(|e| e.to_string())?;
    let suffix = suffix_or_default(&party_suffix);
    let (plain, profile) = decrypt_with_detect(&cipher, &source_steam_id, &suffix)?;
    let entries = parse_runtime_inventory(&plain);
    Ok(SaveSummary {
        source_steam_id,
        crypto_profile: profile,
        encrypted_size: cipher.len(),
        plaintext_size: plain.len(),
        gvas_offset: find_bytes(&plain, b"GVAS"),
        inventory_count: entries.len(),
    })
}

#[tauri::command]
fn load_inventory(path: String, steam_id: Option<String>, party_suffix: String) -> Result<Vec<InventoryEntry>, String> {
    let source_steam_id = steam_id.filter(|s| !s.trim().is_empty()).unwrap_or_else(|| infer_steam_id(&path).unwrap_or_default());
    if source_steam_id.is_empty() {
        return Err("Could not infer SteamID from save filename.".to_string());
    }
    let cipher = fs::read(&path).map_err(|e| e.to_string())?;
    let suffix = suffix_or_default(&party_suffix);
    let (plain, _) = decrypt_with_detect(&cipher, &source_steam_id, &suffix)?;
    Ok(parse_runtime_inventory(&plain))
}

#[tauri::command]
fn transfer_save(request: TransferRequest) -> Result<WriteResult, String> {
    let source_steam_id = request
        .source_steam_id
        .filter(|s| !s.trim().is_empty())
        .unwrap_or_else(|| infer_steam_id(&request.source_path).unwrap_or_default());
    if source_steam_id.is_empty() {
        return Err("Could not infer source SteamID.".to_string());
    }
    let suffix = suffix_or_default(&request.party_suffix);
    let cipher = fs::read(&request.source_path).map_err(|e| e.to_string())?;
    let (mut plain, profile) = decrypt_with_detect(&cipher, &source_steam_id, &suffix)?;
    if request.rewrite_payload {
        plain = rewrite_steam_id_payload(&plain, &source_steam_id, &request.target_steam_id)?;
    }
    write_encrypted(&request.output_path, &plain, &request.target_steam_id, &suffix, &profile)
}

#[tauri::command]
fn save_inventory(request: SaveInventoryRequest) -> Result<WriteResult, String> {
    let steam_id = request
        .steam_id
        .filter(|s| !s.trim().is_empty())
        .unwrap_or_else(|| infer_steam_id(&request.source_path).unwrap_or_default());
    if steam_id.is_empty() {
        return Err("Could not infer SteamID.".to_string());
    }
    let suffix = suffix_or_default(&request.party_suffix);
    let cipher = fs::read(&request.source_path).map_err(|e| e.to_string())?;
    let (mut plain, profile) = decrypt_with_detect(&cipher, &steam_id, &suffix)?;
    for update in request.updates {
        if update.offset + 4 > plain.len() {
            return Err(format!("Invalid inventory offset: {}", update.offset));
        }
        plain[update.offset..update.offset + 4].copy_from_slice(&update.value.to_le_bytes());
    }
    write_encrypted(&request.output_path, &plain, &steam_id, &suffix, &profile)
}

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![
            discover_accounts,
            resolve_account,
            load_save,
            load_inventory,
            transfer_save,
            save_inventory
        ])
        .setup(|app| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.set_title("Far Far West Save Studio");
            }
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

fn discover_accounts_impl() -> Vec<Account> {
    let mut accounts = Vec::new();
    let mut seen = HashSet::new();

    for steam_path in steam_install_candidates() {
        let login_users = steam_path.join("config").join("loginusers.vdf");
        if !login_users.exists() {
            continue;
        }
        if let Ok(text) = fs::read_to_string(&login_users) {
            for account in parse_loginusers_vdf(&text, &login_users) {
                if seen.insert(account.steam_id.clone()) {
                    accounts.push(account);
                }
            }
        }
    }

    if let Some(save_dir) = save_dir() {
        if let Ok(read_dir) = fs::read_dir(&save_dir) {
            let mut saves: Vec<_> = read_dir.filter_map(Result::ok).collect();
            saves.sort_by_key(|entry| entry.metadata().and_then(|m| m.modified()).ok());
            saves.reverse();
            for entry in saves {
                let path = entry.path();
                if path.extension().and_then(|e| e.to_str()).map(|e| e.eq_ignore_ascii_case("save")) != Some(true) {
                    continue;
                }
                if let Some(id) = infer_steam_id(path.to_string_lossy().as_ref()) {
                    if seen.insert(id.clone()) {
                        accounts.push(Account {
                            steam_id: id,
                            name: "Save file".to_string(),
                            source: path.to_string_lossy().to_string(),
                            avatar_url: None,
                        });
                    }
                }
            }
        }
    }

    accounts
}

fn parse_loginusers_vdf(text: &str, path: &Path) -> Vec<Account> {
    let account_re = Regex::new(r#"(?s)"(?P<steamid>\d{15,20})"\s*\{(?P<body>.*?)\n\s*\}"#).unwrap();
    let field_re = Regex::new(r#""([^"]+)"\s+"([^"]*)""#).unwrap();
    let mut accounts = Vec::new();
    for caps in account_re.captures_iter(text) {
        let steam_id = caps["steamid"].to_string();
        let fields: HashMap<String, String> = field_re
            .captures_iter(&caps["body"])
            .map(|c| (c[1].to_string(), c[2].to_string()))
            .collect();
        let mut name = fields
            .get("PersonaName")
            .or_else(|| fields.get("AccountName"))
            .cloned()
            .unwrap_or_else(|| "Steam account".to_string());
        if fields.get("MostRecent").map(|v| v == "1").unwrap_or(false) {
            name.push_str(" (most recent)");
        }
        accounts.push(Account {
            steam_id,
            name,
            source: path.to_string_lossy().to_string(),
            avatar_url: None,
        });
    }
    accounts
}

fn steam_install_candidates() -> Vec<PathBuf> {
    let mut paths = Vec::new();
    let registry_values = [
        (HKEY_CURRENT_USER, "Software\\Valve\\Steam", "SteamPath"),
        (HKEY_LOCAL_MACHINE, "SOFTWARE\\WOW6432Node\\Valve\\Steam", "InstallPath"),
        (HKEY_LOCAL_MACHINE, "SOFTWARE\\Valve\\Steam", "InstallPath"),
    ];
    for (hkey, subkey, value) in registry_values {
        let root = RegKey::predef(hkey);
        if let Ok(key) = root.open_subkey(subkey) {
            if let Ok(path) = key.get_value::<String, _>(value) {
                if !path.trim().is_empty() {
                    paths.push(PathBuf::from(path));
                }
            }
        }
    }
    if let Some(program_files_x86) = std::env::var_os("ProgramFiles(x86)") {
        paths.push(PathBuf::from(program_files_x86).join("Steam"));
    }
    if let Some(program_files) = std::env::var_os("ProgramFiles") {
        paths.push(PathBuf::from(program_files).join("Steam"));
    }
    if let Some(local_app_data) = std::env::var_os("LOCALAPPDATA") {
        paths.push(PathBuf::from(local_app_data).join("Steam"));
    }
    for letter in b'A'..=b'Z' {
        let root = format!("{}:\\", letter as char);
        paths.push(PathBuf::from(&root).join("Steam"));
        paths.push(PathBuf::from(&root).join("Program Files (x86)").join("Steam"));
        paths.push(PathBuf::from(&root).join("Program Files").join("Steam"));
    }
    dedupe_paths(paths)
}

fn dedupe_paths(paths: Vec<PathBuf>) -> Vec<PathBuf> {
    let mut seen = HashSet::new();
    let mut out = Vec::new();
    for path in paths {
        let key = path.to_string_lossy().to_lowercase();
        if seen.insert(key) {
            out.push(path);
        }
    }
    out
}

fn save_dir() -> Option<PathBuf> {
    std::env::var_os("LOCALAPPDATA").map(|local| PathBuf::from(local).join("FarFarWest").join("Saved").join("SaveGames"))
}

fn fetch_steam_profile(steam_id: &str) -> Result<Account, String> {
    let body = reqwest::blocking::Client::builder()
        .timeout(std::time::Duration::from_secs(8))
        .build()
        .map_err(|e| e.to_string())?
        .get(format!("https://steamcommunity.com/profiles/{steam_id}/?xml=1"))
        .send()
        .map_err(|e| e.to_string())?
        .text()
        .map_err(|e| e.to_string())?;
    let name = capture_xml_text(&body, "steamID").unwrap_or_else(|| "Steam account".to_string());
    let avatar = capture_xml_text(&body, "avatarMedium")
        .or_else(|| capture_xml_text(&body, "avatarFull"))
        .filter(|url| url.starts_with("http://") || url.starts_with("https://"));
    Ok(Account {
        steam_id: steam_id.to_string(),
        name,
        source: "steamcommunity.com".to_string(),
        avatar_url: avatar,
    })
}

fn resolve_steam_id(input: &str) -> Result<String, String> {
    let value = input.trim();
    if Regex::new(r"^\d{15,20}$").unwrap().is_match(value) {
        return Ok(value.to_string());
    }
    let url = if value.contains("://") {
        value.to_string()
    } else {
        format!("https://steamcommunity.com/id/{value}")
    };
    let parts: Vec<_> = url.split('/').filter(|p| !p.is_empty()).collect();
    if let Some(idx) = parts.iter().position(|p| p.eq_ignore_ascii_case("profiles")) {
        if let Some(id) = parts.get(idx + 1) {
            if Regex::new(r"^\d{15,20}$").unwrap().is_match(id) {
                return Ok((*id).to_string());
            }
        }
    }
    let vanity = if let Some(idx) = parts.iter().position(|p| p.eq_ignore_ascii_case("id")) {
        parts.get(idx + 1).copied().unwrap_or(value)
    } else {
        value.trim_matches('/')
    };
    let body = reqwest::blocking::Client::builder()
        .timeout(std::time::Duration::from_secs(10))
        .build()
        .map_err(|e| e.to_string())?
        .get(format!("https://steamcommunity.com/id/{}/?xml=1", urlencoding::encode(vanity)))
        .send()
        .map_err(|e| e.to_string())?
        .text()
        .map_err(|e| e.to_string())?;
    capture_xml_text(&body, "steamID64").ok_or_else(|| "Steam did not return a SteamID64 for that profile.".to_string())
}

fn capture_xml_text(body: &str, tag: &str) -> Option<String> {
    let re = Regex::new(&format!(r"<{tag}>(?s:(.*?))</{tag}>")).ok()?;
    re.captures(body).map(|c| clean_xml_text(&c[1]))
}

fn clean_xml_text(value: &str) -> String {
    let trimmed = value.trim();
    let without_cdata = trimmed
        .strip_prefix("<![CDATA[")
        .and_then(|inner| inner.strip_suffix("]]>"))
        .unwrap_or(trimmed);
    html_unescape(without_cdata.trim())
}

fn html_unescape(value: &str) -> String {
    value
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", "\"")
        .replace("&apos;", "'")
}

fn suffix_or_default(value: &str) -> String {
    if value.trim().is_empty() {
        DEFAULT_PARTY_SUFFIX.to_string()
    } else {
        value.trim().to_string()
    }
}

fn infer_steam_id(path: &str) -> Option<String> {
    let name = Path::new(path).file_name()?.to_string_lossy();
    let re = Regex::new(r"^(\d{15,20})").unwrap();
    re.captures(&name).map(|c| c[1].to_string())
}

fn decrypt_with_detect(cipher: &[u8], steam_id: &str, suffix: &str) -> Result<(Vec<u8>, String), String> {
    for profile in profiles() {
        let (key, iv) = derive_profile(steam_id, suffix, profile);
        if let Ok(raw) = aes_decrypt(cipher, &key, &iv) {
            let unpadded = pkcs7_unpad(&raw).unwrap_or_else(|| raw.clone());
            for candidate in [&unpadded, &raw] {
                if looks_like_save(candidate) {
                    return Ok((candidate.clone(), profile.to_string()));
                }
            }
        }
    }
    Err("Could not decrypt save with the built-in filename-derived profiles.".to_string())
}

fn derive_profile(steam_id: &str, suffix: &str, profile: &str) -> ([u8; 32], [u8; 16]) {
    let seed = if profile.contains("utf16le") {
        (steam_id.to_string() + suffix).encode_utf16().flat_map(|u| u.to_le_bytes()).collect::<Vec<u8>>()
    } else {
        (steam_id.to_string() + suffix).into_bytes()
    };
    let key_bytes = Sha256::digest(&seed);
    let mut key = [0u8; 32];
    key.copy_from_slice(&key_bytes);
    let iv_vec = if profile.contains("zero iv") {
        vec![0u8; 16]
    } else if profile.contains("md5") {
        Md5::digest(&seed).to_vec()
    } else if profile.contains("sha256(seed)") {
        key_bytes[..16].to_vec()
    } else {
        let mut data = b"iv".to_vec();
        data.extend_from_slice(&seed);
        Sha256::digest(&data)[..16].to_vec()
    };
    let mut iv = [0u8; 16];
    iv.copy_from_slice(&iv_vec[..16]);
    (key, iv)
}

fn profiles() -> &'static [&'static str] {
    &[
        "sha256(utf8) key, zero iv",
        "sha256(utf8) key, md5(seed) iv",
        "sha256(utf8) key, sha256(seed)[:16] iv",
        "sha256(utf8) key, sha256(iv+seed)[:16] iv",
        "sha256(utf16le) key, zero iv",
        "sha256(utf16le) key, md5(seed) iv",
        "sha256(utf16le) key, sha256(seed)[:16] iv",
        "sha256(utf16le) key, sha256(iv+seed)[:16] iv",
    ]
}

fn aes_decrypt(cipher: &[u8], key: &[u8; 32], iv: &[u8; 16]) -> Result<Vec<u8>, String> {
    if cipher.len() % 16 != 0 {
        return Err("Encrypted save length is not a multiple of AES block size.".to_string());
    }
    Aes256CbcDec::new(key.into(), iv.into())
        .decrypt_padded_vec_mut::<NoPadding>(cipher)
        .map_err(|e| e.to_string())
}

fn aes_encrypt(plain: &[u8], key: &[u8; 32], iv: &[u8; 16]) -> Result<Vec<u8>, String> {
    Ok(Aes256CbcEnc::new(key.into(), iv.into()).encrypt_padded_vec_mut::<Pkcs7>(plain))
}

fn pkcs7_unpad(data: &[u8]) -> Option<Vec<u8>> {
    let pad = *data.last()? as usize;
    if pad == 0 || pad > 16 || pad > data.len() {
        return None;
    }
    if data[data.len() - pad..].iter().all(|b| *b as usize == pad) {
        Some(data[..data.len() - pad].to_vec())
    } else {
        None
    }
}

fn looks_like_save(plain: &[u8]) -> bool {
    let end = plain.len().min(64);
    find_bytes(&plain[..end], b"GVAS").is_some()
}

fn parse_runtime_inventory(plain: &[u8]) -> Vec<InventoryEntry> {
    let Some(start) = find_bytes(plain, b"runtimeInventory") else {
        return Vec::new();
    };
    let end = [b"challenge".as_slice(), b"stats".as_slice(), b"reward".as_slice()]
        .iter()
        .filter_map(|token| find_bytes(&plain[start + 1..], token).map(|pos| start + 1 + pos))
        .min()
        .unwrap_or(plain.len());
    let section = &plain[start..end];
    let Ok(re) = regex::bytes::Regex::new(
        r"(?s)name_2_.*?NameProperty\x00.*?([A-Za-z][A-Za-z0-9_]+)\x00.*?amount_5_.*?IntProperty\x00(.{9})(.{4})",
    ) else {
        return Vec::new();
    };
    let mut entries = Vec::new();
    for caps in re.captures_iter(section) {
        let name = String::from_utf8_lossy(&caps[1]).to_string();
        let offset = start + caps.get(3).unwrap().start();
        if offset + 4 <= plain.len() {
            let value = i32::from_le_bytes(plain[offset..offset + 4].try_into().unwrap());
            if (-1_000_000_000..=1_000_000_000).contains(&value) {
                entries.push(InventoryEntry {
                    category: inventory_category(&name),
                    name,
                    value,
                    offset,
                });
            }
        }
    }
    entries
}

fn inventory_category(name: &str) -> String {
    if name.starts_with("money") {
        "Currency"
    } else if name.starts_with("item") && name.contains("Fragment") {
        "Fragments"
    } else if name.starts_with("item") {
        "Items"
    } else if name.starts_with("joker") {
        "Jokers"
    } else if name.starts_with("skin") {
        "Skins"
    } else if name.starts_with("mount") {
        "Mounts"
    } else if name.starts_with("quest") {
        "Quests"
    } else if name.starts_with("musicDisc") {
        "Music"
    } else if name.starts_with("map") {
        "Map"
    } else {
        "Other"
    }
    .to_string()
}

fn rewrite_steam_id_payload(plain: &[u8], old_id: &str, new_id: &str) -> Result<Vec<u8>, String> {
    if old_id.len() != new_id.len() {
        return Err("Payload SteamID rewrite requires old and new SteamID strings to have the same length.".to_string());
    }
    let mut data = plain.to_vec();
    replace_bytes(&mut data, old_id.as_bytes(), new_id.as_bytes());
    let old_utf16 = old_id.encode_utf16().flat_map(|u| u.to_le_bytes()).collect::<Vec<u8>>();
    let new_utf16 = new_id.encode_utf16().flat_map(|u| u.to_le_bytes()).collect::<Vec<u8>>();
    replace_bytes(&mut data, &old_utf16, &new_utf16);
    Ok(data)
}

fn replace_bytes(data: &mut [u8], needle: &[u8], replacement: &[u8]) {
    if needle.len() != replacement.len() || needle.is_empty() {
        return;
    }
    let mut i = 0;
    while i + needle.len() <= data.len() {
        if &data[i..i + needle.len()] == needle {
            data[i..i + needle.len()].copy_from_slice(replacement);
            i += needle.len();
        } else {
            i += 1;
        }
    }
}

fn write_encrypted(output: &str, plain: &[u8], steam_id: &str, suffix: &str, profile: &str) -> Result<WriteResult, String> {
    let output_path = PathBuf::from(output);
    if let Some(parent) = output_path.parent() {
        fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    }
    let backup_path = if output_path.exists() {
        let stamp = time::OffsetDateTime::now_local()
            .unwrap_or_else(|_| time::OffsetDateTime::now_utc())
            .format(&Rfc3339)
            .unwrap_or_else(|_| "backup".to_string())
            .replace(':', "-");
        let backup = output_path.with_file_name(format!(
            "{}.backup_{}",
            output_path.file_name().unwrap_or_default().to_string_lossy(),
            stamp
        ));
        fs::copy(&output_path, &backup).map_err(|e| e.to_string())?;
        Some(backup.to_string_lossy().to_string())
    } else {
        None
    };
    let (key, iv) = derive_profile(steam_id, suffix, profile);
    let encrypted = aes_encrypt(plain, &key, &iv)?;
    fs::write(&output_path, encrypted).map_err(|e| e.to_string())?;
    Ok(WriteResult {
        output_path: output_path.to_string_lossy().to_string(),
        backup_path,
    })
}

fn find_bytes(haystack: &[u8], needle: &[u8]) -> Option<usize> {
    haystack.windows(needle.len()).position(|window| window == needle)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_loginusers_handles_multiline_account_blocks() {
        let text = r#""users"
{
    "76561198048257465"
    {
        "AccountName"        "daniel9085"
        "PersonaName"        "Mongrel"
        "MostRecent"        "1"
    }
    "76561199224864516"
    {
        "AccountName"        "danielfleer1"
        "PersonaName"        "Turkish Car"
    }
}"#;
        let accounts = parse_loginusers_vdf(text, Path::new("D:\\Steam\\config\\loginusers.vdf"));
        assert_eq!(accounts.len(), 2);
        assert_eq!(accounts[0].steam_id, "76561198048257465");
        assert_eq!(accounts[0].name, "Mongrel (most recent)");
        assert_eq!(accounts[1].name, "Turkish Car");
    }

    #[test]
    fn clean_xml_text_strips_cdata_wrappers() {
        assert_eq!(clean_xml_text("<![CDATA[Mongrel]]>"), "Mongrel");
        assert_eq!(clean_xml_text("https://example.com/avatar.jpg"), "https://example.com/avatar.jpg");
    }

    #[test]
    fn local_save_load_does_not_panic_when_available() {
        let Some(save_dir) = save_dir() else {
            return;
        };
        let Some(save) = fs::read_dir(save_dir)
            .ok()
            .into_iter()
            .flatten()
            .filter_map(Result::ok)
            .map(|entry| entry.path())
            .find(|path| infer_steam_id(path.to_string_lossy().as_ref()).is_some())
        else {
            return;
        };
        let path = save.to_string_lossy().to_string();
        let id = infer_steam_id(&path);
        let summary = load_save(path.clone(), id.clone(), DEFAULT_PARTY_SUFFIX.to_string()).expect("local save should decrypt");
        let inventory = load_inventory(path, id, DEFAULT_PARTY_SUFFIX.to_string()).expect("local inventory should load");
        assert_eq!(summary.inventory_count, inventory.len());
        assert!(inventory.len() >= 60, "local inventory should expose the full editable value set");
        assert!(inventory.iter().any(|entry| entry.name.starts_with("money")), "money entries should be present");
    }
}
