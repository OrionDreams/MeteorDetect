# Architecture

## High-level flow

```text
4K 10-bit H.264 source
        |
        v
FFmpeg decode + scale to gray16le at scan_width (default 960)
or experimental OpenCV decode normalized to uint16 grayscale
        |
        v
optimized temporal median + MAD
exact temporal model + scratch buffers
        |
        v
per-frame positive residual + local sigma threshold
        |
        v
morphology / connected components
        |
        v
line geometry filtering
        |
        v
cross-frame event grouping
        |
        v
per-clip meteor JSON
        |
        v
resolve_importer/legacy/import_meteors.py
        |
        v
Pink TimelineItem markers
```

An experimental prefilter branch remains available through
`--detector-algorithm temporal_median_mad_prefilter`, but it is not the default and is not
recommended for normal processing because it has missed real meteors on longer validation
footage.

The desktop UI is an orchestration layer, not a replacement for the detector:

```text
Avalonia desktop app
        |
        v
app-private runtime in packaged builds
or developer Python in source builds
        |
        v
python -m meteor_detector.cli -> per-clip meteor JSON
        |
        v
Resolve Lua importer
```

The Python detector remains independently runnable and testable. The UI invokes it as a subprocess, captures stderr progress/output, and reads the generated JSON. This keeps detection, packaging, and Resolve integration separated.

## Modules

### `meteor_detector/cli.py`

CLI orchestration:

- loads configuration;
- applies camera-class tuning profiles;
- discovers files;
- applies CLI overrides;
- invokes `scan_file()`;
- writes one JSON per clip by default, or a combined JSON when requested.

### `meteor_detector/detector.py`

Core implementation:

- FFprobe metadata
- FFmpeg raw-frame generator and experimental OpenCV frame generator
- optimized robust temporal model
- optional coarse prefilter experiment
- candidate extraction
- line geometry
- event grouping
- diagnostics
- profiling

The detector runtime version is independent from the desktop app version and is exported
from `meteor_detector/__init__.py`. Detector JSON files record this value as
`detector_version`.

### `resolve_importer/legacy/import_meteors.py`

Legacy external-Python Resolve-side importer. It is intentionally separate from image
analysis and remains available as a development/reference implementation.

### `src/MeteorDetect.App`

Avalonia desktop application for non-console users:

- load one or more clips;
- display clip name, path, duration and detection status;
- launch detection jobs using the existing detector through `python -m meteor_detector.cli`;
- parse detector progress lines emitted every 100 decoded frames;
- display progress percentage, processed frame count, approximate fps, remaining time and candidate count;
- keep an expandable, auto-scrolling detector log;
- write/read per-clip meteor JSON files, with an optional combined JSON mode;
- record successful detections in local processing history;
- help install the Resolve Lua Utility script;
- remember the detected or user-supplied Resolve script directory.

The desktop app version is owned by the .NET project metadata in
`src/MeteorDetect.App/MeteorDetect.App.csproj`. `Version` / `PackageVersion` use the
SemVer value such as `0.2.3`; `InformationalVersion` uses the release tag spelling such as
`v0.2.3`. App releases should be tagged with the same `vX.Y.Z` value.

Packaged releases should bundle the detector runtime. Source/development builds may use the active developer Python environment.

### `src/MeteorDetect.App` persistent state

The desktop app stores settings under the platform user config directory in a `MeteorDetect` subdirectory:

- `settings.json`: Resolve script directory and output-mode preference.
- `history.json`: successful clip runs, meteor count, output JSON path, detector version, detector algorithm, fast-prefilter flag and source file metadata.

History entries are UI convenience data. They are independent from detector JSON outputs and should not be treated as the authoritative detection record.

## Temporal model

Default window is 25 frames with samples every 2 frames, yielding 13 samples. The robust model computes:

```text
background(x,y) = temporal median
MAD(x,y)        = median(abs(frame - background))
sigma(x,y)      = max(noise_floor, 1.4826 * MAD)
```

One model is reused for an 8-frame target block.

The default detector algorithm is `optimized_temporal_median`. It uses the same median/MAD
detection model as the original `temporal_median_mad` path, but computes the exact temporal
median with partition-based NumPy operations and reusable scratch buffers. The older
`temporal_median_mad` algorithm remains available as a slower fallback if the optimized
default misses a meteor on real footage.

In plain terms, for each pixel location the detector looks through nearby sampled frames
and estimates:

- normal brightness: the median value over nearby time;
- normal variation: MAD, the median distance from that normal brightness.

Example:

```text
sample values:        [100, 101, 99, 100, 102, 100, 850]
median background:    100
absolute deviations:  [0, 1, 1, 0, 2, 0, 750]
MAD:                  1
```

The temporary spike does not define the background or normal noise. That is why faint,
short-lived streaks can stand out while stable stars and foreground are suppressed.

## Camera classes

Camera class is separate from detector algorithm. The algorithm controls the implementation
used to analyze frames. The camera class controls the threshold profile used for a family of
footage.

Available camera classes:

- `sony_mirrorless`: the existing default behavior tuned for the original Sony mirrorless
  footage.
- `noisy_camera`: a stricter threshold profile for noisier, more heavily processed video
  such as security-camera or compressed night-mode footage.

The noisy-camera profile keeps the same temporal median/MAD detector but raises candidate
thresholds. It does not skip frames with many candidates and does not change event grouping.

## Diagnostics

Diagnostic level 1 is the default and preserves the existing annotated candidate JPEGs.

Diagnostic level 2 writes additional sidecar diagnostics for each candidate frame:

- positive residual image;
- blurred residual image used for thresholding;
- threshold mask before morphology;
- local sigma map and final signal-threshold map;
- per-frame candidate stats JSON.

## Fast prefilter

The prefilter is not recommended for normal processing. It remains available only as an
experimental profiling path because it missed real meteors on `C2746.MP4`.

The prefilter uses two distant frames around the block as static references. For each target frame:

```text
positive_transient = max(current - max(previous_reference, next_reference), 0)
```

The maximum transient is accumulated across an expanded target range. This is designed to suppress:

- static stars;
- static terrain;
- static building lights;
- monotonic twilight change.

A permissive connected-component / elongation test then answers only:

> Is this block worth deep analysis?

It does not determine whether the object is a meteor.

## Timing coordinate

All authoritative event timing uses integer source-frame indices. Do not convert to decimal seconds and back when avoidable.

## Resolve-side integration

Normal user path:

```text
external detector -> per-clip meteor JSON -> Resolve Workspace/Utility Lua script -> TimelineItem:AddMarker()
```

`resolve_importer/Import Meteors.lua` is the preferred end-user importer. It is self-contained so the Resolve host does not depend on the detector's Python runtime. `resolve_importer/legacy/import_meteors.py` remains as a development/reference implementation.

The desktop UI may install or update `Import Meteors.lua` by probing known Resolve Utility script directories. If no directory is found, the user can choose one manually and the UI should remember that directory. A future Resolve utility may launch the desktop app with the selected original media path, but the app must remain useful without that integration.
