using System.Collections.ObjectModel;
using System.IO;
using System.Net.Http;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using System.Xml.Linq;

namespace FarFarWestSaveStudio;

public sealed record SteamAccount(string SteamId, string Name, string Source, string AvatarUrl = "");

public sealed class InventoryEntry
{
    public InventoryEntry(string name, string category, int value, int offset)
    {
        Name = name;
        Category = category;
        Value = value;
        Offset = offset;
    }

    public string Name { get; }
    public string Category { get; }
    public int Value { get; set; }
    public int Offset { get; }
}
public sealed record LoadedSave(byte[] Plaintext, string CryptoProfile, string SteamId, ObservableCollection<InventoryEntry> Entries);

public static partial class SaveCore
{
    public const string DefaultPartySuffix = "NicoArnoEvilRaptorFireshineRobbo";
    public static readonly string SaveDir = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "FarFarWest", "Saved", "SaveGames");

    [GeneratedRegex(@"^(\d{15,20})")]
    private static partial Regex SteamIdPrefixRegex();

    [GeneratedRegex(@"""(?<steamid>\d{15,20})""\s*\{(?<body>.*?)\n\s*\}", RegexOptions.Singleline)]
    private static partial Regex LoginUserRegex();

    [GeneratedRegex(@"""([^""]+)""\s+""([^""]*)""")]
    private static partial Regex VdfFieldRegex();

    public static string InferSteamId(string path)
    {
        var match = SteamIdPrefixRegex().Match(Path.GetFileName(path));
        if (!match.Success)
            throw new InvalidOperationException("Could not infer SteamID from the save filename.");
        return match.Groups[1].Value;
    }

    public static List<SteamAccount> DiscoverSteamAccounts()
    {
        var accounts = new List<SteamAccount>();
        var seen = new HashSet<string>();
        foreach (var steamPath in SteamInstallCandidates())
        {
            var loginUsers = Path.Combine(steamPath, "config", "loginusers.vdf");
            if (!File.Exists(loginUsers)) continue;
            var text = File.ReadAllText(loginUsers, Encoding.UTF8);
            foreach (Match match in LoginUserRegex().Matches(text))
            {
                var steamId = match.Groups["steamid"].Value;
                if (!seen.Add(steamId)) continue;
                var body = match.Groups["body"].Value;
                var fields = VdfFieldRegex().Matches(body).ToDictionary(m => m.Groups[1].Value, m => m.Groups[2].Value);
                var name = fields.TryGetValue("PersonaName", out var persona) ? persona :
                    fields.TryGetValue("AccountName", out var accountName) ? accountName : "Steam account";
                if (fields.TryGetValue("MostRecent", out var recent) && recent == "1") name += " (most recent)";
                accounts.Add(new SteamAccount(steamId, name, loginUsers));
            }
        }

        if (Directory.Exists(SaveDir))
        {
            foreach (var save in Directory.GetFiles(SaveDir, "*.save").OrderByDescending(File.GetLastWriteTime))
            {
                var match = SteamIdPrefixRegex().Match(Path.GetFileName(save));
                if (match.Success && seen.Add(match.Groups[1].Value))
                    accounts.Add(new SteamAccount(match.Groups[1].Value, "Save file", save));
            }
        }
        return accounts;
    }

    public static async Task<SteamAccount> FetchSteamProfileAsync(string steamId)
    {
        using var http = new HttpClient { Timeout = TimeSpan.FromSeconds(8) };
        var xml = await http.GetStringAsync($"https://steamcommunity.com/profiles/{steamId}/?xml=1");
        var doc = XDocument.Parse(xml);
        var root = doc.Root;
        var name = root?.Element("steamID")?.Value;
        var avatar = root?.Element("avatarMedium")?.Value ?? root?.Element("avatarFull")?.Value ?? "";
        return new SteamAccount(steamId, string.IsNullOrWhiteSpace(name) ? "Steam account" : name, "steamcommunity.com", avatar);
    }

    public static async Task<string> ResolveSteamIdAsync(string value)
    {
        value = value.Trim();
        if (Regex.IsMatch(value, @"^\d{15,20}$")) return value;
        var uriText = value.Contains("://", StringComparison.Ordinal) ? value : $"https://steamcommunity.com/id/{value}";
        var uri = new Uri(uriText);
        var parts = uri.AbsolutePath.Split('/', StringSplitOptions.RemoveEmptyEntries);
        if (parts.Length >= 2 && parts[0].Equals("profiles", StringComparison.OrdinalIgnoreCase) && Regex.IsMatch(parts[1], @"^\d{15,20}$"))
            return parts[1];
        var vanity = parts.Length >= 2 && parts[0].Equals("id", StringComparison.OrdinalIgnoreCase) ? parts[1] : value.Trim('/');
        using var http = new HttpClient { Timeout = TimeSpan.FromSeconds(10) };
        var xml = await http.GetStringAsync($"https://steamcommunity.com/id/{Uri.EscapeDataString(vanity)}/?xml=1");
        var match = Regex.Match(xml, @"<steamID64>(\d{15,20})</steamID64>");
        if (!match.Success) throw new InvalidOperationException("Steam did not return a SteamID64 for that profile.");
        return match.Groups[1].Value;
    }

    public static LoadedSave LoadSave(string path, string? steamId, string partySuffix)
    {
        var sourceSteamId = string.IsNullOrWhiteSpace(steamId) ? InferSteamId(path) : steamId.Trim();
        var cipher = File.ReadAllBytes(path);
        var (plain, profile) = DecryptWithDetect(cipher, sourceSteamId, partySuffix);
        return new LoadedSave(plain, profile, sourceSteamId, new ObservableCollection<InventoryEntry>(ParseRuntimeInventory(plain)));
    }

    public static void TransferSave(string source, string output, string sourceSteamId, string targetSteamId, string partySuffix, bool rewritePayload)
    {
        var cipher = File.ReadAllBytes(source);
        var (plain, profile) = DecryptWithDetect(cipher, sourceSteamId, partySuffix);
        if (rewritePayload)
            plain = RewriteSteamIdPayload(plain, sourceSteamId, targetSteamId);
        WriteEncrypted(output, plain, targetSteamId, partySuffix, profile, true);
    }

    public static void SaveEdited(string output, LoadedSave loaded, IEnumerable<InventoryEntry> entries, string partySuffix)
    {
        var data = loaded.Plaintext.ToArray();
        foreach (var entry in entries)
            BitConverter.GetBytes(entry.Value).CopyTo(data, entry.Offset);
        WriteEncrypted(output, data, loaded.SteamId, partySuffix, loaded.CryptoProfile, true);
    }

    private static void WriteEncrypted(string output, byte[] plain, string steamId, string suffix, string profile, bool backup)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(output)!);
        if (backup && File.Exists(output))
            File.Copy(output, $"{output}.backup_{DateTime.Now:yyyyMMdd_HHmmss}", true);
        var (key, iv) = DeriveProfile(steamId, suffix, profile);
        File.WriteAllBytes(output, AesEncrypt(plain, key, iv));
    }

    private static (byte[] Plain, string Profile) DecryptWithDetect(byte[] cipher, string steamId, string suffix)
    {
        foreach (var profile in Profiles())
        {
            var (key, iv) = DeriveProfile(steamId, suffix, profile);
            try
            {
                var raw = AesDecrypt(cipher, key, iv);
                var candidates = new[] { Unpad(raw) ?? raw, raw };
                foreach (var candidate in candidates)
                    if (LooksLikeSave(candidate)) return (candidate, profile);
            }
            catch
            {
                // Try next profile.
            }
        }
        throw new InvalidOperationException("Could not decrypt save with the built-in filename-derived profiles.");
    }

    private static List<InventoryEntry> ParseRuntimeInventory(byte[] plain)
    {
        var text = Encoding.Latin1.GetString(plain);
        var start = text.IndexOf("runtimeInventory", StringComparison.Ordinal);
        if (start < 0) return [];
        var end = new[] { "challenge", "stats", "reward" }
            .Select(token => text.IndexOf(token, start + 1, StringComparison.Ordinal))
            .Where(pos => pos > start)
            .DefaultIfEmpty(text.Length)
            .Min();
        var section = text[start..end];
        var regex = new Regex(@"name_2_.*?NameProperty\0.*?([A-Za-z][A-Za-z0-9_]+)\0.*?amount_5_.*?IntProperty\0(.{9})(.{4})", RegexOptions.Singleline);
        var entries = new List<InventoryEntry>();
        foreach (Match match in regex.Matches(section))
        {
            var name = match.Groups[1].Value;
            var offset = start + match.Groups[3].Index;
            var value = BitConverter.ToInt32(plain, offset);
            if (value is >= -1_000_000_000 and <= 1_000_000_000)
                entries.Add(new InventoryEntry(name, Category(name), value, offset));
        }
        return entries;
    }

    private static string Category(string name) =>
        name switch
        {
            var n when n.StartsWith("money") => "Currency",
            var n when n.StartsWith("item") && n.Contains("Fragment") => "Fragments",
            var n when n.StartsWith("item") => "Items",
            var n when n.StartsWith("joker") => "Jokers",
            var n when n.StartsWith("skin") => "Skins",
            var n when n.StartsWith("mount") => "Mounts",
            var n when n.StartsWith("quest") => "Quests",
            var n when n.StartsWith("musicDisc") => "Music",
            var n when n.StartsWith("map") => "Map",
            _ => "Other"
        };

    private static byte[] RewriteSteamIdPayload(byte[] plain, string oldId, string newId)
    {
        if (oldId.Length != newId.Length) throw new InvalidOperationException("SteamID rewrite requires equal-length SteamID64 values.");
        var ascii = Encoding.Latin1.GetString(plain).Replace(oldId, newId, StringComparison.Ordinal);
        return Encoding.Latin1.GetBytes(ascii);
    }

    private static bool LooksLikeSave(byte[] plain)
    {
        var window = Encoding.Latin1.GetString(plain.AsSpan(0, Math.Min(64, plain.Length)));
        return window.Contains("GVAS", StringComparison.Ordinal);
    }

    private static byte[] AesDecrypt(byte[] cipher, byte[] key, byte[] iv)
    {
        using var aes = Aes.Create();
        aes.KeySize = 256;
        aes.Mode = CipherMode.CBC;
        aes.Padding = PaddingMode.None;
        aes.Key = key;
        aes.IV = iv;
        using var decryptor = aes.CreateDecryptor();
        return decryptor.TransformFinalBlock(cipher, 0, cipher.Length);
    }

    private static byte[] AesEncrypt(byte[] plain, byte[] key, byte[] iv)
    {
        using var aes = Aes.Create();
        aes.KeySize = 256;
        aes.Mode = CipherMode.CBC;
        aes.Padding = PaddingMode.PKCS7;
        aes.Key = key;
        aes.IV = iv;
        using var encryptor = aes.CreateEncryptor();
        return encryptor.TransformFinalBlock(plain, 0, plain.Length);
    }

    private static byte[]? Unpad(byte[] data)
    {
        if (data.Length == 0) return null;
        var pad = data[^1];
        if (pad is < 1 or > 16 || pad > data.Length) return null;
        for (var i = data.Length - pad; i < data.Length; i++)
            if (data[i] != pad) return null;
        return data[..^pad];
    }

    private static (byte[] Key, byte[] Iv) DeriveProfile(string steamId, string suffix, string profile)
    {
        var seed = profile.Contains("utf16le", StringComparison.Ordinal) ? Encoding.Unicode.GetBytes(steamId + suffix) : Encoding.UTF8.GetBytes(steamId + suffix);
        var sha = SHA256.HashData(seed);
        return profile switch
        {
            "sha256(utf8) key, zero iv" or "sha256(utf16le) key, zero iv" => (sha, new byte[16]),
            "sha256(utf8) key, md5(seed) iv" or "sha256(utf16le) key, md5(seed) iv" => (sha, MD5.HashData(seed)),
            "sha256(utf8) key, sha256(seed)[:16] iv" or "sha256(utf16le) key, sha256(seed)[:16] iv" => (sha, sha[..16]),
            _ => (sha, SHA256.HashData(Encoding.UTF8.GetBytes("iv").Concat(seed).ToArray())[..16])
        };
    }

    private static string[] Profiles() =>
    [
        "sha256(utf8) key, zero iv",
        "sha256(utf8) key, md5(seed) iv",
        "sha256(utf8) key, sha256(seed)[:16] iv",
        "sha256(utf8) key, sha256(iv+seed)[:16] iv",
        "sha256(utf16le) key, zero iv",
        "sha256(utf16le) key, md5(seed) iv",
        "sha256(utf16le) key, sha256(seed)[:16] iv",
        "sha256(utf16le) key, sha256(iv+seed)[:16] iv",
    ];

    private static IEnumerable<string> SteamInstallCandidates()
    {
        var candidates = new List<string>();
        var pf86 = Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86);
        var pf = Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles);
        if (!string.IsNullOrWhiteSpace(pf86)) candidates.Add(Path.Combine(pf86, "Steam"));
        if (!string.IsNullOrWhiteSpace(pf)) candidates.Add(Path.Combine(pf, "Steam"));
        candidates.Add(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Steam"));
        return candidates.Distinct(StringComparer.OrdinalIgnoreCase);
    }
}
