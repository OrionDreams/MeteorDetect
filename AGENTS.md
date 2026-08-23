# AGENTS.md

Instructions for Codex and other coding agents working in this repository.

## Read first

Before changing code, read:

1. `docs/PROJECT_NOTES.md`
2. `docs/ARCHITECTURE.md`
3. `docs/TESTING.md`
4. `docs/PERFORMANCE.md` if the task concerns speed
5. `docs/CSHARP-DOTNET-AVALONIA-MVVM.md` for C#, .NET and Avalonia guidance

## Project goal

Detect meteors in long 4K night-sky videos from a stationary camera and produce source-frame detections that can be imported as Pink **clip markers** into DaVinci Resolve Studio.

The baseline must remain CPU-only and GPU-vendor-independent. Optional GPU acceleration may be explored only after the CPU architecture is stable.

## Critical behavioral invariants

Do not break these without explicit discussion:

- Source timing is based on integer **source frame numbers**, not rounded seconds.
- The target footage is exactly `24000/1001` fps in the reference setup.
- Long shutter times mean one physical camera exposure may appear in two or more encoded frames.
- Therefore **do not require motion between every adjacent frame**.
- The camera is stationary on a tripod; exploit temporal stability.
- Stationary stars, terrain, skyline and other static foreground must not become meteor events.
- Faint multi-frame meteors are important. Prefer recall over prefilter precision.
- v0.4/v0.5 deep detection achieved almost zero false positives on the user's real footage. Preserve that accuracy unless a change is explicitly experimental.
- The known-positive sample `C2738-00.01.58.243-00.02.00.996.MP4` contains exactly one meteor and should remain a regression test when the file is available.
- On the known-positive sample, the current detector reports one event at frames 29–31.
- The fast prefilter is a skip/reject optimization only. It must never be treated as the authoritative meteor classifier.
- JSON schema changes should be backward-compatible where practical.
- Resolve importer changes must continue to target clip (`TimelineItem`) markers, not only timeline-global markers.

## Performance philosophy

Measure before optimizing. Use `--profile --no-diagnostics` on representative clips.

Prioritize portable CPU optimizations:

1. eliminate redundant computation and allocations;
2. reject quiet blocks before robust analysis;
3. improve temporal-statistic reuse;
4. investigate multiprocessing/chunking only after single-process hotspots are measured;
5. do not add mandatory CUDA/ROCm/VAAPI/NVDEC dependencies.

When optimizing, compare both runtime and meteor recall against the same known-positive clips.

## Coding style

- Python 3.11+ compatible unless a strong reason requires newer syntax.
- Keep external dependencies minimal: NumPy, OpenCV, FFmpeg/ffprobe.
- Prefer explicit, readable numerical code over clever abstractions in hot loops.
- Add comments where a calculation exists for a non-obvious meteor-domain reason.
- Avoid per-frame logging other than existing coarse progress messages.
- Avoid adding large debug data to `meteors.json` by default.
- Diagnostic images are optional and must remain disableable with `--no-diagnostics`.

## Before committing an algorithm change

At minimum:

```bash
python -m py_compile meteor_detector/cli.py meteor_detector/detector.py
python -m meteor_detector.cli KNOWN_POSITIVE.MP4 -o test.json --no-diagnostics --profile
python -m meteor_detector.cli KNOWN_POSITIVE.MP4 -o test-fast.json --no-diagnostics --profile --fast-prefilter
```

Check:

- no exceptions;
- known event is still detected;
- event frame range remains sensible;
- no unexplained new events;
- profiler counters make sense;
- performance does not regress unexpectedly.

If the known-positive file is not available, document that the regression test could not be run.

## Files agents may add

Small benchmark scripts, unit tests, fixtures using synthetic arrays and additional Markdown engineering notes are welcome. Do not vendor large video files into the repository.
