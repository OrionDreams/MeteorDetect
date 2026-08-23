# Changelog

## 0.6.0

- Added `resolve_importer/Import Meteors.lua`, a self-contained in-Resolve importer.
- Lua importer reads detector JSON without external Lua dependencies.
- Adds Pink markers to matching TimelineItem clips and skips detections trimmed out of an edit.
- Uses marker custom data to avoid duplicate imports.
- Added interactive JSON selection with environment/home-directory fallbacks.
- Added `resolve_importer/README_LUA.md` and Lua-first installation instructions to the main README.
- Kept the Python Resolve importer for debugging and cross-checking.

## 0.5.0

- Added `--profile` with per-stage wall-clock timings and counters.
- Added profile data to per-file JSON records when requested.
- Added experimental `--fast-prefilter` / `--no-fast-prefilter` controls.
- Added a coarse CPU-only temporal streak prefilter at reduced resolution.
- Prefilter uses two distant temporal references to suppress static stars/foreground and monotonic brightness changes.
- Prefilter accumulates weak line evidence over an expanded block to support multi-frame long-shutter meteors.
- Added an empty-mask early return before morphology/connected-components in the deep detector.
- Added AI/developer documentation: `AGENTS.md`, `PROJECT_NOTES.md`, `ARCHITECTURE.md`, `PERFORMANCE.md`, `TESTING.md`.
- Known-positive 4K regression clip remains one event at frames 29–31 in both baseline and fast-prefilter development tests.

## 0.4.0

- Reused robust temporal median/MAD model across blocks.
- Temporally subsampled model input.
- Cached blurred noise map.
- Preserved faint multi-frame meteor detection with event-level validation.

## 0.3.0

- Added per-pixel temporal noise normalization and stricter line geometry.
- Achieved strong false-positive rejection, but performance was too slow.

## 0.1–0.2

- Initial temporal/background and streak detection experiments.
- Excessive star/foreground false positives motivated robust local-noise modeling.
