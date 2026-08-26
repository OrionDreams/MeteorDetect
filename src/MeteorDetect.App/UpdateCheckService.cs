using System;
using System.Globalization;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;

namespace MeteorDetect.App;

public sealed record UpdateCheckResult(
    bool IsUpdateAvailable,
    string? LatestVersion,
    string? ReleaseUrl);

public sealed class UpdateCheckService
{
    private static readonly Uri LatestReleaseApiUri = new("https://api.github.com/repos/OrionDreams/MeteorDetect/releases/latest");
    private static readonly TimeSpan StartupTimeout = TimeSpan.FromSeconds(5);

    private readonly HttpClient _httpClient;

    public UpdateCheckService()
        : this(CreateHttpClient())
    {
    }

    public UpdateCheckService(HttpClient httpClient)
    {
        _httpClient = httpClient;
    }

    public async Task<UpdateCheckResult> CheckForUpdatesAsync(
        string currentVersion,
        CancellationToken cancellationToken = default)
    {
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        timeout.CancelAfter(StartupTimeout);

        using var response = await _httpClient.GetAsync(LatestReleaseApiUri, timeout.Token);
        response.EnsureSuccessStatusCode();

        await using var stream = await response.Content.ReadAsStreamAsync(timeout.Token);
        using var document = await JsonDocument.ParseAsync(stream, cancellationToken: timeout.Token);
        var root = document.RootElement;

        var latestTag = root.TryGetProperty("tag_name", out var tagProperty)
            ? tagProperty.GetString()
            : null;
        var releaseUrl = root.TryGetProperty("html_url", out var urlProperty)
            ? urlProperty.GetString()
            : null;

        if (string.IsNullOrWhiteSpace(latestTag)
            || !TryParseVersion(currentVersion, out var current)
            || !TryParseVersion(latestTag, out var latest))
        {
            return new UpdateCheckResult(false, latestTag, releaseUrl);
        }

        return new UpdateCheckResult(latest > current, NormalizeTag(latestTag), releaseUrl);
    }

    private static HttpClient CreateHttpClient()
    {
        var httpClient = new HttpClient();
        httpClient.DefaultRequestHeaders.UserAgent.Add(new ProductInfoHeaderValue("MeteorDetect", AppVersionInfo.Version.TrimStart('v', 'V')));
        httpClient.DefaultRequestHeaders.Accept.Add(new MediaTypeWithQualityHeaderValue("application/vnd.github+json"));
        return httpClient;
    }

    private static bool TryParseVersion(string value, out Version version)
    {
        var normalized = NormalizeTag(value).TrimStart('v', 'V');
        var metadataIndex = normalized.IndexOfAny(['-', '+']);
        if (metadataIndex >= 0)
        {
            normalized = normalized[..metadataIndex];
        }

        var parts = normalized.Split('.', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
        if (parts.Length is < 2 or > 4)
        {
            version = new Version();
            return false;
        }

        var versionParts = new int[Math.Max(3, parts.Length)];
        for (var index = 0; index < parts.Length; index++)
        {
            if (!int.TryParse(parts[index], NumberStyles.None, CultureInfo.InvariantCulture, out versionParts[index]))
            {
                version = new Version();
                return false;
            }
        }

        version = versionParts.Length == 3
            ? new Version(versionParts[0], versionParts[1], versionParts[2])
            : new Version(versionParts[0], versionParts[1], versionParts[2], versionParts[3]);
        return true;
    }

    private static string NormalizeTag(string value)
    {
        var trimmed = value.Trim();
        return trimmed.StartsWith("v", StringComparison.OrdinalIgnoreCase)
            ? $"v{trimmed[1..]}"
            : $"v{trimmed}";
    }
}
