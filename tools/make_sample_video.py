#!/usr/bin/env python3
"""Generate a synthetic night-sky test video with a star field and fake meteor streaks.

Useful for exercising meteor_detector.cli's decode/profile pipeline when no real
astronomical footage is available. Detection recall against these clips is not
meaningful -- the streaks are not tuned to survive lossy encoding.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np


def parse_resolution(value: str) -> tuple[int, int]:
    try:
        w_str, h_str = value.lower().split("x")
        width, height = int(w_str), int(h_str)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid resolution '{value}', expected WIDTHxHEIGHT") from exc
    if width <= 0 or height <= 0:
        raise argparse.ArgumentTypeError("resolution width and height must be positive")
    return width, height


def build_star_field(
    rng: np.random.Generator, width: int, height: int, count: int
) -> tuple[np.ndarray, np.ndarray]:
    xy = rng.integers(0, [width, height], size=(count, 2))
    brightness = rng.integers(60, 180, size=count)
    return xy, brightness


def place_meteors(
    rng: np.random.Generator,
    count: int,
    width: int,
    height: int,
    n_frames: int,
    streak_frames: int,
) -> list[dict]:
    """Spread `count` meteor streaks roughly evenly across the clip, with jitter."""
    meteors: list[dict] = []
    span = n_frames - streak_frames
    if count <= 0 or span <= 0:
        return meteors

    slot = span / count
    for i in range(count):
        jitter = rng.uniform(-slot / 2, slot / 2) if count > 1 else 0.0
        start_frame = int(min(max(0, (i + 0.5) * slot + jitter), span))
        p0 = rng.uniform([0, 0], [width, height])
        p1 = rng.uniform([0, 0], [width, height])
        meteors.append({"start_frame": start_frame, "p0": p0, "p1": p1})
    return meteors


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Generate a synthetic night-sky test video with fake meteor streaks.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument("output", type=Path, nargs="?", help="Output MP4 path")
    ap.add_argument(
        "--resolution", type=parse_resolution, default=(3840, 2160),
        metavar="WIDTHxHEIGHT", help="Video resolution",
    )
    ap.add_argument("--stars", type=int, default=800, help="Number of stars in the fixed star field")
    ap.add_argument("--duration", type=float, default=3.0, help="Video length in seconds")
    ap.add_argument("--fps", type=int, default=30, help="Frames per second")
    ap.add_argument("--meteors", type=int, default=1, help="Number of fake meteor streaks to inject")
    ap.add_argument(
        "--streak-frames", type=int, default=4,
        help="Number of frames each meteor streak spans",
    )
    ap.add_argument("--seed", type=int, default=42, help="Random seed for reproducibility")
    args = ap.parse_args()

    if args.output is None:
        ap.print_help()
        return 0

    width, height = args.resolution
    n_frames = max(1, round(args.duration * args.fps))
    rng = np.random.default_rng(args.seed)

    star_xy, star_brightness = build_star_field(rng, width, height, args.stars)
    meteors = place_meteors(rng, args.meteors, width, height, n_frames, args.streak_frames)

    star_radius = max(1, width // 1920)
    streak_thickness = max(2, width // 768)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    out = cv2.VideoWriter(
        str(args.output), cv2.VideoWriter_fourcc(*"mp4v"), args.fps, (width, height), isColor=False
    )
    if not out.isOpened():
        raise RuntimeError(f"Failed to open video writer for {args.output}")

    try:
        for i in range(n_frames):
            frame = rng.integers(8, 20, size=(height, width), dtype=np.uint8)
            for (x, y), b in zip(star_xy, star_brightness):
                cv2.circle(frame, (int(x), int(y)), star_radius, int(b), -1)

            for meteor in meteors:
                offset = i - meteor["start_frame"]
                if 0 <= offset < args.streak_frames:
                    t = offset / args.streak_frames
                    p0, p1 = meteor["p0"], meteor["p1"]
                    seg0 = p0 + (p1 - p0) * t
                    seg1 = p0 + (p1 - p0) * (t + 1.0 / args.streak_frames)
                    cv2.line(
                        frame, tuple(seg0.astype(int)), tuple(seg1.astype(int)),
                        255, streak_thickness, cv2.LINE_AA,
                    )

            out.write(frame)
    finally:
        out.release()

    print(
        f"wrote {args.output} ({width}x{height}, {n_frames} frames, {args.fps} fps, "
        f"{len(meteors)} meteor(s))"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
