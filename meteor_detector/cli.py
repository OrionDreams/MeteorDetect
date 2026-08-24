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


def timestamped_output_path(input_path: Path, timestamp: str, output_dir: Path | None = None) -> Path:
    directory = output_dir if output_dir is not None else Path()
    return directory / f"{input_path.stem}_meteors_{timestamp}.json"


def write_payload(
    out: Path,
    cfg: dict,
    results: list,
    failures: list,
    created_utc: str,
) -> None:
    payload = {
        "format": "resolve-meteor-detector",
        "format_version": 1,
        "detector_version": __version__,
        "created_utc": created_utc,
        "config": cfg,
        "files": results,
        "failures": failures,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")


def main() -> int:
    ap = argparse.ArgumentParser(description="Detect meteor-like transient streaks in night-sky video.")
    ap.add_argument("input", type=Path, help="MP4 file or directory containing MP4 files")
    ap.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Output JSON for a single file/combined mode, or output directory for multi-file per-clip mode",
    )
    ap.add_argument(
        "--output-mode",
        choices=("per-clip", "combined"),
        default="per-clip",
        help="Write one JSON per source clip by default; use combined for the legacy multi-clip JSON",
    )
    ap.add_argument("--config", type=Path, help="JSON config file; see config.example.json")
    ap.add_argument("--no-diagnostics", action="store_true", help="Do not write candidate JPEGs")
    ap.add_argument("--profile", action="store_true", help="Print stage timings/counters and include them in JSON")
    ap.add_argument(
        "--detector-algorithm",
        metavar="NAME",
        help=(
            "Detector algorithm preset: optimized_temporal_median, "
            "temporal_median_mad, temporal_median_mad_prefilter"
        ),
    )
    ap.add_argument(
        "--decoder",
        choices=("ffmpeg", "opencv"),
        help="Frame decoder backend. ffmpeg is the default and preserves the 16-bit grayscale path; opencv is experimental.",
    )
    ap.add_argument("--fast-prefilter", action="store_true",
                    help="Enable experimental cheap temporal streak prefilter before robust analysis")
    ap.add_argument("--no-fast-prefilter", action="store_true",
                    help="Disable prefilter even if enabled in the config file")
    ap.add_argument("--ignore-camera-bumps", action="store_true",
                    help="Ignore frames with an implausibly high number of meteor-like candidates")
    ap.add_argument("--no-ignore-camera-bumps", action="store_true",
                    help="Disable camera-bump candidate burst filtering even if enabled in the config file")
    ap.add_argument("--partial-output", type=Path, help="Write resumable partial progress to this JSON file")
    ap.add_argument("--resume-from", type=Path, help="Resume detection from a partial progress JSON file")
    ap.add_argument("--pause-request-file", type=Path, help="Pause after the next saved partial checkpoint if this file exists")
    args = ap.parse_args()

    if args.fast_prefilter and args.no_fast_prefilter:
        ap.error("--fast-prefilter and --no-fast-prefilter are mutually exclusive")
    if args.ignore_camera_bumps and args.no_ignore_camera_bumps:
        ap.error("--ignore-camera-bumps and --no-ignore-camera-bumps are mutually exclusive")
    if not shutil.which("ffprobe"):
        ap.error("ffprobe must be installed and available on PATH")

    from meteor_detector.detector import (
        PauseRequested,
        apply_detector_algorithm,
        load_config,
        load_scan_checkpoint,
        scan_file,
    )

    cfg = load_config(args.config)
    try:
        if args.detector_algorithm:
            apply_detector_algorithm(cfg, args.detector_algorithm)
    except ValueError as exc:
        ap.error(str(exc))
    if args.no_diagnostics:
        cfg["diagnostic_jpegs"] = False
    if args.decoder:
        cfg["decoder"] = args.decoder
    if str(cfg.get("decoder", "ffmpeg")).lower() == "ffmpeg" and not shutil.which("ffmpeg"):
        ap.error("ffmpeg must be installed and available on PATH when using --decoder ffmpeg")
    if args.fast_prefilter:
        apply_detector_algorithm(cfg, "temporal_median_mad_prefilter")
    if args.no_fast_prefilter:
        apply_detector_algorithm(cfg, "optimized_temporal_median")
    if args.ignore_camera_bumps:
        cfg["ignore_camera_bumps"] = True
    if args.no_ignore_camera_bumps:
        cfg["ignore_camera_bumps"] = False

    inp = args.input.expanduser().resolve()
    if not inp.exists():
        ap.error(f"Input does not exist: {inp}")
    if inp.is_dir():
        files = sorted([p for p in inp.iterdir() if p.is_file() and p.suffix.lower() in {".mp4", ".mov", ".m4v"}])
    else:
        files = [inp]
    if not files:
        ap.error("No supported video files found")

    print(f"Meteor Detector v{__version__}: scanning {len(files)} file(s)", file=sys.stderr)
    print(f"Detector algorithm: {cfg.get('detector_algorithm', 'optimized_temporal_median')}", file=sys.stderr)
    print(f"Decoder: {cfg.get('decoder', 'ffmpeg')}", file=sys.stderr)
    if cfg.get("fast_prefilter", False):
        print("Fast prefilter: ENABLED (experimental; validate recall on known meteors)", file=sys.stderr)
    if cfg.get("ignore_camera_bumps", False):
        print("Ignore camera bumps: ENABLED", file=sys.stderr)

    results = []
    failures = []
    written_outputs = []
    created_utc = datetime.now(timezone.utc).isoformat()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    output_arg = args.output.expanduser().resolve() if args.output is not None else None
    per_clip_output_dir = None
    combined_out = None
    if args.output_mode == "combined":
        combined_out = available_output_path(default_output_path(inp)).resolve() if output_arg is None else output_arg
    elif output_arg is not None and len(files) > 1:
        if output_arg.suffix.lower() == ".json":
            ap.error("--output must be a directory when using --output-mode per-clip with multiple input files")
        per_clip_output_dir = output_arg

    for p in files:
        print(f"Scanning {p}", file=sys.stderr)
        clip_failures = []
        resume_checkpoint = None
        analysis_start_frame = 0
        if args.resume_from is not None:
            resume_checkpoint = load_scan_checkpoint(args.resume_from.expanduser().resolve(), p)
            resume_overlap = 30
            analysis_start_frame = max(0, resume_checkpoint.frame_progress - resume_overlap)
            resume_checkpoint.candidates = [
                candidate
                for candidate in resume_checkpoint.candidates
                if candidate.frame < analysis_start_frame
            ]
            print(
                f"Resuming from partial progress at frame {resume_checkpoint.frame_progress}; "
                f"analysis restarts at frame {analysis_start_frame}",
                file=sys.stderr,
            )
        if combined_out is not None:
            diagnostic_dir = combined_out.parent
        elif output_arg is not None and len(files) == 1 and output_arg.suffix.lower() == ".json":
            diagnostic_dir = output_arg.parent
        else:
            diagnostic_dir = (per_clip_output_dir or Path()).resolve()

        try:
            file_result = scan_file(
                p,
                diagnostic_dir,
                cfg,
                profile=args.profile,
                initial_candidates=resume_checkpoint.candidates if resume_checkpoint is not None else None,
                analysis_start_frame=analysis_start_frame,
                partial_output_path=args.partial_output.expanduser().resolve() if args.partial_output is not None else None,
                pause_request_path=args.pause_request_file.expanduser().resolve() if args.pause_request_file is not None else None,
            )
            results.append(file_result)
            clip_results = [file_result]
        except PauseRequested:
            return 0
        except Exception as exc:
            print(f"ERROR: {p}: {exc}", file=sys.stderr)
            failure = {"path": str(p), "error": str(exc)}
            failures.append(failure)
            clip_failures.append(failure)
            clip_results = []

        if args.output_mode == "per-clip":
            if output_arg is not None and len(files) == 1 and output_arg.suffix.lower() == ".json":
                out = output_arg
            else:
                out = available_output_path(timestamped_output_path(p, timestamp, per_clip_output_dir)).resolve()
            write_payload(out, cfg, clip_results, clip_failures, created_utc)
            if args.partial_output is not None and clip_results:
                partial_output = args.partial_output.expanduser().resolve()
                if partial_output.exists():
                    partial_output.unlink()
            written_outputs.append(out)
            print(f"Wrote {out}", file=sys.stderr)

    if args.output_mode == "combined":
        assert combined_out is not None
        combined_out.parent.mkdir(parents=True, exist_ok=True)
        write_payload(combined_out, cfg, results, failures, created_utc)
        written_outputs.append(combined_out)
        print(f"Wrote {combined_out}", file=sys.stderr)

    print(f"Detected {sum(len(x['events']) for x in results)} event(s); failures={len(failures)}", file=sys.stderr)
    return 1 if failures and not results else 0


if __name__ == "__main__":
    raise SystemExit(main())
