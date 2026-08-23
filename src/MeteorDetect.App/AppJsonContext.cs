using System.Text.Json.Serialization;

namespace MeteorDetect.App;

[JsonSourceGenerationOptions(PropertyNamingPolicy = JsonKnownNamingPolicy.CamelCase, WriteIndented = true)]
[JsonSerializable(typeof(AppSettings))]
[JsonSerializable(typeof(DetectionFailureInfo))]
[JsonSerializable(typeof(ProcessingHistoryDocument))]
public partial class AppJsonContext : JsonSerializerContext;

public sealed record DetectionFailureInfo(string Path, string Error);
