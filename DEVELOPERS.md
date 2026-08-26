# MeteorDetect Developers

This file collects source-build and development-context notes that do not need to be in the main user README.

## Development target

The reference environment used during development:

- DaVinci Resolve Studio 21.0.4 Build 5
- Linux / CachyOS
- Sony A7 IV, 3840x2160 H.264 High 4:2:2 10-bit
- exactly `24000/1001` fps
- S-Log3 / S-Gamut3.Cine
- stationary tripod
- long shutter times where one camera exposure can be represented by multiple encoded video frames

The detector should remain CPU-only and GPU-vendor-independent by default. Optional GPU acceleration can be explored later, but it should not become a required dependency.

## Run from source

Install Python dependencies:

```bash
bin/install.sh
```

You also need `ffmpeg` and `ffprobe` available on `PATH`.

Run the development UI:

```bash
tools/dev-app.sh
```

Build the app:

```bash
tools/build-app.sh
```

Publish for the current platform:

```bash
tools/publish-app.sh
```

Source/development builds use a bundled runtime if present under `runtime/python` and `runtime/ffmpeg`; otherwise they fall back to `.venv` and then the platform Python executable. Public release packages should bundle their own detector runtime and FFmpeg tools.

## Detector and app boundaries

The C# / Avalonia app owns user interaction, file selection, settings, progress display, local history, packaging integration, and Resolve plugin installation.

The Python detector owns video decoding orchestration, temporal modeling, candidate extraction, event grouping, profiling, and JSON output. Keep detector behavior independently runnable and testable from the command line.

The Resolve Lua importer is intentionally separate from detection. It consumes detector JSON and adds Pink clip markers to matching timeline clips.

## Regression expectations

When changing detector behavior, preserve the project invariants documented in [AGENTS.md](AGENTS.md) and [PROJECT_NOTES.md](docs/PROJECT_NOTES.md).

At minimum, run syntax checks:

```bash
python -m py_compile meteor_detector/cli.py meteor_detector/detector.py resolve_importer/legacy/import_meteors.py
```

For desktop app or packaging changes:

```bash
dotnet build MeteorDetect.slnx
```

When the known-positive clip is available, the default detector should still report exactly one event at frames 29-31 for:

```text
C2738-00.01.58.243-00.02.00.996.MP4
```

See [TESTING.md](docs/TESTING.md) for the full regression checklist.

## AI-assisted development

This repository includes context for Codex and other coding agents:

- [AGENTS.md](AGENTS.md) - coding-agent instructions and behavioral invariants
- [PROJECT_NOTES.md](docs/PROJECT_NOTES.md) - project history, user requirements, and known findings
- [ARCHITECTURE.md](docs/ARCHITECTURE.md) - current data flow and module responsibilities
- [CSHARP-DOTNET-AVALONIA-MVVM.md](docs/CSHARP-DOTNET-AVALONIA-MVVM.md) - C# .NET and Avalonia guidance
- [PERFORMANCE.md](docs/PERFORMANCE.md) - profiling interpretation and optimization candidates
- [TESTING.md](docs/TESTING.md) - regression strategy and known-positive tests
- [CHANGELOG.md](docs/CHANGELOG.md) - version history
