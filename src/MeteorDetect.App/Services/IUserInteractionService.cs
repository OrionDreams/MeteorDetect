namespace MeteorDetect.App.Services;

public interface IUserInteractionService
{
    Task<IReadOnlyList<string>> OpenVideoFilesAsync();

    Task<string?> ChooseFolderAsync(string title);

    Task ShowNoticeAsync(string title, string message);
}
