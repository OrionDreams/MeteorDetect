using System.Collections.ObjectModel;
using System.Globalization;
using System.Text.RegularExpressions;
using Avalonia.Threading;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using MeteorDetect.App.Services;

namespace MeteorDetect.App.ViewModels;

public partial class MainWindowViewModel : ObservableObject
{
    private static readonly Regex DetectorProgressPattern = new(
        @"^(?:\[(?<time>\d{2}:\d{2}:\d{2})\])?\[(?<file>[^\]]+)\]\s+frame\s+(?<processed>\d+)\/(?<total>\d+),\s+candidates=(?<candidates>\d+)",
        RegexOptions.Compiled | RegexOptions.CultureInvariant);

    private readonly DetectorRuntime _runtime;
    private readonly DetectionService _detectionService;
    private readonly IUserInteractionService _userInteraction;
    private readonly DispatcherTimer _remainingTimeTimer;
    private readonly Queue<double> _recentFrameRates = new();
    private AppSettings _settings = new();
    private DateTimeOffset? _previousProgressObservedAt;
    private long? _previousProgressFrames;
    private long? _previousProgressTotalFrames;
    private DateTimeOffset? _remainingTimeEstimatedAt;
    private double? _remainingSecondsAtEstimate;

    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(RemoveSelectedCommand))]
    private ClipItemViewModel? _selectedClip;

    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(RemoveSelectedHistoryEntryCommand))]
    private ProcessingHistoryEntryViewModel? _selectedHistoryEntry;

    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(DetectCommand))]
    [NotifyCanExecuteChangedFor(nameof(AddFilesCommand))]
    [NotifyCanExecuteChangedFor(nameof(PauseDetectionCommand))]
    private bool _isDetecting;

    [ObservableProperty]
    private bool _isPauseRequested;

    [ObservableProperty]
    private string _detectButtonText = "Detect";

    [ObservableProperty]
    private string _pauseButtonText = "Pause";

    [ObservableProperty]
    private bool _ignoreCameraBumps;

    [ObservableProperty]
    private DetectorAlgorithmOption _selectedDetectorAlgorithm = DetectorAlgorithms.All[0];

    [ObservableProperty]
    private bool _writeCombinedJson;

    [ObservableProperty]
    private string _outputPath = "";

    [ObservableProperty]
    private string _logText = "";

    [ObservableProperty]
    private double _progressPercentage;

    [ObservableProperty]
    private string _progressPercentText = "0%";

    [ObservableProperty]
    private string _processedFramesText = "Processed frames: 0 / 0";

    [ObservableProperty]
    private string _candidateFramesText = "Candidate frames: 0";

    [ObservableProperty]
    private string _framesPerSecondText = "Speed: -- fps";

    [ObservableProperty]
    private string _remainingTimeText = "Remaining: --";

    [ObservableProperty]
    private string _resolveScriptDirectory = "";

    [ObservableProperty]
    private string _resolvePluginStatus = "";

    [ObservableProperty]
    private string _runtimeStatus;

    public MainWindowViewModel(
        DetectorRuntime runtime,
        DetectionService detectionService,
        IUserInteractionService userInteraction)
    {
        _runtime = runtime;
        _detectionService = detectionService;
        _userInteraction = userInteraction;
        _runtimeStatus = $"Detector: {_runtime.DetectScript}\nPython: {_runtime.PythonExecutable}";
        _remainingTimeTimer = new DispatcherTimer
        {
            Interval = TimeSpan.FromSeconds(1)
        };
        _remainingTimeTimer.Tick += (_, _) => RefreshRemainingTimeCountdown(DateTimeOffset.Now);

        _ = InitializeAsync();
    }

    public ObservableCollection<ClipItemViewModel> Clips { get; } = [];

    public ObservableCollection<ProcessingHistoryEntryViewModel> HistoryEntries { get; } = [];

    public IReadOnlyList<DetectorAlgorithmOption> DetectorAlgorithmOptions => DetectorAlgorithms.All;

    [RelayCommand(CanExecute = nameof(CanAddFiles))]
    private async Task AddFilesAsync()
    {
        var paths = await _userInteraction.OpenVideoFilesAsync();
        foreach (var path in paths)
        {
            if (Clips.Any(clip => string.Equals(clip.Path, path, StringComparison.OrdinalIgnoreCase)))
            {
                continue;
            }

            var clip = new ClipItemViewModel(path);
            Clips.Add(clip);
            _ = LoadDurationAsync(clip);
        }

        AppendLog($"Loaded {Clips.Count} clip(s).");
        RefreshDetectButtonText();
        DetectCommand.NotifyCanExecuteChanged();
    }

    [RelayCommand(CanExecute = nameof(CanDetect))]
    private async Task DetectAsync()
    {
        IsDetecting = true;
        IsPauseRequested = false;
        OutputPath = "";
        ResetProgress();

        try
        {
            foreach (var clip in Clips)
            {
                clip.Status = "Queued";
                clip.EventSummary = "";
            }

            var result = await _detectionService.DetectAsync(
                Clips.Select(clip => clip.Path).ToList(),
                SelectedDetectorAlgorithm.Id,
                IgnoreCameraBumps,
                WriteCombinedJson,
                UpdateClipStatus,
                AppendLogThreadSafe);

            foreach (var group in result.Clips.GroupBy(clip => clip.ClipPath))
            {
                var clip = Clips.FirstOrDefault(item => string.Equals(item.Path, group.Key, StringComparison.OrdinalIgnoreCase));
                if (clip is null)
                {
                    continue;
                }

                if (group.Any(item => !item.Succeeded))
                {
                    if (group.Any(item => item.Paused))
                    {
                        clip.Status = "Paused";
                        clip.EventSummary = "Resume available";
                        clip.RefreshPartialDetection();
                    }
                    else
                    {
                        clip.Status = "Failed";
                        clip.EventSummary = "Failed";
                    }
                }
                else
                {
                    clip.Status = "Done";
                    clip.EventSummary = $"{group.Sum(item => item.EventCount)} event(s)";
                }
            }

            await AddSuccessfulClipsToHistoryAsync(result.Clips);
            OutputPath = result.IsPaused
                ? "Detection paused. Progress was saved to the partial JSON file."
                : result.IsCombinedOutput
                ? $"Output: {result.PrimaryOutputPath}"
                : $"Output: {result.OutputPaths.Count} JSON file(s)";
            AppendLog(result.IsPaused
                ? $"Paused. Completed outputs before pause: {result.OutputPaths.Count}; failures={result.FailureCount}."
                : $"Finished. Detected {result.EventCount} event(s); failures={result.FailureCount}.");
            foreach (var outputPath in result.OutputPaths)
            {
                AppendLog($"Wrote {outputPath}");
            }

            if (result.IsPaused)
            {
                await _userInteraction.ShowNoticeAsync(
                    "Detection paused",
                    "Progress was saved. Reloading this clip will offer Resume Detection.");
            }
            else if (result.FailureCount > 0)
            {
                var failedClips = result.Clips.Where(clip => !clip.Succeeded).ToList();
                var message = result.EventCount > 0
                    ? $"Wrote partial results:\n{FormatOutputPaths(result.OutputPaths)}\n\nDetected {result.EventCount} event(s), but {result.FailureCount} clip(s) failed. Check the output log before importing into Resolve."
                    : $"Detection failed for {result.FailureCount} clip(s). No meteor events were written.\n\nDetails are in the output log.";

                if (failedClips.Count > 0)
                {
                    message += $"\n\nFirst failure:\n{SummarizeFailure(failedClips[0].Error)}";
                }

                var title = result.EventCount > 0 ? "Detection incomplete" : "Detection failed";
                await _userInteraction.ShowNoticeAsync(title, message);
            }
            else
            {
                await _userInteraction.ShowNoticeAsync(
                    "Detection finished",
                    $"Meteor Events: {result.EventCount}\n\nWrote:\n{FormatOutputPaths(result.OutputPaths)}\n\nIn DaVinci Resolve, choose Workspace > Scripts > Import Meteors, then select the JSON file(s) to add Pink clip markers.");
            }
        }
        catch (Exception ex)
        {
            AppendLog($"ERROR: {ex.Message}");
            await _userInteraction.ShowNoticeAsync("Detection failed", ex.Message);
        }
        finally
        {
            IsDetecting = false;
            IsPauseRequested = false;
            foreach (var clip in Clips)
            {
                clip.RefreshPartialDetection();
            }
            RefreshDetectButtonText();
        }
    }

    [RelayCommand(CanExecute = nameof(CanPauseDetection))]
    private void PauseDetection()
    {
        IsPauseRequested = true;
        PauseButtonText = "Pausing...";
        _detectionService.RequestPause();
        AppendLog("Pause requested. Detection will stop after the next saved partial checkpoint.");
        PauseDetectionCommand.NotifyCanExecuteChanged();
    }

    [RelayCommand(CanExecute = nameof(CanRemoveSelectedHistoryEntry))]
    private async Task RemoveSelectedHistoryEntryAsync()
    {
        if (SelectedHistoryEntry is null)
        {
            return;
        }

        await ProcessingHistoryStore.RemoveEntryAsync(SelectedHistoryEntry.Id);
        HistoryEntries.Remove(SelectedHistoryEntry);
        SelectedHistoryEntry = null;
    }

    [RelayCommand]
    private async Task ClearHistoryAsync()
    {
        await ProcessingHistoryStore.ClearAsync();
        HistoryEntries.Clear();
        SelectedHistoryEntry = null;
    }

    [RelayCommand(CanExecute = nameof(CanRemoveSelected))]
    private void RemoveSelected()
    {
        if (SelectedClip is not null)
        {
            Clips.Remove(SelectedClip);
            SelectedClip = null;
            RefreshDetectButtonText();
            DetectCommand.NotifyCanExecuteChanged();
        }
    }

    [RelayCommand]
    private void Clear()
    {
        Clips.Clear();
        OutputPath = "";
        SelectedClip = null;
        ResetProgress();
        AppendLog("Cleared clips.");
        RefreshDetectButtonText();
        DetectCommand.NotifyCanExecuteChanged();
    }

    [RelayCommand]
    private void DiscardPartial(ClipItemViewModel? clip)
    {
        if (clip is null)
        {
            return;
        }

        var partialPath = clip.PartialDetectionPath;
        if (File.Exists(partialPath))
        {
            File.Delete(partialPath);
            AppendLog($"Discarded partial progress for {clip.Name}");
        }

        clip.Status = "Ready";
        clip.EventSummary = "";
        clip.RefreshPartialDetection();
        RefreshDetectButtonText();
    }

    [RelayCommand]
    private async Task BrowseResolveDirectoryAsync()
    {
        var path = await _userInteraction.ChooseFolderAsync("Choose Resolve Fusion/Scripts/Utility directory");
        if (string.IsNullOrWhiteSpace(path))
        {
            return;
        }

        ResolveScriptDirectory = path;
        _settings.ResolveScriptDirectory = path;
        await SettingsStore.SaveAsync(_settings);
        RefreshResolvePluginStatus();
    }

    [RelayCommand]
    private async Task InstallResolvePluginAsync()
    {
        var directory = ResolveScriptDirectory.Trim();
        if (string.IsNullOrWhiteSpace(directory))
        {
            await _userInteraction.ShowNoticeAsync("Resolve directory required", "Choose the Resolve Fusion/Scripts/Utility directory first.");
            return;
        }

        try
        {
            var destination = RuntimePaths.InstallResolveImporter(directory, _runtime.ResolveImporterScript);
            _settings.ResolveScriptDirectory = directory;
            await SettingsStore.SaveAsync(_settings);
            RefreshResolvePluginStatus();
            await _userInteraction.ShowNoticeAsync("Resolve importer installed", $"Installed:\n{destination}\n\nRestart Resolve if the script is not visible under Workspace > Scripts.");
        }
        catch (Exception ex)
        {
            await _userInteraction.ShowNoticeAsync("Install failed", ex.Message);
        }
    }

    private async Task InitializeAsync()
    {
        _settings = await SettingsStore.LoadAsync();
        _settings.ResolveScriptDirectory ??= RuntimePaths.FirstExistingResolveUtilityDirectory();
        ResolveScriptDirectory = _settings.ResolveScriptDirectory ?? "";
        if (_settings.FastPrefilter
            && !string.Equals(_settings.DetectorAlgorithm, DetectorAlgorithms.AccurateWithPrefilter, StringComparison.Ordinal))
        {
            _settings.DetectorAlgorithm = DetectorAlgorithms.AccurateWithPrefilter;
        }

        SelectedDetectorAlgorithm = DetectorAlgorithms.Resolve(_settings.DetectorAlgorithm);
        WriteCombinedJson = _settings.WriteCombinedJson;
        IgnoreCameraBumps = _settings.IgnoreCameraBumps;
        await LoadHistoryAsync();
        await SettingsStore.SaveAsync(_settings);
        RefreshResolvePluginStatus();
    }

    private async Task LoadHistoryAsync()
    {
        var history = await ProcessingHistoryStore.LoadAsync();
        HistoryEntries.Clear();
        foreach (var entry in history.Entries.OrderByDescending(entry => entry.DetectedAtUtc))
        {
            HistoryEntries.Add(new ProcessingHistoryEntryViewModel(entry));
        }
    }

    private async Task AddSuccessfulClipsToHistoryAsync(IReadOnlyList<ClipDetectionResult> results)
    {
        var entries = results
            .Where(result => result.Succeeded)
            .Select(CreateHistoryEntry)
            .ToList();

        if (entries.Count == 0)
        {
            return;
        }

        await ProcessingHistoryStore.AddEntriesAsync(entries);
        foreach (var entry in entries.OrderByDescending(entry => entry.DetectedAtUtc))
        {
            HistoryEntries.Insert(0, new ProcessingHistoryEntryViewModel(entry));
        }
    }

    private static ProcessingHistoryEntry CreateHistoryEntry(ClipDetectionResult result)
    {
        var fileInfo = new FileInfo(result.ClipPath);
        return new ProcessingHistoryEntry
        {
            Id = Guid.NewGuid().ToString("N"),
            ClipPath = result.ClipPath,
            FileName = Path.GetFileName(result.ClipPath),
            DurationSeconds = result.DurationSeconds,
            MeteorCount = result.EventCount,
            DetectedAtUtc = DateTimeOffset.UtcNow,
            OutputJsonPath = result.JsonPath,
            DetectorVersion = result.DetectorVersion,
            DetectorAlgorithm = result.DetectorAlgorithm,
            FastPrefilter = result.FastPrefilter,
            FileSizeBytes = fileInfo.Exists ? fileInfo.Length : null,
            LastWriteTimeUtc = fileInfo.Exists ? fileInfo.LastWriteTimeUtc : null
        };
    }

    private async Task LoadDurationAsync(ClipItemViewModel clip)
    {
        var duration = await MediaMetadata.ReadDurationAsync(clip.Path);
        Dispatcher.UIThread.Post(() => clip.Duration = duration);
    }

    private void UpdateClipStatus(string clipPath, string status)
    {
        Dispatcher.UIThread.Post(() =>
        {
            var clip = Clips.FirstOrDefault(item => string.Equals(item.Path, clipPath, StringComparison.OrdinalIgnoreCase));
            if (clip is not null)
            {
                clip.Status = status;
            }
        });
    }

    private void AppendLogThreadSafe(string message)
    {
        Dispatcher.UIThread.Post(() => AppendLog(message));
    }

    private void RefreshResolvePluginStatus()
    {
        if (string.IsNullOrWhiteSpace(ResolveScriptDirectory))
        {
            ResolvePluginStatus = "Resolve script directory was not detected. Choose it manually.";
            return;
        }

        var installed = RuntimePaths.IsResolveImporterInstalled(ResolveScriptDirectory);
        ResolvePluginStatus = installed
            ? $"Installed in: {ResolveScriptDirectory}"
            : $"Not installed in: {ResolveScriptDirectory}";
    }

    private void AppendLog(string message)
    {
        UpdateProgressFromLog(message, DateTimeOffset.Now);
        LogText += $"[{DateTime.Now:HH:mm:ss}] {message}{Environment.NewLine}";
    }

    partial void OnIsDetectingChanged(bool value)
    {
        if (value)
        {
            _remainingTimeTimer.Start();
            return;
        }

        _remainingTimeTimer.Stop();
        PauseButtonText = "Pause";
    }

    partial void OnIsPauseRequestedChanged(bool value)
    {
        PauseDetectionCommand.NotifyCanExecuteChanged();
    }

    partial void OnWriteCombinedJsonChanged(bool value)
    {
        _settings.WriteCombinedJson = value;
        _ = SettingsStore.SaveAsync(_settings);
    }

    partial void OnIgnoreCameraBumpsChanged(bool value)
    {
        _settings.IgnoreCameraBumps = value;
        _ = SettingsStore.SaveAsync(_settings);
    }

    partial void OnSelectedDetectorAlgorithmChanged(DetectorAlgorithmOption value)
    {
        _settings.DetectorAlgorithm = value.Id;
        _settings.FastPrefilter = value.Id == DetectorAlgorithms.AccurateWithPrefilter;
        _ = SettingsStore.SaveAsync(_settings);
    }

    private void UpdateProgressFromLog(string message, DateTimeOffset observedAt)
    {
        var match = DetectorProgressPattern.Match(message);
        if (!match.Success)
        {
            return;
        }

        if (!long.TryParse(match.Groups["processed"].Value, NumberStyles.None, CultureInfo.InvariantCulture, out var processedFrames)
            || !long.TryParse(match.Groups["total"].Value, NumberStyles.None, CultureInfo.InvariantCulture, out var totalFrames)
            || !long.TryParse(match.Groups["candidates"].Value, NumberStyles.None, CultureInfo.InvariantCulture, out var candidateFrames)
            || totalFrames <= 0)
        {
            return;
        }

        var isNewProgressStream = _previousProgressFrames > processedFrames
            || (_previousProgressTotalFrames is { } previousTotal && previousTotal != totalFrames);

        if (isNewProgressStream)
        {
            _previousProgressObservedAt = null;
            _previousProgressFrames = null;
            _recentFrameRates.Clear();
        }

        var averagedFramesPerSecond = CalculateAveragedFramesPerSecond(observedAt, processedFrames);
        var progress = Math.Clamp(processedFrames * 100.0 / totalFrames, 0, 100);

        ProgressPercentage = progress;
        ProgressPercentText = $"{Math.Round(progress)}%";
        ProcessedFramesText = $"Processed frames: {processedFrames:N0} / {totalFrames:N0}";
        CandidateFramesText = $"Candidate frames: {candidateFrames:N0}";
        FramesPerSecondText = averagedFramesPerSecond is null
            ? "Speed: -- fps"
            : $"Speed: {Math.Round(averagedFramesPerSecond.Value):N0} fps";
        if (averagedFramesPerSecond is null || averagedFramesPerSecond <= 0)
        {
            _remainingTimeEstimatedAt = null;
            _remainingSecondsAtEstimate = null;
            RemainingTimeText = "Remaining: --";
        }
        else
        {
            _remainingTimeEstimatedAt = observedAt;
            _remainingSecondsAtEstimate = Math.Max(0, (totalFrames - processedFrames) / averagedFramesPerSecond.Value);
            RefreshRemainingTimeCountdown(observedAt);
        }

        _previousProgressObservedAt = observedAt;
        _previousProgressFrames = processedFrames;
        _previousProgressTotalFrames = totalFrames;
    }

    private void RefreshRemainingTimeCountdown(DateTimeOffset now)
    {
        if (_remainingTimeEstimatedAt is not { } estimatedAt || _remainingSecondsAtEstimate is not { } estimatedSeconds)
        {
            return;
        }

        var elapsedSinceEstimate = Math.Max(0, (now - estimatedAt).TotalSeconds);
        var remainingSeconds = Math.Max(0, estimatedSeconds - elapsedSinceEstimate);
        RemainingTimeText = $"Remaining: {FormatDuration(remainingSeconds)}";
    }

    private double? CalculateAveragedFramesPerSecond(DateTimeOffset observedAt, long processedFrames)
    {
        if (_previousProgressObservedAt is not { } previousObservedAt || _previousProgressFrames is not { } previousFrames)
        {
            return null;
        }

        var elapsed = observedAt - previousObservedAt;
        var frameDelta = processedFrames - previousFrames;
        if (elapsed.TotalSeconds <= 0 || frameDelta <= 0)
        {
            return _recentFrameRates.Count > 0 ? _recentFrameRates.Average() : null;
        }

        _recentFrameRates.Enqueue(frameDelta / elapsed.TotalSeconds);
        while (_recentFrameRates.Count > 3)
        {
            _recentFrameRates.Dequeue();
        }

        return _recentFrameRates.Average();
    }

    private void ResetProgress()
    {
        _previousProgressObservedAt = null;
        _previousProgressFrames = null;
        _previousProgressTotalFrames = null;
        _remainingTimeEstimatedAt = null;
        _remainingSecondsAtEstimate = null;
        _recentFrameRates.Clear();
        if (!IsDetecting)
        {
            _remainingTimeTimer.Stop();
        }

        ProgressPercentage = 0;
        ProgressPercentText = "0%";
        ProcessedFramesText = "Processed frames: 0 / 0";
        CandidateFramesText = "Candidate frames: 0";
        FramesPerSecondText = "Speed: -- fps";
        RemainingTimeText = "Remaining: --";
    }

    private void RefreshDetectButtonText()
    {
        DetectButtonText = Clips.Any(clip => clip.HasPartialDetection)
            ? "Resume Detection"
            : "Detect";
    }

    private static string FormatDuration(double seconds)
    {
        if (double.IsNaN(seconds) || double.IsInfinity(seconds) || seconds < 0)
        {
            return "--";
        }

        var duration = TimeSpan.FromSeconds(seconds);
        return duration.TotalHours >= 1
            ? $"{(int)duration.TotalHours}:{duration.Minutes:00}:{duration.Seconds:00}"
            : $"{duration.Minutes:00}:{duration.Seconds:00}";
    }

    private static string SummarizeFailure(string? error)
    {
        if (string.IsNullOrWhiteSpace(error))
        {
            return "Unknown detector error.";
        }

        var lines = error
            .Split(["\r\n", "\n", "\r"], StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)
            .TakeLast(3);

        return string.Join(Environment.NewLine, lines);
    }

    private static string FormatOutputPaths(IReadOnlyList<string> outputPaths)
    {
        if (outputPaths.Count == 0)
        {
            return "No JSON files were written.";
        }

        return string.Join(Environment.NewLine, outputPaths);
    }

    private bool CanAddFiles() => !IsDetecting;

    private bool CanDetect() => !IsDetecting && Clips.Count > 0;

    private bool CanPauseDetection() => IsDetecting && !IsPauseRequested;

    private bool CanRemoveSelected() => SelectedClip is not null;

    private bool CanRemoveSelectedHistoryEntry() => SelectedHistoryEntry is not null;
}
