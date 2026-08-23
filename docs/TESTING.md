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
  -o baseline.json --no-diagnostics --profile

python -m meteor_detector.cli C2738-00.01.58.243-00.02.00.996.MP4 \
  -o fast.json --no-diagnostics --profile --fast-prefilter
```

Compare `files[0].events`.

## Long-clip validation

For a representative astronomical-night clip with known meteors:

1. run v0.4 or v0.5 without prefilter as the accuracy reference;
2. record event frame ranges;
3. run v0.5 with `--fast-prefilter`;
4. verify every known/reference event remains;
5. compare false positives;
6. compare profiler output and wall-clock runtime.

Do not tighten prefilter thresholds until this comparison has been done on multiple known-positive clips, including faint meteors.

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

## JSON sanity checks

- `fps_num` / `fps_den` remain rational source metadata.
- event frames are integers.
- profiling appears only when requested.
- enabling the prefilter is recorded in `config.fast_prefilter` and file-level `fast_prefilter`.
