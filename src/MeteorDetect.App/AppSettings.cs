using System;
using System.IO;
using System.Runtime.InteropServices;
using System.Text.Json;
using System.Threading.Tasks;

namespace MeteorDetect.App;

public sealed class AppSettings
{
    public string? ResolveScriptDirectory { get; set; }

    public bool WriteCombinedJson { get; set; }

    public bool IgnoreCameraBumps { get; set; }

    public string DetectorAlgorithm { get; set; } = DetectorAlgorithms.Accurate;

    public bool FastPrefilter { get; set; }
}

public static class SettingsStore
{
    public static string SettingsDirectory => Path.Combine(GetConfigRoot(), "MeteorDetect");

    public static string SettingsPath => Path.Combine(SettingsDirectory, "settings.json");

    public static async Task<AppSettings> LoadAsync()
    {
        if (!File.Exists(SettingsPath))
        {
            return new AppSettings();
        }

        await using var stream = File.OpenRead(SettingsPath);
        return await JsonSerializer.DeserializeAsync(stream, AppJsonContext.Default.AppSettings) ?? new AppSettings();
    }

    public static async Task SaveAsync(AppSettings settings)
    {
        Directory.CreateDirectory(SettingsDirectory);
        await using var stream = File.Create(SettingsPath);
        await JsonSerializer.SerializeAsync(stream, settings, AppJsonContext.Default.AppSettings);
    }

    private static string GetConfigRoot()
    {
        if (RuntimeInformation.IsOSPlatform(OSPlatform.Windows))
        {
            return Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData);
        }

        if (RuntimeInformation.IsOSPlatform(OSPlatform.OSX))
        {
            return Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.UserProfile),
                "Library",
                "Application Support");
        }

        var xdgConfigHome = Environment.GetEnvironmentVariable("XDG_CONFIG_HOME");
        if (!string.IsNullOrWhiteSpace(xdgConfigHome))
        {
            return xdgConfigHome;
        }

        return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), ".config");
    }
}
