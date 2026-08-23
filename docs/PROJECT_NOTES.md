# Project Notes

## User / environment

Reference environment established during development:

- OS: CachyOS Linux
- DaVinci Resolve Studio: 21.0.4 Build 5
- Camera: Sony A7 IV
- Lens: Sigma 20 mm, but field-of-view calculations are intentionally out of scope for the current detector
- Camera is stationary on a tripod
- Video: 3840×2160
- Codec: H.264 High 4:2:2, about 100 Mb/s
- Pixel format from FFprobe: `yuv422p10le(pc, progressive)`
- Frame rate: exactly `24000/1001`
- Time base: `1/24000`
- Gamma: S-Log3-Cine
- Primaries: S-Gamut3-Cine
- Coding equations: Rec.709
- Typical clips: 15–90 minutes
- Sony files can contain a 90-degree display rotation and RTMD timed metadata

## Important imaging behavior

The user may record 23.976 fps with shutter times such as 1/10 s. Consequently one sensor exposure can span multiple encoded video frames. A meteor may therefore appear essentially unchanged in two consecutive frames.

Any detector that assumes `meteor == object that changes position every frame` is invalid for this project.

## Desired output

Current goal: one Pink Resolve marker per meteor.

Preferred destination: marker on the actual timeline clip (`TimelineItem`) rather than only a timeline-global marker.

Future ideas, not required for current versions:

- Small/Big marker classes
- classification from duration, brightness and illuminated pixel count
- magnitude-like scoring
- angular measurements using lens/FOV

## Architecture decision

Keep detection independent of DaVinci Resolve.

1. external Python/FFmpeg/OpenCV detector scans video;
2. detector writes JSON using source frame numbers, currently one timestamped JSON file per clip by default;
3. Resolve Lua importer matches filenames and adds Pink clip markers to timeline clips.

This separation is intentional for safety, tuning and batch processing.

The older external Python Resolve importer remains available as a debugging/reference implementation, but it is not the preferred end-user path.

## Detection history

### v0.1 / v0.2

Early simple temporal/background approaches detected huge numbers of stars and foreground features. One run generated a `meteors.json` with about 236,000 lines.

Lesson: global residual thresholds and weak geometry are insufficient for this footage.

### v0.3

Per-pixel robust temporal noise normalization (median/MAD) plus stricter line morphology produced almost zero false positives and successfully detected meteors.

Major problem: speed. User observed roughly 5,000 frames in 30 minutes.

### v0.4

Reused one robust temporal model over an 8-frame block and temporally subsampled the model window. Accuracy stayed strong and speed improved to approximately 25,000 frames in 15 minutes on the user's hardware — about 100,000 frames/hour.

User's target is closer to 100,000 frames in ~10 minutes if feasible.

### v0.5

Adds profiling and an experimental coarse CPU prefilter. See `PERFORMANCE.md`.

### v0.6

Adds the first desktop application around the detector, plus the self-contained in-Resolve Lua importer. The app can load multiple clips, run detection through the Python CLI, show progress parsed from detector stderr, install the Lua importer, and keep a local processing history.

The CLI and UI now default to per-clip JSON output. Combined multi-clip JSON remains available for compatibility, but normal Resolve import should expect one JSON per processed clip.

## Real sample findings

The user supplied an original 4K sample:

`C2738-00.01.58.243-00.02.00.996.MP4`

It contains exactly one meteor.

The meteor is faint/moderate in an individual encoded frame but coherent and elongated across multiple frames. v0.4/v0.5 deep detection returns one event spanning source frames 29–31 in the supplied trimmed clip.

This is a key design finding: multi-frame line coherence is more informative than requiring a very strong individual-frame signal.

## Current optimization constraint

The user explicitly wants CPU optimization first so the software can eventually be available regardless of GPU vendor. Do not make GPU acceleration a dependency. GPU mode may be considered later as optional acceleration.

## Resolve integration direction (v0.6)

End-user Resolve integration should be an **in-Resolve Lua Utility script**, not a requirement to invoke the importer from an external Python/Distrobox environment. The detector remains external and communicates through detector JSON files. Keep the Lua importer self-contained and dependency-free where practical; the Python importer is a debugging/reference implementation.

## Desktop application direction

End-user usability should not require console commands or a system Python install. The preferred desktop UI direction is:

- C# + Avalonia for the cross-platform desktop shell;
- the existing Python detector remains the authoritative headless detection engine;
- the desktop app is an orchestration layer: it loads clips, starts detector subprocesses, parses progress logs, shows status/results and helps install the Resolve Lua importer;
- public releases should bundle a private Python runtime, pinned Python dependencies, FFmpeg/ffprobe, detector code and the Resolve Lua importer;
- do not rely on the user's system Python, NumPy, OpenCV or FFmpeg versions for normal packaged releases;
- first-run dependency installation is acceptable for development/beta experiments, but the target public release model is a fully bundled runtime.

Expected early release artifacts:

- Windows x64: `.zip`;
- Linux x64: `.AppImage` plus `.tar.gz` fallback;
- macOS Apple Silicon / Intel: `.dmg`.

Unsigned builds are acceptable for early releases. Windows users may see SmartScreen warnings and macOS users may need to right-click/Open. Signing and notarization are desirable later, but should not block getting a working cross-platform package.

Distribution can initially use GitHub Releases with website links to the latest release. A few hundred megabytes per platform is acceptable because avoiding dependency friction matters more than minimizing the initial download size.
