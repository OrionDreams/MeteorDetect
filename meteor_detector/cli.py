#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from meteor_detector import __version__


def available_output_path(base: Path) -> Path:
    """Return base, or base with _N appended before the suffix if it already exists."""
    if not base.exists():
        return base
    for i in range(1, sys.maxsize):
        candidate = base.with_name(f"{base.stem}_{i}{base.suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"Could not find an available output path for {base}")


def default_output_path(input_path: Path) -> Path:
    return Path(f"{input_path.stem}_meteors.json")


def main() -> int:
    ap = argparse.ArgumentParser(description="Detect meteor-like transient streaks in night-sky video.")
    ap.add_argument("input", type=Path, help="MP4 file or directory containing MP4 files")
    ap.add_argument("-o", "--output", type=Path, help="Output JSON (default: <video_name>_meteors.json)")
    ap.add_argument("--config", type=Path, help="JSON config file; see config.example.json")
    ap.add_argument("--no-diagnostics", action="store_true", help="Do not write candidate JPEGs")
    ap.add_argument("--profile", action="store_true", help="Print stage timings/counters and include them in JSON")
    ap.add_argument("--fast-prefilter", action="store_true",
                    help="Enable experimental cheap temporal streak prefilter before robust analysis")
    ap.add_argument("--no-fast-prefilter", action="store_true",
                    help="Disable prefilter even if enabled in the config file")
    args = ap.parse_args()

    if args.fast_prefilter and args.no_fast_prefilter:
        ap.error("--fast-prefilter and --no-fast-prefilter are mutually exclusive")
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        ap.error("ffmpeg and ffprobe must be installed and available on PATH")

    from meteor_detector.detector import load_config, scan_file

    cfg = load_config(args.config)
    if args.no_diagnostics:
        cfg["diagnostic_jpegs"] = False
    if args.fast_prefilter:
        cfg["fast_prefilter"] = True
    if args.no_fast_prefilter:
        cfg["fast_prefilter"] = False

    inp = args.input.expanduser().resolve()
    if not inp.exists():
        ap.error(f"Input does not exist: {inp}")
    if inp.is_dir():
        files = sorted([p for p in inp.iterdir() if p.is_file() and p.suffix.lower() in {".mp4", ".mov", ".m4v"}])
    else:
        files = [inp]
    if not files:
        ap.error("No supported video files found")

    if args.output is None:
        out = available_output_path(default_output_path(inp)).resolve()
    else:
        out = args.output.expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    print(f"Meteor Detector v{__version__}: scanning {len(files)} file(s)", file=sys.stderr)
    if cfg.get("fast_prefilter", False):
        print("Fast prefilter: ENABLED (experimental; validate recall on known meteors)", file=sys.stderr)

    results = []
    failures = []
    for p in files:
        print(f"Scanning {p}", file=sys.stderr)
        try:
            results.append(scan_file(p, out.parent, cfg, profile=args.profile))
        except Exception as exc:
            print(f"ERROR: {p}: {exc}", file=sys.stderr)
            failures.append({"path": str(p), "error": str(exc)})

    payload = {
        "format": "resolve-meteor-detector",
        "format_version": 1,
        "detector_version": __version__,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "config": cfg,
        "files": results,
        "failures": failures,
    }
    with out.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")
    print(f"Wrote {out}", file=sys.stderr)
    print(f"Detected {sum(len(x['events']) for x in results)} event(s); failures={len(failures)}", file=sys.stderr)
    return 1 if failures and not results else 0


if __name__ == "__main__":
    raise SystemExit(main())
