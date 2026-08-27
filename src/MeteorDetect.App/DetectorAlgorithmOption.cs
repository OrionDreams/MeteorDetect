namespace MeteorDetect.App;

public sealed record DetectorAlgorithmOption(string Id, string Name, string Description)
{
    public override string ToString() => Name;
}

public static class DetectorAlgorithms
{
    public const string OptimizedTemporalMedian = "optimized_temporal_median";
    public const string Accurate = "temporal_median_mad";
    public const string AccurateWithPrefilter = "temporal_median_mad_prefilter";
    public const string FastDetectExperimental = "fastdetect_experimental";

    public static IReadOnlyList<DetectorAlgorithmOption> All { get; } =
    [
        new(
            OptimizedTemporalMedian,
            "Optimized Temporal Median",
            "Current default. Same recall-focused detector with faster exact temporal modeling."),
        new(
            Accurate,
            "Temporal Median / MAD",
            "Accurate baseline. Slowest, but currently the recall reference."),
        new(
            AccurateWithPrefilter,
            "Temporal Median / MAD with Fast Prefilter",
            "Experimental skip pass. Faster, but can miss faint meteors."),
    ];

    public static DetectorAlgorithmOption Resolve(string? id)
    {
        if (string.Equals(id, FastDetectExperimental, StringComparison.Ordinal))
        {
            return All[0];
        }

        return All.FirstOrDefault(option => string.Equals(option.Id, id, StringComparison.Ordinal))
            ?? All[0];
    }
}

public sealed record DetectorDecoderOption(string Id, string Name, string Description)
{
    public override string ToString() => Name;
}

public static class DetectorDecoders
{
    public const string Ffmpeg = "ffmpeg";
    public const string OpenCv = "opencv";

    public static IReadOnlyList<DetectorDecoderOption> All { get; } =
    [
        new(
            Ffmpeg,
            "FFmpeg",
            "Default. Decodes and scales directly to 16-bit grayscale; best-tested for faint 10-bit footage."),
        new(
            OpenCv,
            "OpenCV",
            "Experimental. May decode faster, but commonly reads 8-bit frames before converting them to the detector's 16-bit grayscale format."),
    ];

    public static DetectorDecoderOption Resolve(string? id)
    {
        return All.FirstOrDefault(option => string.Equals(option.Id, id, StringComparison.Ordinal))
            ?? All[0];
    }
}

public sealed record HardwareDecoderOption(string Id, string Name, string Description)
{
    public override string ToString() => Name;
}

public static class HardwareDecoders
{
    public const string None = "none";
    public const string Auto = "auto";

    private static readonly IReadOnlyDictionary<string, HardwareDecoderOption> OptionsById =
        new Dictionary<string, HardwareDecoderOption>(StringComparer.Ordinal)
        {
            [None] = new(None, "None", "Default. Use FFmpeg software decoding."),
            [Auto] = new(Auto, "Auto", "Try available hardware decoders in detector order and use the first one that works for the file."),
            ["vaapi"] = new("vaapi", "VAAPI", "Linux hardware decoding through VAAPI."),
            ["cuda"] = new("cuda", "CUDA / NVDEC", "NVIDIA hardware decoding through FFmpeg's CUDA hwaccel path."),
            ["qsv"] = new("qsv", "Intel Quick Sync", "Intel hardware decoding through Quick Sync Video."),
            ["videotoolbox"] = new("videotoolbox", "VideoToolbox", "macOS hardware decoding through VideoToolbox."),
            ["d3d11va"] = new("d3d11va", "D3D11VA", "Windows hardware decoding through Direct3D 11 Video Acceleration."),
            ["dxva2"] = new("dxva2", "DXVA2", "Windows hardware decoding through DirectX Video Acceleration 2."),
        };

    public static IReadOnlyList<string> DetectorOrder { get; } =
    [
        None,
        Auto,
        "vaapi",
        "cuda",
        "qsv",
        "videotoolbox",
        "d3d11va",
        "dxva2",
    ];

    public static IReadOnlyList<HardwareDecoderOption> DefaultOptions { get; } =
    [
        OptionsById[None],
        OptionsById[Auto],
    ];

    public static IReadOnlyList<HardwareDecoderOption> FromAvailableMethods(IReadOnlySet<string> availableMethods)
    {
        var options = new List<HardwareDecoderOption>
        {
            OptionsById[None],
            OptionsById[Auto],
        };

        foreach (var id in DetectorOrder.Skip(2))
        {
            if (availableMethods.Contains(id) && OptionsById.TryGetValue(id, out var option))
            {
                options.Add(option);
            }
        }

        return options;
    }

    public static HardwareDecoderOption Resolve(
        string? id,
        IEnumerable<HardwareDecoderOption>? options = null)
    {
        var candidates = options ?? DefaultOptions;
        return candidates.FirstOrDefault(option => string.Equals(option.Id, id, StringComparison.Ordinal))
            ?? candidates.FirstOrDefault(option => string.Equals(option.Id, Auto, StringComparison.Ordinal))
            ?? OptionsById[Auto];
    }
}

public sealed record CameraClassOption(string Id, string Name, string Description)
{
    public override string ToString() => Name;
}

public static class CameraClasses
{
    public const string SonyMirrorless = "sony_mirrorless";
    public const string NoisyCamera = "noisy_camera";

    public static IReadOnlyList<CameraClassOption> All { get; } =
    [
        new(
            SonyMirrorless,
            "Mirrorless (Sony, Canon, etc)",
            "Default. Current tuning for mirrorless night-sky footage."),
        new(
            NoisyCamera,
            "Noisy Camera",
            "Stricter tuning for noisy, compressed, or heavily processed night video."),
    ];

    public static CameraClassOption Resolve(string? id)
    {
        return All.FirstOrDefault(option => string.Equals(option.Id, id, StringComparison.Ordinal))
            ?? All[0];
    }
}

public sealed record DiagnosticLevelOption(int Id, string Name, string Description)
{
    public override string ToString() => Name;
}

public static class DiagnosticLevels
{
    public const int Standard = 1;
    public const int Deep = 2;

    public static IReadOnlyList<DiagnosticLevelOption> All { get; } =
    [
        new(
            Standard,
            "Level 1",
            "Default. Writes the current annotated candidate JPEGs."),
        new(
            Deep,
            "Level 2",
            "Adds residual, threshold mask, sigma map, threshold map, and candidate stats sidecars."),
    ];

    public static DiagnosticLevelOption Resolve(int id)
    {
        return All.FirstOrDefault(option => option.Id == id) ?? All[0];
    }
}
