using System;
using System.Reflection;

namespace MeteorDetect.App;

public static class AppVersionInfo
{
    public static string Version { get; } = ResolveVersion();

    public static string ReleaseTag { get; } = Version.StartsWith("v", StringComparison.Ordinal)
        ? Version
        : $"v{Version}";

    private static string ResolveVersion()
    {
        var assembly = typeof(AppVersionInfo).Assembly;
        var informationalVersion = assembly
            .GetCustomAttribute<AssemblyInformationalVersionAttribute>()?
            .InformationalVersion;

        if (!string.IsNullOrWhiteSpace(informationalVersion))
        {
            return informationalVersion;
        }

        return assembly.GetName().Version?.ToString(3) ?? "0.0.0";
    }
}
