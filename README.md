# MeteorDetect

CPU-first meteor detection for stationary night-sky video, with import of detections as **Pink clip markers** in DaVinci Resolve Studio.

MeteorDetect scans long video clips, finds likely meteor streaks using source-frame timing, writes detector JSON files, and helps bring those detections into the **DaVinci Resolve** video editor as clip markers.

## Quickstart
- Install MeteorDetect from the [MeteorDetect releases page](https://github.com/OrionDreams/MeteorDetect/releases).
- Open MeteorDetect, go to **Settings** and click on **Install Plugin** to install the DaVinci Resolve plugin.

For a more detailed guide, please read the next sections in this readme.

## Install the app

Download the latest package from the [MeteorDetect releases page](https://github.com/OrionDreams/MeteorDetect/releases).

Choose the package for your operating system:

- Windows: download the Windows x64 `.zip`, extract it, and run `MeteorDetect.exe`.
- Linux: download the Linux x64 `.AppImage`, make it executable if needed, and run it. A `.tar.gz` package is also provided as a fallback.
- macOS: download the `.dmg` for your Mac architecture, open it, and run MeteorDetect. Because early builds are unsigned, macOS may require right-clicking the app and choosing **Open** the first time.

Packaged releases are intended to include the app, detector runtime, FFmpeg/ffprobe, and Resolve importer files. To build or run from source, see [DEVELOPERS.md](DEVELOPERS.md).

## Use the Resolve plugin

MeteorDetect includes a DaVinci Resolve Lua Utility script:

```text
resolve_importer/Import Meteors.lua
```

Install it from the app's Settings view, or copy it into Resolve's `Fusion/Scripts/Utility` user scripts directory and restart Resolve.

Then, in Resolve:

1. Open the project and timeline containing the source clips.
2. Choose **Workspace -> Scripts -> Import Meteors**.
3. Select the JSON file produced by MeteorDetect.
4. The script adds **Pink markers to the matching clips themselves**.

The Resolve script is self-contained. It does not need Python, OpenCV, FFmpeg, or the detector virtual environment. Re-importing the same JSON is designed not to duplicate existing meteor markers.

See [resolve_importer/README_LUA.md](resolve_importer/README_LUA.md) for script directory notes and file-picker fallbacks.

## Use the app GUI

The usual workflow is:

1. Open MeteorDetect.
2. Add one or more source clips, or open a directory containing video clips.
3. Click **Detect**.
4. Wait for processing to finish.
5. In Resolve, run **Workspace -> Scripts -> Import Meteors** and select the generated JSON.

By default, MeteorDetect writes one timestamped JSON file next to each processed clip, with a name like:

```text
C2752_meteors_20260823_142233.json
```

Processed clips appear in the app with their detected meteor count. The History view keeps successful runs visible for later reference.

For output modes, detector settings, decoder choices, and how selection affects batch processing, see [GUI advanced use](#gui-advanced-use).

## Use the command line

For a single clip:

```bash
bin/detect-meteors.sh /path/to/C2752.MP4
```

For a directory:

```bash
bin/detect-meteors.sh /path/to/video-directory
```

By default, each processed clip gets its own timestamped JSON output. These JSON files can be imported with the Resolve plugin.

For detector algorithms, decoder options, profiling, combined JSON output, and direct Python module usage, see [command-line advanced use](#command-line-advanced-use).

## App and detector architecture

MeteorDetect is a C# / Avalonia desktop app with a Python detection engine.

The app handles user interaction, file selection, progress display, history, settings, packaging integration, and Resolve plugin installation. The Python detector remains the source of truth for meteor analysis and can also run independently from the command line.

Packaged builds prefer a bundled detector executable and bundled FFmpeg tools. Source builds use the local Python environment when a bundled runtime is not present.

## Pause and resume

The desktop app can pause detection, but pause is mainly intended for unavoidable interruptions and crash or power-loss recovery on very large files.

While detection is running, MeteorDetect writes a resumable partial checkpoint every 1000 analyzed frames. If the machine loses power or the app/system crashes, reopening the same clip can offer **Resume Detection** from the last saved checkpoint.

When you click **Pause**, detection does not stop immediately. The detector checks for pause requests at checkpoint boundaries, writes a partial JSON, and exits cleanly. Resume re-analyzes an overlap before the saved frame so events near the checkpoint are not split incorrectly.

Resume is not a fast seek in this version. The detector still decodes from the beginning of the clip, then skips expensive detection work until it reaches the checkpoint area.

## How the main detector works

MeteorDetect is built around a stationary-camera assumption. Stars, terrain, skyline, and sky glow are usually stable over nearby frames. Meteors are temporary bright streaks.

The default detector decodes video with FFmpeg, scales frames to a working scan width, and builds a robust temporal background model. For each pixel, it estimates normal brightness from nearby frames using a median, then estimates local noise using MAD, or Median Absolute Deviation.

A temporary spike does not become part of the background:

```text
sample values:     [100, 101, 99, 100, 102, 100, 850]
median background: 100
```

After subtracting the background, the detector keeps pixels that are bright compared with their local noise, cleans them into connected shapes, filters for narrow elongated components, and groups compatible candidates across nearby source frames.

Long shutter footage matters: one physical meteor exposure may appear in two or more encoded frames, so MeteorDetect does not require motion between every adjacent frame.

## High-level algorithm overview

```text
source video
  -> FFmpeg decode and grayscale scaling
  -> temporal median background model
  -> MAD-derived local noise estimate
  -> positive transient residuals
  -> morphology and connected components
  -> line geometry filtering
  -> cross-frame event grouping
  -> per-clip meteor JSON
  -> Resolve Pink clip markers
```

Authoritative timing uses integer source frame numbers, not rounded seconds. The reference footage is `24000/1001` fps, and detector JSON stores frame rate as a rational pair:

```json
{
  "fps_num": 24000,
  "fps_den": 1001
}
```

Example event:

```json
{
  "id": "C2752-000001",
  "start_frame": 1487,
  "end_frame": 1490,
  "peak_frame": 1489,
  "video_frame_count": 4,
  "confidence": 0.91
}
```

## GUI advanced use

Open a directory to list `.mp4`, `.mov`, and `.m4v` clips. Directory clips are listed alphabetically. The app scans the same directory for completed detector JSON files whose names contain `_meteors_`; when more than one JSON matches a clip, the newest JSON is used.

If no clip is selected, **Detect** starts at the first unprocessed visible clip and continues through the remaining unprocessed clips. Select one or more clips to process only that selection, in visible-list order. Use Ctrl+Click on Linux/Windows, Command+Click on macOS, or Shift+Click for a range.

Settings currently include detector algorithm, decoder, Resolve script directory, and output mode. Per-clip timestamped JSON is the default. Combined JSON output remains available for workflows that need one result file for multiple clips.

## Command-line advanced use

Disable JPEG diagnostics and record profiling:

```bash
bin/detect-meteors.sh C2752.MP4 --no-diagnostics --profile
```

Run the default optimized detector explicitly:

```bash
bin/detect-meteors.sh C2752.MP4 --detector-algorithm optimized_temporal_median
```

Run the original slower baseline if you suspect the optimized detector missed a real meteor:

```bash
bin/detect-meteors.sh C2752.MP4 --detector-algorithm temporal_median_mad
```

Run the experimental Fast Prefilter path only for comparison or profiling:

```bash
bin/detect-meteors.sh C2752.MP4 --detector-algorithm temporal_median_mad_prefilter
```

Use a combined JSON output for multiple clips:

```bash
bin/detect-meteors.sh /path/to/video-directory --output-mode combined -o meteors.json
```

Use a custom config:

```bash
cp config.example.json config.json
bin/detect-meteors.sh C2752.MP4 --config config.json
```

The default decoder is FFmpeg, which preserves the best-tested 16-bit grayscale path:

```bash
bin/detect-meteors.sh C2752.MP4 --decoder ffmpeg
```

An experimental OpenCV decoder is available for speed comparisons:

```bash
bin/detect-meteors.sh C2752.MP4 --decoder opencv
```

For headless integrations, call the Python module directly:

```bash
.venv/bin/python -m meteor_detector.cli C2752.MP4 \
  -o C2752_meteors.json \
  --no-diagnostics \
  --detector-algorithm optimized_temporal_median
```

The detector prints coarse progress to stderr every 100 decoded frames and once more at completion, for example:

```text
[C2752.MP4] frame 1200/25000, candidates=3
```

## Detector tuning and profiling

The default `optimized_temporal_median` detector is the normal choice. It uses the same recall-focused temporal median/MAD detection idea as the original baseline, but computes the temporal model faster and avoids repeated large temporary allocations.

The `temporal_median_mad_prefilter` path is not recommended for routine use. It remains available for experiments because longer validation found missed real meteors. Treat prefilter settings as recall-first: a false-positive block wastes some CPU, while a false-negative block can miss a meteor.

For comparable performance measurements, use:

```bash
--no-diagnostics --profile
```

See [PERFORMANCE.md](docs/PERFORMANCE.md) for optimization notes and [TESTING.md](docs/TESTING.md) for regression guidance.

## More documentation

- [DEVELOPERS.md](DEVELOPERS.md) - source setup, development target, and packaging notes
- [ARCHITECTURE.md](docs/ARCHITECTURE.md) - data flow and module responsibilities
- [TESTING.md](docs/TESTING.md) - regression strategy and known-positive tests
- [PERFORMANCE.md](docs/PERFORMANCE.md) - profiling interpretation and optimization candidates
- [CHANGELOG.md](docs/CHANGELOG.md) - version history
- [PROJECT_NOTES.md](docs/PROJECT_NOTES.md) - project history, requirements, and known findings
