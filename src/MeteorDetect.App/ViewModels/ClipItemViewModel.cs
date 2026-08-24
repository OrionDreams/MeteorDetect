using CommunityToolkit.Mvvm.ComponentModel;
using System.Text.Json;

namespace MeteorDetect.App.ViewModels;

public partial class ClipItemViewModel : ObservableObject
{
    [ObservableProperty]
    private string _duration = "--";

    [ObservableProperty]
    private string _status = "Ready";

    [ObservableProperty]
    private bool _isDetectingStatus;

    [ObservableProperty]
    private string _eventSummary = "";

    [ObservableProperty]
    private bool _isSelected;

    [ObservableProperty]
    private bool _isEventBadgeVisible;

    [ObservableProperty]
    private bool _hasProcessedDetection;

    [ObservableProperty]
    private string _processedDetectionPath = "";

    [ObservableProperty]
    private bool _hasPartialDetection;

    [ObservableProperty]
    private string _partialDetectionText = "";

    public ClipItemViewModel(string path)
    {
        Path = path;
        Name = System.IO.Path.GetFileName(path);
        RefreshPartialDetection();
    }

    public string Name { get; }

    public string Path { get; }

    public string PartialDetectionPath => DetectionService.GetPartialOutputPath(Path);

    partial void OnStatusChanged(string value)
    {
        IsDetectingStatus = string.Equals(value, "Detecting...", StringComparison.Ordinal)
            || string.Equals(value, "Resuming...", StringComparison.Ordinal);
    }

    public void SetProcessedDetection(string jsonPath, int eventCount)
    {
        HasProcessedDetection = true;
        ProcessedDetectionPath = jsonPath;
        EventSummary = $"{eventCount.ToString(System.Globalization.CultureInfo.InvariantCulture)} event(s)";
        IsEventBadgeVisible = true;
    }

    public void ClearProcessedDetection()
    {
        HasProcessedDetection = false;
        ProcessedDetectionPath = "";
        EventSummary = "";
        IsEventBadgeVisible = false;
    }

    public void RefreshPartialDetection()
    {
        HasPartialDetection = System.IO.File.Exists(PartialDetectionPath);
        PartialDetectionText = HasPartialDetection ? ReadPartialDetectionText() : "";
        if (HasPartialDetection && Status == "Ready")
        {
            Status = "Paused";
        }
    }

    private string ReadPartialDetectionText()
    {
        try
        {
            using var document = JsonDocument.Parse(System.IO.File.ReadAllText(PartialDetectionPath));
            if (document.RootElement.TryGetProperty("frame_progress", out var frameProgress)
                && frameProgress.TryGetInt64(out var frame))
            {
                return $"Paused detection available at frame {frame:N0}";
            }
        }
        catch (Exception)
        {
            return "Paused detection available";
        }

        return "Paused detection available";
    }
}
