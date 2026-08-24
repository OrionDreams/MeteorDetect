# Resolve Meteor Detector v0.6

CPU-first meteor detection for stationary night-sky video, with import of detections as **Pink clip markers** in DaVinci Resolve Studio.

Development target:

- DaVinci Resolve Studio 21.0.4 Build 5
- Linux / CachyOS
- Sony A7 IV, 3840×2160 H.264 High 4:2:2 10-bit
- exactly 24000/1001 fps
- S-Log3 / S-Gamut3.Cine
- stationary tripod
- long shutter times where one camera exposure can be represented by multiple encoded video frames

The detector itself is independent of Resolve. By default, it writes one JSON file per source video, such as `C2752_meteors_20260823_142233.json`; the included Resolve importer reads that JSON and places Pink markers on matching timeline clips.

## What's new in v0.6

- Added a first-pass **Avalonia desktop UI** for loading clips, running detection, watching progress and installing the Resolve Lua importer.
- Added UI progress reporting: progress bar, processed frame count, approximate fps, remaining-time countdown, candidate count and expandable auto-scrolling logs.
- Added processing history for successful clips.
- Made per-clip JSON the default output mode for both CLI and UI; combined multi-clip JSON remains available as an option.
- Added a self-contained **Lua importer** that runs from Resolve's Workspace → Scripts menu.
- Added an in-Resolve JSON file-selection workflow with non-interactive fallbacks.
- Added `resolve_importer/README_LUA.md` with installation and usage instructions.
- Kept the external Python importer as a developer/debug fallback.

## v0.5 detector changes

v0.5 is the measurement/optimization release built on the accurate v0.4 detector.

### 1. Profiling mode

Run:

```bash
bin/detect-meteors.sh VIDEO.MP4 --no-diagnostics --profile
```

The detector prints and stores timing for:

- FFmpeg decode / pipe waiting
- optional fast prefilter
- temporal median + MAD model
- per-frame residual / blur / threshold
- morphology + connected-components
- component geometry
- diagnostic JPEG writing
- event grouping

It also records counters such as temporal models built, deeply analyzed frames, empty masks, candidate frames and prefilter block pass/reject counts.

The profile is included under each file's `profile` object in the detector JSON output.

### 2. Detector algorithms

The detector has named algorithm presets:

```text
optimized_temporal_median       current default, optimized exact temporal median model
temporal_median_mad             original accurate baseline, slowest
temporal_median_mad_prefilter   original baseline plus experimental Fast Prefilter
```

`optimized_temporal_median` is the normal choice. It keeps the same recall-focused detector behavior as the original median/MAD path, but computes the temporal model with a faster exact implementation and reusable scratch buffers.

If the optimized default misses a meteor on a real clip, rerun that clip with `temporal_median_mad`. That older path is slower, but it is useful as a conservative fallback and comparison baseline.

`temporal_median_mad_prefilter` is not recommended for normal processing. On a longer known-positive clip (`C2746.MP4`), the Fast Prefilter missed real meteors. Keep it as an experimental profiling option only.

Select an algorithm from the desktop Settings view, or from the CLI:

```bash
bin/detect-meteors.sh VIDEO.MP4 --no-diagnostics --profile --detector-algorithm optimized_temporal_median
```

The old `--fast-prefilter` flag remains as a shortcut for `--detector-algorithm temporal_median_mad_prefilter`.
The previous `fastdetect_experimental` id remains accepted as a compatibility alias for `optimized_temporal_median`.

### 3. Experimental CPU-only fast prefilter

Enable it with:

```bash
bin/detect-meteors.sh VIDEO.MP4 --no-diagnostics --profile --detector-algorithm temporal_median_mad_prefilter
```

This is **not** a second meteor classifier. It is a deliberately permissive cheap test whose only purpose is to reject blocks that are obviously quiet before v0.4's expensive per-pixel temporal median/MAD model runs.

At roughly 480×270, it compares target frames against two distant temporal references. It keeps only positive signal that is brighter than both references, accumulates evidence across the block, and performs a permissive elongated-component test. This largely cancels stationary stars, foreground and monotonic twilight changes without doing a full robust noise model.

Blocks near a possible streak receive a temporal safety margin (`prefilter_margin_frames`) so a meteor near an 8-frame block boundary can cause both neighboring blocks to be analyzed deeply.

The prefilter is **off by default** and not recommended for normal processing because longer validation found missed real meteors.

## Known-positive regression clip

The supplied original 4K sample:

```text
C2738-00.01.58.243-00.02.00.996.MP4
```

contains one meteor. The optimized default and the original temporal median/MAD path should find one event spanning source frames **29–31**.

This regression matters because the meteor is only moderately significant in individual encoded frames but forms a coherent elongated event across several frames.

## Requirements

```bash
bin/install.sh
pip install -r requirements.txt
```

You also need `ffmpeg` and `ffprobe` available on `PATH`.

`bin/install.sh` changes to the repository root, creates `.venv` if needed, and starts an activated shell. It uses `.venv/bin/activate.fish` when your login shell is Fish, otherwise it uses the standard POSIX activation script.

## Basic usage

Single file:

```bash
bin/detect-meteors.sh /path/to/C2752.MP4
```

Directory:

```bash
bin/detect-meteors.sh /path/to/video-directory
```

By default, `C2752.MP4` writes a timestamped file named like `C2752_meteors_20260823_142233.json`. Directory scans write one JSON per clip. Use `-o` with a single clip when you want to force a specific output path.

To keep the legacy behavior where multiple clips are written into one JSON:

```bash
bin/detect-meteors.sh /path/to/video-directory --output-mode combined -o meteors.json
```

Disable JPEG diagnostics for speed measurements:

```bash
bin/detect-meteors.sh C2752.MP4 --no-diagnostics
```

Profile the optimized default detector:

```bash
bin/detect-meteors.sh C2752.MP4 -o optimized.json --no-diagnostics --profile
```

Run the original slower baseline if the optimized default misses a meteor:

```bash
bin/detect-meteors.sh C2752.MP4 -o original-baseline.json --no-diagnostics --profile --detector-algorithm temporal_median_mad
```

Run the experimental Fast Prefilter path only for comparison/profiling:

```bash
bin/detect-meteors.sh C2752.MP4 -o fast.json --no-diagnostics --profile --detector-algorithm temporal_median_mad_prefilter
```

For headless integrations, call the Python module directly:

```bash
.venv/bin/python -m meteor_detector.cli C2752.MP4 \
  -o C2752_meteors.json \
  --no-diagnostics \
  --detector-algorithm optimized_temporal_median
```

Use a custom config:

```bash
cp config.example.json config.json
bin/detect-meteors.sh C2752.MP4 --config config.json
```

If an older config enables `fast_prefilter` and you want to force the normal optimized path:

```bash
bin/detect-meteors.sh C2752.MP4 --config config.json --no-fast-prefilter
```

The detector prints coarse progress to stderr every 100 decoded frames and once more at completion, for example:

```text
[C2752.MP4] frame 1200/25000, candidates=3
```

The desktop UI parses these messages for its progress display.

## Desktop UI

Run the development UI:

```bash
tools/dev-app.sh
```

The app is a C# / Avalonia shell around the existing Python detector. It currently supports:

- opening one or more source clips;
- showing clip duration, status and detected event count;
- running the Python detector with `--no-diagnostics --profile`;
- detector algorithm selection from Settings;
- per-clip timestamped JSON output by default, written next to each source clip;
- optional combined JSON output for multiple clips;
- progress bar, processed frames, approximate speed, remaining-time estimate and expandable logs;
- history of successful detection runs;
- detecting or choosing the Resolve `Fusion/Scripts/Utility` directory and installing `Import Meteors.lua`.

Development builds use a bundled runtime if present under `runtime/python` and `runtime/ffmpeg`; otherwise they fall back to `.venv` and then the platform Python executable. Public releases should bundle their own runtime.

## How the main detector works

At a 960-pixel scan width, the default `Optimized Temporal Median` path:

1. decodes the 10-bit video to `gray16le` using FFmpeg;
2. samples a symmetric 25-frame temporal window;
3. builds a robust per-pixel median background and MAD-derived local noise map using the optimized exact temporal model;
4. reuses that model over an 8-frame block;
5. looks for positive transient residuals relative to local noise;
6. keeps narrow elongated components;
7. groups compatible candidates across nearby frames into meteor events;
8. allows the same meteor exposure to repeat across consecutive encoded frames.

A single-frame event can still be accepted, but it must satisfy stronger geometry and signal requirements.

### High-level algorithm overview

The detector is built around the stationary-camera assumption. Most of the image should be stable over nearby frames: stars, terrain, skyline and sky glow usually stay in the same place. Meteors are different because they are temporary bright streaks.

For each model block, the detector looks at a 25-frame window around an anchor frame and samples every other frame, giving 13 sampled frames. For every pixel location, it asks: "What is this pixel's normal brightness over nearby time?"

Example brightness values for one pixel over the sampled frames:

```text
[100, 101, 99, 100, 102, 100, 850]
```

The `850` could be a meteor, glint or other temporary spike. The median is `100`, so the spike does not become part of the background. That is why the detector uses a median instead of an average.

MAD means Median Absolute Deviation. After finding the median brightness, the detector measures how far each sampled value is from that median:

```text
median brightness: 100
absolute deviations: [0, 1, 1, 0, 2, 0, 750]
MAD: 1
```

MAD gives a robust estimate of local pixel noise. The detector converts that to a sigma-like value:

```text
sigma = max(noise_floor, 1.4826 * MAD)
```

Then each target frame is compared with the background. A pixel only survives if it is bright in absolute terms and bright compared with its own local noise. Surviving pixels are cleaned up into connected shapes, and only narrow elongated shapes can become meteor candidates. Nearby compatible candidates are grouped into final meteor events using source frame numbers.

The original `Temporal Median / MAD` algorithm and the default `Optimized Temporal Median` algorithm use the same detection idea. The optimized version uses a faster exact way to compute the median/MAD model and avoids repeated large temporary allocations.

## Fast prefilter configuration

The Fast Prefilter path is not recommended for normal use. It remains available only for experiments because it missed real meteors on longer validation footage.

Defaults:

```json
{
  "fast_prefilter": false,
  "prefilter_width": 480,
  "prefilter_minimum_threshold": 180.0,
  "prefilter_min_component_area": 2,
  "prefilter_max_component_area": 900,
  "prefilter_min_streak_length": 3.5,
  "prefilter_min_elongation": 1.6,
  "prefilter_max_streak_width": 10.0,
  "prefilter_margin_frames": 8
}
```

Treat these as **recall-first** settings. A false-positive block only wastes some CPU; a false-negative block can miss a meteor. Do not tighten the prefilter based only on speed.

The first metrics to inspect are:

```text
Prefilter blocks
Prefilter passed
Prefilter rejected
Deep blocks skipped
Meteor events
```

If a long astronomical-night recording rejects almost no blocks, the prefilter is not useful enough yet. If it rejects many blocks but known meteors disappear, it is too strict.

## Profiling notes

`decode_wait` measures wall-clock time spent obtaining the next frame from the FFmpeg generator. It includes FFmpeg decode/scale/pipe waiting plus the Python raw-frame conversion/copy. It is intentionally an application-level measurement, not a pure FFmpeg microbenchmark.

Stage percentages do not necessarily sum to 100%; orchestration, Python loop overhead, buffer management, probing, JSON writing and profiler overhead are outside the named stages.

For comparable measurements always use:

```bash
--no-diagnostics --profile
```

and test the exact same input file.

See [PERFORMANCE.md](docs/PERFORMANCE.md) for the optimization roadmap and [TESTING.md](docs/TESTING.md) for regression guidance.

## JSON timing

Source frame numbers are authoritative. Frame rate is stored exactly as a rational:

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

## Resolve importer

For normal end users, use the **in-Resolve Lua importer**. It does not require an external Python environment.

### Install the Lua importer

Copy:

```text
resolve_importer/Import Meteors.lua
```

into Resolve's `Fusion/Scripts/Utility` user scripts directory. On the current Linux development target, the usual per-user path is:

```text
~/.local/share/DaVinciResolve/Fusion/Scripts/Utility/
```

Create the directory if necessary, copy the file there, and **restart DaVinci Resolve**. Resolve/Fusion supports interactive Utility scripts from its scripts directory, and Lua is embedded in the application.

Then:

1. Open the project and desired timeline.
2. Choose **Workspace → Scripts → Import Meteors**.
3. Select the detector's JSON output, such as `C2752_meteors_20260823_142233.json`.
4. The script adds **Pink markers to the matching clips themselves**.

The Lua file is self-contained, including its JSON reader. It does not need Python, OpenCV, FFmpeg, Distrobox, or the detector virtual environment. Re-importing the same JSON is designed not to duplicate existing meteor markers.

See [resolve_importer/README_LUA.md](resolve_importer/README_LUA.md) for details and file-picker fallbacks.

### External Python importer (developer/debug fallback)

The previous Python importer is still included for debugging. A typical Linux external scripting environment is:

```bash
export RESOLVE_SCRIPT_API=/opt/resolve/Developer/Scripting
export RESOLVE_SCRIPT_LIB=/opt/resolve/libs/Fusion/fusionscript.so
export PYTHONPATH="$PYTHONPATH:$RESOLVE_SCRIPT_API/Modules"
python resolve_importer/import_meteors.py meteors.json
```


## AI-assisted development

This package deliberately includes repository context for Codex and other coding agents:

- [AGENTS.md](AGENTS.md) - coding-agent instructions and invariants
- [PROJECT_NOTES.md](docs/PROJECT_NOTES.md) - project history, user requirements and known findings
- [ARCHITECTURE.md](docs/ARCHITECTURE.md) - current data flow and module responsibilities
- [CSHARP-DOTNET-AVALONIA-MVVM.md](docs/CSHARP-DOTNET-AVALONIA-MVVM.md) - C# .NET and Avalonia guidance
- [PERFORMANCE.md](docs/PERFORMANCE.md) - profiling interpretation and optimization candidates
- [TESTING.md](docs/TESTING.md) - regression strategy and known-positive tests
- [CHANGELOG.md](docs/CHANGELOG.md) - version history

Agents should read `AGENTS.md` and `docs/PROJECT_NOTES.md` before changing detector logic.
