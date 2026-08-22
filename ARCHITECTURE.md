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

## Modules

### `detect.py`

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
