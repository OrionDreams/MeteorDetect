using System;
using System.Globalization;
using CommunityToolkit.Mvvm.ComponentModel;

namespace MeteorDetect.App.ViewModels;

public sealed partial class ProcessingHistoryEntryViewModel : ObservableObject
{
    public ProcessingHistoryEntryViewModel(ProcessingHistoryEntry entry)
    {
        Entry = entry;
    }

    public ProcessingHistoryEntry Entry { get; }

    public string Id => Entry.Id;

    public string FileName => string.IsNullOrWhiteSpace(Entry.FileName)
        ? System.IO.Path.GetFileName(Entry.ClipPath)
        : Entry.FileName;

    public string ClipPath => Entry.ClipPath;

    public string Duration => Entry.DurationSeconds is { } seconds
        ? FormatDuration(TimeSpan.FromSeconds(seconds))
        : "Unknown length";

    public string MeteorCount => $"{Entry.MeteorCount:N0} meteor(s)";

    public string DetectedAt => Entry.DetectedAtUtc
        .ToLocalTime()
        .ToString("yyyy-MM-dd HH:mm", CultureInfo.CurrentCulture);

    public string OutputJsonPath => Entry.OutputJsonPath;

    private static string FormatDuration(TimeSpan duration)
    {
        return duration.TotalHours >= 1
            ? duration.ToString(@"h\:mm\:ss", CultureInfo.InvariantCulture)
            : duration.ToString(@"m\:ss", CultureInfo.InvariantCulture);
    }
}
