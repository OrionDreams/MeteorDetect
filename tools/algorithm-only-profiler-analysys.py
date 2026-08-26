#!/usr/bin/env python3
"""Profile the detection algorithm with decoding excluded, to find its ceiling.

Frames are decoded once into RAM, then fed to `scan_file` through the same seam the decoder
normally occupies (`iter_decoded_frames`). No codec, no scaler, no pipe remains, so what is
measured is detection alone.

This answers a question the built-in `--profile` structurally cannot. There, decode and
analysis overlap, so a slow scan cannot be attributed to either one. Here the decode ceiling
for the clip is printed alongside the analysis figures: if analysis throughput is well above
the ceiling, the decoder is the limit and optimising detection will not make scans faster.

Usage:

    python tools/algorithm-only-profiler-analysys.py INPUT.MP4
    python tools/algorithm-only-profiler-analysys.py INPUT.MP4 --workers 1,4,8
    python tools/algorithm-only-profiler-analysys.py INPUT.MP4 --config config.example.json

Memory: every frame is held at scan resolution, about 1 MB at the default 960x540, so a
1800-frame clip needs roughly 1.9 GB. Use a shorter clip when that is tight.

Single runs vary by around 10% on a loaded machine. Repeat before trusting a number, and do
not read a small difference between two runs as a real change.
"""
from __future__ import annotations

import argparse
import io
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from meteor_detector.detector import (  # noqa: E402
    _scan_dimensions,
    ffmpeg_frames,
    iter_decoded_frames,
    load_config,
    probe_video,
    scan_file,
)
import meteor_detector.detector as detector  # noqa: E402

ANALYSIS_STAGES = (
    "temporal_model",
    "residual_blur_threshold",
    "mask_morphology_components",
    "component_geometry",
    "prefilter",
    "diagnostics",
)


def parse_workers(value: str) -> list[int]:
    try:
        counts = [int(part) for part in value.split(",") if part.strip()]
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid worker list '{value}'") from exc
    if not counts or any(c < 1 for c in counts):
        raise argparse.ArgumentTypeError("worker counts must be positive integers")
    return counts


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Profile detection with decoding excluded.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("video", type=Path, help="Video file to profile")
    ap.add_argument("--config", type=Path, help="Detector config JSON, as used by the CLI")
    ap.add_argument("--workers", type=parse_workers, default=[1, 2, 3, 4, 6, 8],
                    help="Comma-separated worker counts to test (default: 1,2,3,4,6,8)")
    ap.add_argument("--scan-width", type=int, default=960,
                    help="Scan width, matching the detector's own setting (default: 960)")
    args = ap.parse_args()

    video = args.video.expanduser().resolve()
    if not video.is_file():
        ap.error(f"Input does not exist: {video}")

    info = probe_video(video)
    sw, sh = _scan_dimensions(info["width"], info["height"], args.scan_width)

    print(f"preloading {video.name} at {sw}x{sh} ...", flush=True)
    started = time.perf_counter()
    frames = list(ffmpeg_frames(video, sw, sh, "none", None))
    decode_seconds = time.perf_counter() - started
    if not frames:
        ap.error(f"No frames decoded from {video}")
    decode_ceiling = len(frames) / decode_seconds
    print(f"  {len(frames)} frames, {sum(f.nbytes for f in frames) / 1e9:.2f} GB, "
          f"decoded in {decode_seconds:.1f}s ({decode_ceiling:.1f} fps decode ceiling)\n")

    def run(workers: int):
        """Run a full scan whose frames come from RAM instead of the decoder."""
        detector.iter_decoded_frames = lambda *a, **k: iter(frames)
        try:
            cfg = load_config(args.config)
            cfg["diagnostic_jpegs"] = False
            cfg["worker_threads"] = workers
            captured, real_stderr = io.StringIO(), sys.stderr
            sys.stderr = captured
            t0 = time.perf_counter()
            result = scan_file(video, Path(video).parent, cfg, profile=True)
            wall = time.perf_counter() - t0
            sys.stderr = real_stderr
        finally:
            detector.iter_decoded_frames = iter_decoded_frames
        return wall, result

    print("analysis only, decode excluded")
    print(f"{'workers':>8} {'wall':>8} {'fps':>9} {'speedup':>9} {'concurrency':>12} {'events':>7}")
    print("-" * 60)
    baseline = None
    single = None
    for workers in args.workers:
        wall, result = run(workers)
        profile = result["profile"]
        frame_count = profile["counts"]["decoded_frames"]
        analysis = sum(float(profile["stages_seconds"].get(k, 0.0)) for k in ANALYSIS_STAGES)
        baseline = baseline or wall
        if workers == 1:
            single = (wall, profile, frame_count)
        print(f"{workers:>8} {wall:7.2f}s {frame_count / wall:9.1f} {baseline / wall:8.2f}x "
              f"{analysis / wall:11.2f}x {len(result['events']):7d}")

    if single is None:
        wall, result = run(1)
        single = (wall, result["profile"], result["profile"]["counts"]["decoded_frames"])
    wall, profile, frame_count = single

    print("\nfull stage breakdown at 1 worker (share of wall):")
    accounted = 0.0
    for name, seconds in sorted(profile["stages_seconds"].items(), key=lambda kv: -kv[1]):
        if seconds <= 0:
            continue
        print(f"  {name:32s} {seconds:9.3f}s  {100 * seconds / wall:5.1f}%  "
              f"{1000 * seconds / frame_count:7.3f} ms/frame")
        accounted += seconds
    print(f"  {'--- sum of stages':32s} {accounted:9.3f}s  {100 * accounted / wall:5.1f}%")
    print(f"  {'wall':32s} {wall:9.3f}s  -> {frame_count / wall:.1f} fps")

    print(f"\ndecode ceiling for this clip: {decode_ceiling:.1f} fps")
    print("Analysis well above that means the decoder is the bottleneck, not the algorithm.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
