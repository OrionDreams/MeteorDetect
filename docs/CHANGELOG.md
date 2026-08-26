# Changelog

## Unreleased

- Added explicit app and detector-runtime version sources: the desktop app now uses .NET
  project metadata for `v0.2.3`, while the Python detector runtime reports `0.6.0`.
- Improved temporal background median performance with a sort-network implementation for
  small sampled-frame stacks.
- Added a Diagnostic Level setting to the desktop app and detector CLI.
- Added camera-class tuning profiles with `sony_mirrorless` as the default and `noisy_camera`
  as a stricter profile for noisy or heavily processed night video.
- Added the Camera Class selector to the desktop app and moved it to the top bar for easier
  per-run access.
- Renamed the default camera-class label to "Mirrorless (Sony, Canon, etc)" while preserving
  the existing `sony_mirrorless` internal ID.
- Added diagnostic level 2 with residual, threshold-mask, sigma-map, threshold-map and
  candidate-stat sidecars for candidate frames.
- Fixed progress/frame-count estimates for videos whose `avg_frame_rate` metadata disagrees
  with the nominal stream frame rate, using packet counts as a fallback when frame count
  metadata is absent.

## v0.2.3 Beta with Detector runtime 0.6.0

- Added a GitHub Actions release workflow for tag-triggered packaging.
- Release builds now produce Windows x64 `.zip`, Linux x64 `.tar.gz`, Linux x64 `.AppImage`, and macOS `.dmg` artifacts for Apple Silicon and Intel.
- Manual `workflow_dispatch` runs build downloadable artifacts without requiring a tag.
- Tag pushes matching `v*` attach the packaged artifacts to the GitHub Release.
- Packaged builds prefer a bundled `runtime/detector/meteor-detector` executable, while development builds continue to use `python -m meteor_detector.cli`.
- Release packages include bundled static `ffmpeg` and `ffprobe` binaries under `runtime/ffmpeg`.
- Set the desktop executable assembly name to `MeteorDetect` for release artifacts.
- Added tracked app icon assets for Windows, Linux and macOS release packages.
- Replaced the desktop app header letter badge with the MeteorDetect logo.
- Reworked the README around first-time user workflows and moved development-target notes into `DEVELOPERS.md`.

## v0.2.1 with Detector runtime 0.6.0

- Added a C# / Avalonia desktop app for loading clips and launching the Python detector.
- Added UI progress display with processed frames, approximate fps, remaining-time countdown, candidate count and expandable auto-scrolling logs.
- Added processing history for successful clip detections.
- Added Resolve importer installation support from the app Settings tab.
- Changed default detector output to one timestamped JSON file per source clip; combined output remains available with `--output-mode combined` or the UI setting.
- Detector progress is now reported every 100 decoded frames and again at completion.
- Added optional Ignore camera bumps detector mode to drop frames with more than 15 meteor-like candidates.
- Added `resolve_importer/Import Meteors.lua`, a self-contained in-Resolve importer.
- Lua importer reads detector JSON without external Lua dependencies.
- Adds Pink markers to matching TimelineItem clips and skips detections trimmed out of an edit.
- Uses marker custom data to avoid duplicate imports.
- Added interactive JSON selection with environment/home-directory fallbacks.
- Added `resolve_importer/README_LUA.md` and Lua-first installation instructions to the main README.
- Kept the Python Resolve importer for debugging and cross-checking.
- Added detector algorithm selection and made `optimized_temporal_median` the default.
- Kept the original `temporal_median_mad` algorithm as a slower fallback for suspected missed meteors.
- Marked `temporal_median_mad_prefilter` as experimental/not recommended after C2746 validation showed missed real meteors.
- Optimized temporal modeling with exact partition-based median/MAD, reusable scratch buffers and precomputed local threshold maps.

## Detector runtime 0.5.0

- Added `--profile` with per-stage wall-clock timings and counters.
- Added profile data to per-file JSON records when requested.
- Added experimental `--fast-prefilter` / `--no-fast-prefilter` controls.
- Added a coarse CPU-only temporal streak prefilter at reduced resolution.
- Prefilter uses two distant temporal references to suppress static stars/foreground and monotonic brightness changes.
- Prefilter accumulates weak line evidence over an expanded block to support multi-frame long-shutter meteors.
- Added an empty-mask early return before morphology/connected-components in the deep detector.
- Added AI/developer documentation: `AGENTS.md`, `PROJECT_NOTES.md`, `ARCHITECTURE.md`, `PERFORMANCE.md`, `TESTING.md`.
- Known-positive 4K regression clip remains one event at frames 29–31 in both baseline and fast-prefilter development tests.

## Detector runtime  0.4.0

- Reused robust temporal median/MAD model across blocks.
- Temporally subsampled model input.
- Cached blurred noise map.
- Preserved faint multi-frame meteor detection with event-level validation.

## Detector runtime  0.3.0

- Added per-pixel temporal noise normalization and stricter line geometry.
- Achieved strong false-positive rejection, but performance was too slow.

## Detector runtime  0.1–0.2

- Initial temporal/background and streak detection experiments.
- Excessive star/foreground false positives motivated robust local-noise modeling.
