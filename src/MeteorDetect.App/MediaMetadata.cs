using System;
using System.Globalization;
using System.Threading.Tasks;

namespace MeteorDetect.App;

public static class MediaMetadata
{
    public static async Task<string> ReadDurationAsync(string clipPath)
    {
        try
        {
            var result = await ProcessRunner.RunAsync(
                "ffprobe",
                new[]
                {
                    "-v", "error",
                    "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    clipPath
                });

            if (result.ExitCode != 0)
            {
                return "Unknown length";
            }

            var text = result.StandardOutput.Trim();
            if (!double.TryParse(text, NumberStyles.Float, CultureInfo.InvariantCulture, out var seconds))
            {
                return "Unknown length";
            }

            return FormatDuration(TimeSpan.FromSeconds(seconds));
        }
        catch
        {
            return "Unknown length";
        }
    }

    private static string FormatDuration(TimeSpan duration)
    {
        return duration.TotalHours >= 1
            ? duration.ToString(@"h\:mm\:ss", CultureInfo.InvariantCulture)
            : duration.ToString(@"m\:ss", CultureInfo.InvariantCulture);
    }
}
