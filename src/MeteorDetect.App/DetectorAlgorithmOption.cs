namespace MeteorDetect.App;

public sealed record DetectorAlgorithmOption(string Id, string Name, string Description)
{
    public override string ToString() => Name;
}

public static class DetectorAlgorithms
{
    public const string Accurate = "temporal_median_mad";
    public const string AccurateWithPrefilter = "temporal_median_mad_prefilter";
    public const string FastDetectExperimental = "fastdetect_experimental";

    public static IReadOnlyList<DetectorAlgorithmOption> All { get; } =
    [
        new(
            Accurate,
            "Temporal Median / MAD",
            "Accurate baseline. Slowest, but currently the recall reference."),
        new(
            AccurateWithPrefilter,
            "Temporal Median / MAD with Fast Prefilter",
            "Experimental skip pass. Faster, but can miss faint meteors."),
        new(
            FastDetectExperimental,
            "FastDetect (Experimental)",
            "Exact small-sample median/MAD experiment with moderately fewer temporal models.")
    ];

    public static DetectorAlgorithmOption Resolve(string? id)
    {
        return All.FirstOrDefault(option => string.Equals(option.Id, id, StringComparison.Ordinal))
            ?? All[0];
    }
}
