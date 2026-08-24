# Testing

## Primary regression principle

Every speed optimization must be checked for **meteor recall**, not only runtime.

## Known-positive real clip

When available:

```text
C2738-00.01.58.243-00.02.00.996.MP4
```

Expected current result:

- exactly one event
- event spans frames 29–31

Run both paths:

```bash
python -m meteor_detector.cli C2738-00.01.58.243-00.02.00.996.MP4 \
  -o optimized.json --no-diagnostics --profile

python -m meteor_detector.cli C2738-00.01.58.243-00.02.00.996.MP4 \
  -o original-baseline.json --no-diagnostics --profile --detector-algorithm temporal_median_mad
```

The experimental Fast Prefilter path may be run for comparison, but it is not recommended
for normal processing:

```bash
python -m meteor_detector.cli C2738-00.01.58.243-00.02.00.996.MP4 \
  -o fast.json --no-diagnostics --profile --detector-algorithm temporal_median_mad_prefilter
```

Compare `files[0].events`.

## Long-clip validation

For a representative astronomical-night clip with known meteors:

1. run the default `optimized_temporal_median` algorithm;
2. record event frame ranges;
3. if a known meteor is missing, rerun with `--detector-algorithm temporal_median_mad`;
4. compare event frame ranges, false positives, profiler output and wall-clock runtime;
5. run `--detector-algorithm temporal_median_mad_prefilter` only as an experimental comparison.

Do not tighten prefilter thresholds until recall has been proven on multiple known-positive clips, including faint meteors. Current long-clip validation found missed real meteors with the prefilter, so it should stay off the normal path.

## Twilight footage

Include at least one recording beginning after sunset but before full astronomical darkness. Earlier versions falsely detected skyline/foreground and changing brightness. The robust detector and prefilter should not regress to that behavior.

## Long-shutter behavior

Test or preserve cases shaped like:

```text
normal
meteor A
meteor A
meteor B
meteor B
normal
```

A duplicated exposure must not be rejected merely because consecutive encoded frames are almost identical.

## Syntax smoke test

```bash
python -m py_compile meteor_detector/cli.py meteor_detector/detector.py resolve_importer/import_meteors.py
```

## Desktop UI smoke test

For changes touching `src/MeteorDetect.App` or the app build scripts:

```bash
dotnet build MeteorDetect.slnx
```

When practical, run:

```bash
tools/dev-app.sh
```

Verify that files can be added, detection can be started, progress updates appear, logs expand and auto-scroll, successful runs enter History, and the Settings tab reports the Resolve Lua importer status.

## JSON sanity checks

- `fps_num` / `fps_den` remain rational source metadata.
- event frames are integers.
- profiling appears only when requested.
- the selected algorithm is recorded in `config.detector_algorithm` and file-level `detector_algorithm`.
- the default selected algorithm is `optimized_temporal_median`.
- enabling the prefilter is still recorded in `config.fast_prefilter` and file-level `fast_prefilter`.
- per-clip mode writes one JSON payload per processed clip by default.
- combined mode still writes a single payload containing all successful files and failures.
