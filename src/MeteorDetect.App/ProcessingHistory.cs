using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Threading.Tasks;

namespace MeteorDetect.App;

public sealed class ProcessingHistoryDocument
{
    public int FormatVersion { get; set; } = 1;

    public List<ProcessingHistoryEntry> Entries { get; set; } = [];
}

public sealed class ProcessingHistoryEntry
{
    public string Id { get; set; } = Guid.NewGuid().ToString("N");

    public string ClipPath { get; set; } = "";

    public string FileName { get; set; } = "";

    public double? DurationSeconds { get; set; }

    public int MeteorCount { get; set; }

    public DateTimeOffset DetectedAtUtc { get; set; }

    public string OutputJsonPath { get; set; } = "";

    public string? AppVersion { get; set; }

    public string? DetectorVersion { get; set; }

    public string DetectorAlgorithm { get; set; } = DetectorAlgorithms.OptimizedTemporalMedian;

    public string Decoder { get; set; } = DetectorDecoders.Ffmpeg;

    public bool FastPrefilter { get; set; }

    public long? FileSizeBytes { get; set; }

    public DateTimeOffset? LastWriteTimeUtc { get; set; }
}

public static class ProcessingHistoryStore
{
    public static string HistoryPath => Path.Combine(SettingsStore.SettingsDirectory, "history.json");

    public static async Task<ProcessingHistoryDocument> LoadAsync()
    {
        if (!File.Exists(HistoryPath))
        {
            return new ProcessingHistoryDocument();
        }

        await using var stream = File.OpenRead(HistoryPath);
        return await JsonSerializer.DeserializeAsync(stream, AppJsonContext.Default.ProcessingHistoryDocument)
            ?? new ProcessingHistoryDocument();
    }

    public static async Task SaveAsync(ProcessingHistoryDocument history)
    {
        Directory.CreateDirectory(SettingsStore.SettingsDirectory);
        history.FormatVersion = 1;
        history.Entries = history.Entries
            .OrderByDescending(entry => entry.DetectedAtUtc)
            .ToList();

        await using var stream = File.Create(HistoryPath);
        await JsonSerializer.SerializeAsync(stream, history, AppJsonContext.Default.ProcessingHistoryDocument);
    }

    public static async Task AddEntriesAsync(IEnumerable<ProcessingHistoryEntry> entries)
    {
        var history = await LoadAsync();
        history.Entries.AddRange(entries);
        await SaveAsync(history);
    }

    public static async Task RemoveEntryAsync(string id)
    {
        var history = await LoadAsync();
        history.Entries.RemoveAll(entry => string.Equals(entry.Id, id, StringComparison.Ordinal));
        await SaveAsync(history);
    }

    public static async Task ClearAsync()
    {
        await SaveAsync(new ProcessingHistoryDocument());
    }
}
