# Architecture

## High-level flow

```text
4K 10-bit H.264 source
        |
        v
FFmpeg decode + scale to gray16le at scan_width (default 960)
        |
        +------------------------------+
        | optional --fast-prefilter    |
        | ~480 px temporal streak test |
        +------------------------------+
        | pass                         | reject
        v                              v
robust temporal median + MAD        skip deep block
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
meteors.json
        |
        v
resolve_importer/import_meteors.py
        |
        v
Pink TimelineItem markers
```

The desktop UI is an orchestration layer, not a replacement for the detector:

```text
Avalonia desktop app
        |
        v
app-private runtime in packaged builds
or developer Python in source builds
        |
        v
python -m meteor_detector.cli -> meteors.json
        |
        v
Resolve Lua importer
```

The Python detector remains independently runnable and testable. The UI should invoke it as a subprocess, capture progress/output, and read the generated JSON. This keeps detection, packaging, and Resolve integration separated.

## Modules

### `meteor_detector/cli.py`

CLI orchestration:

- loads configuration;
- discovers files;
- applies CLI overrides;
- invokes `scan_file()`;
- writes combined JSON.

### `meteor_detector/detector.py`

Core implementation:

- FFprobe metadata
- FFmpeg raw-frame generator
- robust temporal model
- optional coarse prefilter
- candidate extraction
- line geometry
- event grouping
- diagnostics
- profiling

### `resolve_importer/import_meteors.py`

Resolve-side importer. It is intentionally separate from image analysis.

### `src/MeteorDetect.App`

Avalonia desktop application for non-console users:

- load one or more clips;
- display clip name, path, duration and detection status;
- launch detection jobs using the existing detector;
- write/read `meteors.json`;
- help install the Resolve Lua Utility script;
- remember the detected or user-supplied Resolve script directory.

Packaged releases should bundle the detector runtime. Source/development builds may use the active developer Python environment.

## Temporal model

Default window is 25 frames with samples every 2 frames, yielding 13 samples. The robust model computes:

```text
background(x,y) = temporal median
MAD(x,y)        = median(abs(frame - background))
sigma(x,y)      = max(noise_floor, 1.4826 * MAD)
```

One model is reused for an 8-frame target block.

## Fast prefilter

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
external detector -> meteors.json -> Resolve Workspace/Utility Lua script -> TimelineItem:AddMarker()
```

`resolve_importer/Import Meteors.lua` is the preferred end-user importer. It is self-contained so the Resolve host does not depend on the detector's Python runtime. `resolve_importer/import_meteors.py` remains as a development/reference implementation.

The desktop UI may install or update `Import Meteors.lua` by probing known Resolve Utility script directories. If no directory is found, the user can choose one manually and the UI should remember that directory. A future Resolve utility may launch the desktop app with the selected original media path, but the app must remain useful without that integration.
