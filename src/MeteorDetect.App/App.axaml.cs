using Avalonia;
using Avalonia.Controls.ApplicationLifetimes;
using Avalonia.Markup.Xaml;
using MeteorDetect.App.Services;
using MeteorDetect.App.ViewModels;

namespace MeteorDetect.App;

public partial class App : Application
{
    public override void Initialize()
    {
        AvaloniaXamlLoader.Load(this);
    }

    public override void OnFrameworkInitializationCompleted()
    {
        if (ApplicationLifetime is IClassicDesktopStyleApplicationLifetime desktop)
        {
            var runtime = RuntimePaths.Discover();
            desktop.MainWindow = new MainWindow
            {
                DataContext = new MainWindowViewModel(
                    runtime,
                    new DetectionService(runtime),
                    new AvaloniaUserInteractionService())
            };
        }

        base.OnFrameworkInitializationCompleted();
    }
}
