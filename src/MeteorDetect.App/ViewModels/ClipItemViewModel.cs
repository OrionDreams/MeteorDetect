using CommunityToolkit.Mvvm.ComponentModel;

namespace MeteorDetect.App.ViewModels;

public partial class ClipItemViewModel : ObservableObject
{
    [ObservableProperty]
    private string _duration = "Reading metadata...";

    [ObservableProperty]
    private string _status = "Ready";

    [ObservableProperty]
    private string _eventSummary = "";

    public ClipItemViewModel(string path)
    {
        Path = path;
        Name = System.IO.Path.GetFileName(path);
    }

    public string Name { get; }

    public string Path { get; }
}
