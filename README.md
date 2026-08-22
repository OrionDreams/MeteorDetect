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

The detector itself is independent of Resolve. It writes a JSON file named after the source video, such as `C2752_meteors.json`; the included Resolve importer reads that JSON and places Pink markers on matching timeline clips.

## What's new in v0.6

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

### 2. Experimental CPU-only fast prefilter

Enable it with:

```bash
bin/detect-meteors.sh VIDEO.MP4 --no-diagnostics --profile --fast-prefilter
```

This is **not** a second meteor classifier. It is a deliberately permissive cheap test whose only purpose is to reject blocks that are obviously quiet before v0.4's expensive per-pixel temporal median/MAD model runs.

At roughly 480×270, it compares target frames against two distant temporal references. It keeps only positive signal that is brighter than both references, accumulates evidence across the block, and performs a permissive elongated-component test. This largely cancels stationary stars, foreground and monotonic twilight changes without doing a full robust noise model.

Blocks near a possible streak receive a temporal safety margin (`prefilter_margin_frames`) so a meteor near an 8-frame block boundary can cause both neighboring blocks to be analyzed deeply.

The prefilter is **off by default** until it has been validated on more known-positive clips.

## Known-positive regression clip

The supplied original 4K sample:

```text
C2738-00.01.58.243-00.02.00.996.MP4
```

contains one meteor. v0.5's deep detector finds one event spanning source frames **29–31**. The default fast-prefilter settings also preserve that same event in the development test.

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

By default, `C2752.MP4` writes `C2752_meteors.json`. If that file already exists, the detector writes `C2752_meteors_1.json`, then `C2752_meteors_2.json`, and so on. Use `-o` only when you want to force a specific output path.

Disable JPEG diagnostics for speed measurements:

```bash
bin/detect-meteors.sh C2752.MP4 --no-diagnostics
```

Profile the current accurate deep detector:

```bash
bin/detect-meteors.sh C2752.MP4 -o baseline.json --no-diagnostics --profile
```

Profile the experimental prefilter:

```bash
bin/detect-meteors.sh C2752.MP4 -o fast.json --no-diagnostics --profile --fast-prefilter
```

Use a custom config:

```bash
cp config.example.json config.json
bin/detect-meteors.sh C2752.MP4 --config config.json
```

If `fast_prefilter` is enabled in a config and you want to force it off:

```bash
bin/detect-meteors.sh C2752.MP4 --config config.json --no-fast-prefilter
```

## How the main detector works

At a 960-pixel scan width, the accurate path:

1. decodes the 10-bit video to `gray16le` using FFmpeg;
2. samples a symmetric 25-frame temporal window;
3. builds a robust per-pixel median background and MAD-derived local noise map;
4. reuses that model over an 8-frame block;
5. looks for positive transient residuals relative to local noise;
6. keeps narrow elongated components;
7. groups compatible candidates across nearby frames into meteor events;
8. allows the same meteor exposure to repeat across consecutive encoded frames.

A single-frame event can still be accepted, but it must satisfy stronger geometry and signal requirements.

## Fast prefilter configuration

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

See [PERFORMANCE.md](PERFORMANCE.md) for the optimization roadmap and [TESTING.md](TESTING.md) for regression guidance.

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
3. Select the detector's JSON output, such as `C2752_meteors.json`.
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

- [AGENTS.md](AGENTS.md) — coding-agent instructions and invariants
- [PROJECT_NOTES.md](PROJECT_NOTES.md) — project history, user requirements and known findings
- [ARCHITECTURE.md](ARCHITECTURE.md) — current data flow and module responsibilities
- [PERFORMANCE.md](PERFORMANCE.md) — profiling interpretation and optimization candidates
- [TESTING.md](TESTING.md) — regression strategy and known-positive tests
- [CHANGELOG.md](CHANGELOG.md) — version history

Agents should read `AGENTS.md` and `PROJECT_NOTES.md` before changing detector logic.
