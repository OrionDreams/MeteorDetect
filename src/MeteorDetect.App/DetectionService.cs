using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;

namespace MeteorDetect.App;

public sealed record ClipDetectionResult(string ClipPath, string JsonPath, int EventCount, bool Succeeded, string? Error);

public sealed record DetectionBatchResult(string CombinedJsonPath, int EventCount, int FailureCount, IReadOnlyList<ClipDetectionResult> Clips);

public sealed class DetectionService
{
    private static readonly JsonSerializerOptions JsonOptions = new() { WriteIndented = true };

    private readonly DetectorRuntime _runtime;

    public DetectionService(DetectorRuntime runtime)
    {
        _runtime = runtime;
    }

    public async Task<DetectionBatchResult> DetectAsync(
        IReadOnlyList<string> clipPaths,
        bool fastPrefilter,
        Action<string, string>? updateClipStatus,
        Action<string>? log,
        CancellationToken cancellationToken = default)
    {
        if (clipPaths.Count == 0)
        {
            throw new InvalidOperationException("No clips have been loaded.");
        }

        var batchDirectory = CreateBatchDirectory();
        var results = new List<ClipDetectionResult>();
        var fileElements = new List<JsonElement>();
        var failureElements = new List<JsonElement>();
        JsonElement? config = null;
        string? detectorVersion = null;

        foreach (var clipPath in clipPaths)
        {
            cancellationToken.ThrowIfCancellationRequested();
            updateClipStatus?.Invoke(clipPath, "Detecting...");

            var clipOutput = Path.Combine(batchDirectory, $"{SanitizeFileName(Path.GetFileNameWithoutExtension(clipPath))}_meteors.json");
            var args = new List<string>
            {
                "-m",
                _runtime.DetectScript,
                clipPath,
                "-o",
                clipOutput,
                "--no-diagnostics",
                "--profile"
            };

            if (fastPrefilter)
            {
                args.Add("--fast-prefilter");
            }

            log?.Invoke($"Scanning {clipPath}");
            var result = await ProcessRunner.RunAsync(
                _runtime.PythonExecutable,
                args,
                _runtime.RepositoryRoot,
                BuildProcessEnvironment(),
                line => log?.Invoke(line),
                cancellationToken);

            if (result.ExitCode != 0)
            {
                updateClipStatus?.Invoke(clipPath, "Failed");
                var error = result.StandardError.Trim();
                results.Add(new ClipDetectionResult(clipPath, clipOutput, 0, false, error));
                failureElements.Add(CreateFailureElement(clipPath, error));
                continue;
            }

            using var document = JsonDocument.Parse(await File.ReadAllTextAsync(clipOutput, cancellationToken));
            var root = document.RootElement;
            detectorVersion ??= root.GetProperty("detector_version").GetString();
            config ??= root.GetProperty("config").Clone();

            foreach (var file in root.GetProperty("files").EnumerateArray())
            {
                var clone = file.Clone();
                fileElements.Add(clone);
                var eventCount = clone.TryGetProperty("events", out var events) ? events.GetArrayLength() : 0;
                results.Add(new ClipDetectionResult(clipPath, clipOutput, eventCount, true, null));
            }

            foreach (var failure in root.GetProperty("failures").EnumerateArray())
            {
                failureElements.Add(failure.Clone());
            }

            updateClipStatus?.Invoke(clipPath, "Done");
        }

        var combinedPath = Path.Combine(GetDefaultOutputDirectory(clipPaths[0]), $"meteors_{DateTime.Now:yyyyMMdd_HHmmss}.json");
        await WriteCombinedJsonAsync(
            combinedPath,
            detectorVersion ?? "unknown",
            config,
            fileElements,
            failureElements,
            cancellationToken);

        var totalEvents = results.Where(r => r.Succeeded).Sum(r => r.EventCount);
        var failures = failureElements.Count;
        return new DetectionBatchResult(combinedPath, totalEvents, failures, results);
    }

    private IReadOnlyDictionary<string, string> BuildProcessEnvironment()
    {
        var env = new Dictionary<string, string>();
        var ffmpegDirectory = Path.Combine(_runtime.RepositoryRoot, "runtime", "ffmpeg");
        if (!Directory.Exists(ffmpegDirectory))
        {
            return env;
        }

        var currentPath = Environment.GetEnvironmentVariable("PATH") ?? "";
        env["PATH"] = ffmpegDirectory + Path.PathSeparator + currentPath;
        return env;
    }

    private static string CreateBatchDirectory()
    {
        var directory = Path.Combine(SettingsStore.SettingsDirectory, "runs", DateTime.Now.ToString("yyyyMMdd_HHmmss"));
        Directory.CreateDirectory(directory);
        return directory;
    }

    private static string GetDefaultOutputDirectory(string firstClipPath)
    {
        var clipDirectory = Path.GetDirectoryName(firstClipPath);
        if (!string.IsNullOrWhiteSpace(clipDirectory))
        {
            return clipDirectory;
        }

        Directory.CreateDirectory(SettingsStore.SettingsDirectory);
        return SettingsStore.SettingsDirectory;
    }

    private static string SanitizeFileName(string fileName)
    {
        var invalid = Path.GetInvalidFileNameChars();
        return new string(fileName.Select(ch => invalid.Contains(ch) ? '_' : ch).ToArray());
    }

    private static JsonElement CreateFailureElement(string clipPath, string error)
    {
        return JsonSerializer.SerializeToElement(
            new DetectionFailureInfo(clipPath, error),
            AppJsonContext.Default.DetectionFailureInfo);
    }

    private static async Task WriteCombinedJsonAsync(
        string outputPath,
        string detectorVersion,
        JsonElement? config,
        IReadOnlyList<JsonElement> files,
        IReadOnlyList<JsonElement> failures,
        CancellationToken cancellationToken)
    {
        await using var stream = File.Create(outputPath);
        await using var writer = new Utf8JsonWriter(stream, new JsonWriterOptions { Indented = true });

        writer.WriteStartObject();
        writer.WriteString("format", "resolve-meteor-detector");
        writer.WriteNumber("format_version", 1);
        writer.WriteString("detector_version", detectorVersion);
        writer.WriteString("created_utc", DateTimeOffset.UtcNow.ToString("O"));
        writer.WritePropertyName("config");
        if (config is { } configElement)
        {
            configElement.WriteTo(writer);
        }
        else
        {
            writer.WriteStartObject();
            writer.WriteEndObject();
        }

        writer.WritePropertyName("files");
        writer.WriteStartArray();
        foreach (var file in files)
        {
            file.WriteTo(writer);
        }

        writer.WriteEndArray();
        writer.WritePropertyName("failures");
        writer.WriteStartArray();
        foreach (var failure in failures)
        {
            failure.WriteTo(writer);
        }

        writer.WriteEndArray();
        writer.WriteEndObject();
        await writer.FlushAsync(cancellationToken);
    }
}
