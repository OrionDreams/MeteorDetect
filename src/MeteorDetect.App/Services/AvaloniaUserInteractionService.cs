using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.ApplicationLifetimes;
using Avalonia.Platform.Storage;

namespace MeteorDetect.App.Services;

public sealed class AvaloniaUserInteractionService : IUserInteractionService
{
    public async Task<IReadOnlyList<string>> OpenVideoFilesAsync()
    {
        var window = GetMainWindow();
        if (window is null)
        {
            return [];
        }

        var files = await window.StorageProvider.OpenFilePickerAsync(new FilePickerOpenOptions
        {
            Title = "Open video clips",
            AllowMultiple = true,
            FileTypeFilter =
            [
                new FilePickerFileType("Video files")
                {
                    Patterns = ["*.mp4", "*.mov", "*.m4v"]
                },
                FilePickerFileTypes.All
            ]
        });

        return files
            .Select(file => file.TryGetLocalPath())
            .Where(path => !string.IsNullOrWhiteSpace(path))
            .Select(path => path!)
            .ToList();
    }

    public async Task<string?> ChooseFolderAsync(string title)
    {
        var window = GetMainWindow();
        if (window is null)
        {
            return null;
        }

        var folders = await window.StorageProvider.OpenFolderPickerAsync(new FolderPickerOpenOptions
        {
            Title = title,
            AllowMultiple = false
        });

        return folders.FirstOrDefault()?.TryGetLocalPath();
    }

    public async Task ShowNoticeAsync(string title, string message)
    {
        var owner = GetMainWindow();
        if (owner is null)
        {
            return;
        }

        var okButton = new Button
        {
            Content = "OK",
            MinWidth = 90,
            HorizontalAlignment = Avalonia.Layout.HorizontalAlignment.Right
        };

        var dialog = new Window
        {
            Title = title,
            Width = 520,
            Height = 260,
            WindowStartupLocation = WindowStartupLocation.CenterOwner,
            Content = new Grid
            {
                Margin = new Thickness(18),
                RowDefinitions = new RowDefinitions("*,Auto"),
                RowSpacing = 14,
                Children =
                {
                    new ScrollViewer
                    {
                        VerticalScrollBarVisibility = Avalonia.Controls.Primitives.ScrollBarVisibility.Auto,
                        Content = new TextBlock
                        {
                            Text = message,
                            TextWrapping = Avalonia.Media.TextWrapping.Wrap
                        }
                    },
                    okButton
                }
            }
        };

        Grid.SetRow(okButton, 1);
        okButton.Click += (_, _) => dialog.Close();
        await dialog.ShowDialog(owner);
    }

    private static Window? GetMainWindow()
    {
        return Application.Current?.ApplicationLifetime is IClassicDesktopStyleApplicationLifetime desktop
            ? desktop.MainWindow
            : null;
    }
}
