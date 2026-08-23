using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;

namespace MeteorDetect.App;

public sealed record DetectorRuntime(string RepositoryRoot, string DetectScript, string ResolveImporterScript, string PythonExecutable);

public static class RuntimePaths
{
    private const string ImporterRelativePath = "resolve_importer/Import Meteors.lua";

    public static DetectorRuntime Discover()
    {
        var root = FindRepositoryRoot();
        var python = FindPythonExecutable(root);
        return new DetectorRuntime(
            root,
            "meteor_detector.cli",
            Path.Combine(root, "resolve_importer", "Import Meteors.lua"),
            python);
    }

    public static IEnumerable<string> ProbeResolveUtilityDirectories()
    {
        var home = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
        var appData = Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData);
        var commonAppData = Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData);

        if (RuntimeInformation.IsOSPlatform(OSPlatform.Windows))
        {
            yield return Path.Combine(appData, "Blackmagic Design", "DaVinci Resolve", "Support", "Fusion", "Scripts", "Utility");
            yield return Path.Combine(commonAppData, "Blackmagic Design", "DaVinci Resolve", "Fusion", "Scripts", "Utility");
        }
        else if (RuntimeInformation.IsOSPlatform(OSPlatform.OSX))
        {
            yield return Path.Combine(home, "Library", "Application Support", "Blackmagic Design", "DaVinci Resolve", "Fusion", "Scripts", "Utility");
            yield return Path.Combine("/Library", "Application Support", "Blackmagic Design", "DaVinci Resolve", "Fusion", "Scripts", "Utility");
        }
        else
        {
            yield return Path.Combine(home, ".local", "share", "DaVinciResolve", "Fusion", "Scripts", "Utility");
            yield return Path.Combine("/opt", "resolve", "Fusion", "Scripts", "Utility");
        }
    }

    public static string? FirstExistingResolveUtilityDirectory() =>
        ProbeResolveUtilityDirectories().FirstOrDefault(Directory.Exists);

    public static bool IsResolveImporterInstalled(string? utilityDirectory)
    {
        if (string.IsNullOrWhiteSpace(utilityDirectory))
        {
            return false;
        }

        return File.Exists(Path.Combine(utilityDirectory, "Import Meteors.lua"));
    }

    public static string InstallResolveImporter(string utilityDirectory, string importerSource)
    {
        if (!File.Exists(importerSource))
        {
            throw new FileNotFoundException("Resolve importer script was not found.", importerSource);
        }

        Directory.CreateDirectory(utilityDirectory);
        var destination = Path.Combine(utilityDirectory, "Import Meteors.lua");
        File.Copy(importerSource, destination, overwrite: true);
        return destination;
    }

    private static string FindRepositoryRoot()
    {
        var current = AppContext.BaseDirectory;
        while (!string.IsNullOrWhiteSpace(current))
        {
            var detect = Path.Combine(current, "meteor_detector", "cli.py");
            var detector = Path.Combine(current, "meteor_detector");
            var importer = Path.Combine(current, ImporterRelativePath.Replace('/', Path.DirectorySeparatorChar));
            if (File.Exists(detect) && Directory.Exists(detector) && File.Exists(importer))
            {
                return current;
            }

            var parent = Directory.GetParent(current);
            if (parent is null)
            {
                break;
            }

            current = parent.FullName;
        }

        throw new DirectoryNotFoundException("Could not find MeteorDetect detector files from the application directory.");
    }

    private static string FindPythonExecutable(string repositoryRoot)
    {
        foreach (var candidate in BundledPythonCandidates(repositoryRoot))
        {
            if (File.Exists(candidate))
            {
                return candidate;
            }
        }

        return RuntimeInformation.IsOSPlatform(OSPlatform.Windows) ? "python" : "python3";
    }

    private static IEnumerable<string> BundledPythonCandidates(string repositoryRoot)
    {
        if (RuntimeInformation.IsOSPlatform(OSPlatform.Windows))
        {
            yield return Path.Combine(repositoryRoot, "runtime", "python", "python.exe");
            yield return Path.Combine(repositoryRoot, ".venv", "Scripts", "python.exe");
        }
        else
        {
            yield return Path.Combine(repositoryRoot, "runtime", "python", "bin", "python3");
            yield return Path.Combine(repositoryRoot, "runtime", "python", "bin", "python");
            yield return Path.Combine(repositoryRoot, ".venv", "bin", "python3");
            yield return Path.Combine(repositoryRoot, ".venv", "bin", "python");
        }
    }
}
