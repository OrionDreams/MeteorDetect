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

    public string MeteorCount => $"{Entry.MeteorCount:N0} meteors";

    public string DetectorAlgorithm =>
        $"{MeteorDetect.App.DetectorAlgorithms.Resolve(Entry.DetectorAlgorithm).Name} / {MeteorDetect.App.DetectorDecoders.Resolve(Entry.Decoder).Name}";

    public string VersionSummary
    {
        get
        {
            var appVersion = string.IsNullOrWhiteSpace(Entry.AppVersion) ? "unknown app" : Entry.AppVersion;
            var detectorVersion = string.IsNullOrWhiteSpace(Entry.DetectorVersion) ? "unknown detector" : $"detector {Entry.DetectorVersion}";
            return $"{appVersion} / {detectorVersion}";
        }
    }

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
