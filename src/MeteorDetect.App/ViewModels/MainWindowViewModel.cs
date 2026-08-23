using System.Collections.ObjectModel;
using Avalonia.Threading;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using MeteorDetect.App.Services;

namespace MeteorDetect.App.ViewModels;

public partial class MainWindowViewModel : ObservableObject
{
    private readonly DetectorRuntime _runtime;
    private readonly DetectionService _detectionService;
    private readonly IUserInteractionService _userInteraction;
    private AppSettings _settings = new();

    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(RemoveSelectedCommand))]
    private ClipItemViewModel? _selectedClip;

    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(DetectCommand))]
    [NotifyCanExecuteChangedFor(nameof(AddFilesCommand))]
    private bool _isDetecting;

    [ObservableProperty]
    private bool _fastPrefilter;

    [ObservableProperty]
    private string _outputPath = "";

    [ObservableProperty]
    private string _logText = "";

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

        _ = InitializeAsync();
    }

    public ObservableCollection<ClipItemViewModel> Clips { get; } = [];

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
        DetectCommand.NotifyCanExecuteChanged();
    }

    [RelayCommand(CanExecute = nameof(CanDetect))]
    private async Task DetectAsync()
    {
        IsDetecting = true;
        OutputPath = "";

        try
        {
            foreach (var clip in Clips)
            {
                clip.Status = "Queued";
                clip.EventSummary = "";
            }

            var result = await _detectionService.DetectAsync(
                Clips.Select(clip => clip.Path).ToList(),
                FastPrefilter,
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
                    clip.Status = "Failed";
                    clip.EventSummary = "Failed";
                }
                else
                {
                    clip.Status = "Done";
                    clip.EventSummary = $"{group.Sum(item => item.EventCount)} event(s)";
                }
            }

            OutputPath = $"Output: {result.CombinedJsonPath}";
            AppendLog($"Finished. Detected {result.EventCount} event(s); failures={result.FailureCount}.");

            if (result.FailureCount > 0)
            {
                var failedClips = result.Clips.Where(clip => !clip.Succeeded).ToList();
                var message = result.EventCount > 0
                    ? $"Wrote partial results:\n{result.CombinedJsonPath}\n\nDetected {result.EventCount} event(s), but {result.FailureCount} clip(s) failed. Check the output log before importing this JSON into Resolve."
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
                    $"Wrote:\n{result.CombinedJsonPath}\n\nIn DaVinci Resolve, choose Workspace > Scripts > Import Meteors, then select this JSON file to add Pink clip markers.");
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
        }
    }

    [RelayCommand(CanExecute = nameof(CanRemoveSelected))]
    private void RemoveSelected()
    {
        if (SelectedClip is not null)
        {
            Clips.Remove(SelectedClip);
            SelectedClip = null;
            DetectCommand.NotifyCanExecuteChanged();
        }
    }

    [RelayCommand]
    private void Clear()
    {
        Clips.Clear();
        OutputPath = "";
        SelectedClip = null;
        AppendLog("Cleared clips.");
        DetectCommand.NotifyCanExecuteChanged();
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
        await SettingsStore.SaveAsync(_settings);
        RefreshResolvePluginStatus();
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
        LogText += $"[{DateTime.Now:HH:mm:ss}] {message}{Environment.NewLine}";
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

    private bool CanAddFiles() => !IsDetecting;

    private bool CanDetect() => !IsDetecting && Clips.Count > 0;

    private bool CanRemoveSelected() => SelectedClip is not null;
}
