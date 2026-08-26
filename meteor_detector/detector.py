from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import threading
import time
from collections import defaultdict, deque
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict, dataclass
from fractions import Fraction
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

import cv2
import numpy as np

from meteor_detector import __version__


PROGRESS_LOG_INTERVAL_FRAMES = 100
PARTIAL_CHECKPOINT_INTERVAL_FRAMES = 1000


DEFAULT_CONFIG: dict[str, Any] = {
    "camera_class": "sony_mirrorless",
    "decoder": "ffmpeg",
    # Off by default: hardware decode availability varies by machine, driver and codec, and
    # the portable software path is the one every user is guaranteed to get. When enabled,
    # scaling deliberately stays on the CPU so decoded frames remain bit-identical to the
    # software path; only the codec reconstruction moves to the GPU. See docs/PERFORMANCE.md.
    "hardware_decoder": "none",
    "hardware_decoder_device": None,
    # Anchor blocks are independent, so they analyse in parallel. 0 picks a small pool
    # automatically; 1 keeps the fully sequential path. Do not raise this to the core count:
    # the gain is small and caps early, and past ~4 workers throughput goes backwards.
    # See docs/PERFORMANCE.md for why the ceiling is decode, not analysis.
    "worker_threads": 0,
    "detector_algorithm": "optimized_temporal_median",
    "scan_width": 960,
    "temporal_window_frames": 25,
    "temporal_sample_stride": 2,
    "temporal_model_stride": 8,
    "local_sigma_threshold": 4.0,
    "local_noise_floor": 64.0,
    "minimum_threshold": 300.0,
    "minimum_component_area": 5,
    "maximum_component_area": 1200,
    "minimum_streak_length": 8.0,
    "minimum_elongation": 3.5,
    "maximum_streak_width": 4.5,
    "event_gap_frames": 8,
    "event_max_center_distance": 120.0,
    "event_max_angle_difference_deg": 30.0,
    "minimum_multiframe_event_frames": 2,
    "single_frame_min_streak_length": 16.0,
    "single_frame_min_elongation": 5.5,
    "single_frame_min_peak_sigma": 5.5,
    "single_frame_min_peak_signal": 700.0,
    "diagnostic_jpegs": True,
    "diagnostic_level": 1,
    "diagnostic_quality": 92,
    "include_candidates_in_json": False,
    "ignore_camera_bumps": False,
    "camera_bump_max_candidates_per_frame": 15,

    # Optional CPU-only coarse pass. It is deliberately permissive: its only job is to
    # reject obviously quiet blocks before the expensive temporal median/MAD model.
    "fast_prefilter": False,
    "prefilter_width": 480,
    "prefilter_minimum_threshold": 180.0,
    "prefilter_min_component_area": 2,
    "prefilter_max_component_area": 900,
    "prefilter_min_streak_length": 3.5,
    "prefilter_min_elongation": 1.6,
    "prefilter_max_streak_width": 10.0,
    "prefilter_margin_frames": 8,
}

CAMERA_CLASSES: dict[str, dict[str, Any]] = {
    "sony_mirrorless": {},
    "noisy_camera": {
        "local_sigma_threshold": 7.5,
        "local_noise_floor": 128.0,
        "minimum_threshold": 900.0,
        "minimum_component_area": 12,
        "minimum_streak_length": 22.0,
        "minimum_elongation": 6.0,
        "maximum_streak_width": 4.0,
        "single_frame_min_streak_length": 24.0,
        "single_frame_min_elongation": 7.0,
        "single_frame_min_peak_sigma": 8.0,
        "single_frame_min_peak_signal": 1200.0,
    },
}

CAMERA_CLASS_ALIASES: dict[str, str] = {
    "sony": "sony_mirrorless",
    "mirrorless": "sony_mirrorless",
    "noisy": "noisy_camera",
    "noisy_video": "noisy_camera",
}

DETECTOR_ALGORITHMS: dict[str, dict[str, Any]] = {
    "optimized_temporal_median": {
        "fast_prefilter": False,
        "temporal_model_impl": "partition",
        "temporal_model_stride": 8,
    },
    "temporal_median_mad": {
        "fast_prefilter": False,
        "temporal_model_impl": "median",
        "temporal_model_stride": 8,
    },
    "temporal_median_mad_prefilter": {
        "fast_prefilter": True,
        "temporal_model_impl": "median",
        "temporal_model_stride": 8,
    },
}

DETECTOR_ALGORITHM_ALIASES: dict[str, str] = {
    "fastdetect_experimental": "optimized_temporal_median",
}


@dataclass
class Candidate:
    frame: int
    x: int
    y: int
    w: int
    h: int
    area: int
    cx: float
    cy: float
    length: float
    width: float
    elongation: float
    angle_deg: float
    mean_signal: float
    peak_signal: float
    peak_sigma: float


@dataclass
class Event:
    id: str
    start_frame: int
    end_frame: int
    peak_frame: int
    video_frame_count: int
    confidence: float
    peak_signal: float
    peak_sigma: float
    max_streak_length_scan_px: float
    max_area_scan_px: int
    candidate_count: int
    candidates: list[dict[str, Any]] | None = None


@dataclass
class ScanCheckpoint:
    frame_progress: int
    candidates: list[Candidate]


@dataclass
class CandidateDetection:
    candidates: list[Candidate]
    threshold: float
    residual: np.ndarray | None = None
    blurred_residual: np.ndarray | None = None
    threshold_mask: np.ndarray | None = None


@dataclass
class PauseRequested(Exception):
    frame_progress: int
    partial_output_path: Path


class TemporalModelScratch:
    def __init__(self, sample_count: int, height: int, width: int) -> None:
        frame_shape = (height, width)
        self.background = np.empty(frame_shape, dtype=np.float32)
        self.sigma = np.empty(frame_shape, dtype=np.float32)
        self.sigma_blur = np.empty(frame_shape, dtype=np.float32)
        self.signal_threshold = np.empty(frame_shape, dtype=np.float32)
        # One extra buffer beyond sample_count acts as the selection network's rotating spare slot.
        self.selection_pool = [np.empty(frame_shape, dtype=np.uint16) for _ in range(sample_count + 1)]

        # An odd sample count takes the middle sample as the median, so the temporal background
        # is always an exact integer and every |frame - background| fits a uint16 unchanged. The
        # deviation stack can then stay in uint16 and reuse the selection network, which is much
        # faster than partitioning a float32 stack. An even count averages the two middle
        # samples and can land on a half-integer, so that case keeps the float32 stack.
        self.integer_medians = sample_count % 2 == 1
        if self.integer_medians:
            self.background_u16 = np.empty(frame_shape, dtype=np.uint16)
            self.deviation_pool = [np.empty(frame_shape, dtype=np.uint16) for _ in range(sample_count + 1)]
            self.stack_f32 = None
        else:
            self.background_u16 = None
            self.deviation_pool = None
            self.stack_f32 = np.empty((sample_count, height, width), dtype=np.float32)


class Profiler:
    """Very small wall-clock profiler used for optimization work.

    Timings are intentionally inclusive from the application's point of view. In particular,
    `decode_wait` measures time spent asking the FFmpeg generator for the next frame, which
    includes pipe waiting, raw-frame conversion and the copy into the detector's frame buffer.
    """

    def __init__(self, enabled: bool = False) -> None:
        self.enabled = enabled
        self.seconds: defaultdict[str, float] = defaultdict(float)
        self.counts: defaultdict[str, int] = defaultdict(int)
        self.started = time.perf_counter()
        # Analysis stages are collected per worker and summed, so with a pool their total
        # overlaps the main thread's wall clock and can exceed it. Recorded so the report can
        # use the right denominator instead of showing percentages that add up past 100%.
        self.worker_threads = 1

    def add_time(self, name: str, seconds: float) -> None:
        if self.enabled:
            self.seconds[name] += seconds

    def inc(self, name: str, value: int = 1) -> None:
        if self.enabled:
            self.counts[name] += value

    def snapshot(self) -> dict[str, Any]:
        total = time.perf_counter() - self.started
        stages = {k: round(v, 6) for k, v in sorted(self.seconds.items())}
        return {
            "total_seconds": round(total, 6),
            "worker_threads": self.worker_threads,
            "stages_seconds": stages,
            "counts": dict(sorted(self.counts.items())),
        }


def _run_json(cmd: list[str]) -> dict[str, Any]:
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"Command failed ({p.returncode}): {' '.join(cmd)}\n{p.stderr}")
    return json.loads(p.stdout)


def _parse_rate(value: Any) -> Fraction | None:
    text = str(value or "")
    if not text or text == "0/0":
        return None
    try:
        rate = Fraction(text)
    except (ValueError, ZeroDivisionError):
        return None
    return rate if rate > 0 else None


def _metadata_frame_rates(stream: dict[str, Any]) -> tuple[Fraction, Fraction | None, Fraction | None]:
    avg = _parse_rate(stream.get("avg_frame_rate"))
    nominal = _parse_rate(stream.get("r_frame_rate"))
    selected = avg or nominal
    if selected is None:
        raise RuntimeError("Video stream does not report a usable frame rate")
    if avg is not None and nominal is not None:
        ratio = float(avg / nominal)
        if ratio < 0.8 or ratio > 1.25:
            selected = nominal
    return selected, avg, nominal


def _count_video_packets(path: Path) -> int | None:
    try:
        data = _run_json([
            "ffprobe", "-v", "error", "-count_packets", "-select_streams", "v:0",
            "-show_entries", "stream=nb_read_packets", "-of", "json", str(path),
        ])
    except Exception:
        return None
    streams = data.get("streams", [])
    if not streams:
        return None
    value = streams[0].get("nb_read_packets")
    return int(value) if str(value).isdigit() else None


def _estimated_frame_count(path: Path, stream: dict[str, Any], duration: float, selected_fps: Fraction) -> int | None:
    nb_frames = None
    if str(stream.get("nb_frames", "")).isdigit():
        nb_frames = int(stream["nb_frames"])
    if nb_frames is not None or duration <= 0:
        return nb_frames

    estimate_fps = selected_fps
    avg = _parse_rate(stream.get("avg_frame_rate"))
    nominal = _parse_rate(stream.get("r_frame_rate"))
    if avg is not None and nominal is not None:
        ratio = float(avg / nominal)
        if ratio < 0.8 or ratio > 1.25:
            return _count_video_packets(path) or int(round(duration * float(nominal)))
    return int(round(duration * float(estimate_fps)))


def probe_video(path: Path) -> dict[str, Any]:
    data = _run_json([
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries",
        "stream=codec_name,width,height,pix_fmt,r_frame_rate,avg_frame_rate,time_base,nb_frames,duration:stream_tags=rotate:stream_side_data",
        "-of", "json", str(path),
    ])
    streams = data.get("streams", [])
    if not streams:
        raise RuntimeError(f"No video stream found in {path}")
    s = streams[0]
    fps, avg_fps, nominal_fps = _metadata_frame_rates(s)
    rotation = 0
    tags = s.get("tags") or {}
    if "rotate" in tags:
        try:
            rotation = int(round(float(tags["rotate"]))) % 360
        except Exception:
            pass
    for side in s.get("side_data_list", []) or []:
        if "rotation" in side:
            try:
                rotation = int(round(float(side["rotation"]))) % 360
            except Exception:
                pass
    duration = float(s.get("duration") or 0.0)
    nb_frames = _estimated_frame_count(path, s, duration, fps)
    return {
        "codec_name": s.get("codec_name"),
        "width": int(s["width"]),
        "height": int(s["height"]),
        "pix_fmt": s.get("pix_fmt"),
        "fps_num": fps.numerator,
        "fps_den": fps.denominator,
        "avg_frame_rate": str(avg_fps) if avg_fps is not None else None,
        "r_frame_rate": str(nominal_fps) if nominal_fps is not None else None,
        "time_base": s.get("time_base"),
        "rotation": rotation,
        "duration_seconds": duration,
        "estimated_frames": nb_frames,
    }


def _scan_dimensions(width: int, height: int, scan_width: int) -> tuple[int, int]:
    if width <= scan_width:
        sw, sh = width, height
    else:
        sw = scan_width
        sh = int(round(height * (scan_width / width)))
    return max(2, sw - sw % 2), max(2, sh - sh % 2)


HARDWARE_DECODER_CHOICES = ("none", "auto", "vaapi", "cuda", "qsv", "videotoolbox", "d3d11va", "dxva2")

# Tried in this order when `hardware_decoder` is "auto". Only methods ffmpeg reports as
# built in are attempted, and each is probed against the real file before being accepted.
_HARDWARE_DECODER_AUTO_ORDER = ("videotoolbox", "vaapi", "cuda", "qsv", "d3d11va", "dxva2")


def normalize_hardware_decoder(method: str | None) -> str:
    selected = str(method or "none").strip().lower()
    if selected in ("", "off", "software", "cpu"):
        selected = "none"
    if selected not in HARDWARE_DECODER_CHOICES:
        choices = ", ".join(HARDWARE_DECODER_CHOICES)
        raise ValueError(f"Unknown hardware decoder '{method}'. Choices: {choices}")
    return selected


def _hwaccel_args(method: str, device: str | None) -> list[str]:
    """FFmpeg flags for `method`, leaving frames in system memory.

    Deliberately omits `-hwaccel_output_format`, so ffmpeg downloads decoded frames and the
    CPU filter chain still performs the area-averaged downscale. That keeps output identical
    to software decoding: H.264/HEVC reconstruction is exact per spec, so a compliant
    hardware decoder returns the same samples. Scaling on the GPU would be faster still, but
    its scaler is not area-averaging and measurably shifts pixel values, which would change
    detection results.
    """
    if method == "none":
        return []
    args = ["-hwaccel", method]
    if device:
        args += ["-hwaccel_device", device]
    return args


def available_hwaccels() -> list[str]:
    try:
        p = subprocess.run(["ffmpeg", "-hide_banner", "-hwaccels"],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=30)
    except Exception:
        return []
    if p.returncode != 0:
        return []
    lines = [line.strip() for line in p.stdout.splitlines()[1:]]
    return [line for line in lines if line]


def _candidate_hw_devices(method: str, device: str | None) -> list[str | None]:
    if device:
        return [device]
    if method in ("vaapi", "qsv"):
        # ffmpeg's default render node may belong to a GPU whose driver cannot decode (a
        # discrete NVIDIA card exposes one but has no VAAPI driver), so try each in turn.
        nodes = sorted(str(p) for p in Path("/dev/dri").glob("renderD*")) if Path("/dev/dri").is_dir() else []
        return [*nodes, None] if nodes else [None]
    return [None]


# GPU surface pixel format each method decodes into, needed to force frames to stay on the
# device during probing. Values are ffmpeg's own pix_fmt names.
_HWACCEL_SURFACE_FORMAT = {
    "vaapi": "vaapi",
    "cuda": "cuda",
    "qsv": "qsv",
    "videotoolbox": "videotoolbox_vld",
    "d3d11va": "d3d11",
    "dxva2": "dxva2_vld",
}

# Tried in turn when downloading a probe frame, to cover 8-bit and 10-bit surfaces.
_HW_DOWNLOAD_FORMATS = ("nv12", "p010", "yuv420p")


def _probe_hardware_decoder(path: Path, method: str, device: str | None) -> bool:
    """Confirm this accelerator genuinely decodes this file.

    `-hwaccel` on its own is best effort: when the GPU cannot handle the codec, ffmpeg quietly
    decodes in software and still exits 0, so a permissive probe would report acceleration that
    is not happening (MPEG-4 part 2 does exactly this on current Intel and NVIDIA hardware).
    Demanding `-hwaccel_output_format` keeps frames on the device, which only succeeds under
    real hardware decode. The scan itself then runs without that flag, so frames come back to
    system memory for the bit-exact CPU downscale.

    Probing up front also matters because a decoder can initialize and then fail. Discovering
    that mid-scan would strand a partly consumed frame generator, so the fallback decision is
    made before the scan starts.
    """
    surface = _HWACCEL_SURFACE_FORMAT.get(method)
    if surface is None:
        return False
    for download_format in _HW_DOWNLOAD_FORMATS:
        cmd = ["ffmpeg", "-v", "error", "-nostdin", "-noautorotate"] + _hwaccel_args(method, device) + [
            "-hwaccel_output_format", surface, "-i", str(path),
            "-map", "0:v:0", "-an", "-sn", "-dn", "-frames:v", "2",
            "-vf", f"hwdownload,format={download_format}", "-f", "null", "-",
        ]
        try:
            p = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
        except Exception:
            continue
        if p.returncode == 0:
            return True
    return False


def resolve_hardware_decoder(
    path: Path, cfg: dict[str, Any], codec: str | None = None
) -> tuple[str, str | None]:
    """Pick a working hardware decoder, or fall back to software.

    Returns ("none", None) when disabled or when nothing usable is found, so a machine
    without the right GPU or driver still scans instead of failing.
    """
    requested = normalize_hardware_decoder(cfg.get("hardware_decoder"))
    if requested == "none":
        return "none", None
    if str(cfg.get("decoder", "ffmpeg")).lower() != "ffmpeg":
        print("[hw] hardware decoding requires --decoder ffmpeg; using software decoding",
              file=sys.stderr)
        return "none", None

    device = cfg.get("hardware_decoder_device") or None
    built_in = available_hwaccels()
    if requested == "auto":
        methods = [m for m in _HARDWARE_DECODER_AUTO_ORDER if m in built_in]
        if not methods:
            print("[hw] this ffmpeg reports no usable hardware decoders; using software decoding",
                  file=sys.stderr)
            return "none", None
    else:
        if built_in and requested not in built_in:
            print(f"[hw] ffmpeg was not built with '{requested}'; using software decoding",
                  file=sys.stderr)
            return "none", None
        methods = [requested]

    for method in methods:
        for candidate in _candidate_hw_devices(method, device):
            if _probe_hardware_decoder(path, method, candidate):
                where = f" on {candidate}" if candidate else ""
                print(f"[hw] hardware decoding enabled: {method}{where}", file=sys.stderr)
                return method, candidate

    tried = "/".join(methods)
    detail = f" (codec {codec})" if codec else ""
    print(f"[hw] no hardware decoder ({tried}) handles {path.name}{detail}; "
          f"using software decoding", file=sys.stderr)
    return "none", None


def ffmpeg_frames(
    path: Path,
    width: int,
    height: int,
    hw_method: str = "none",
    hw_device: str | None = None,
) -> Iterable[np.ndarray]:
    vf = f"scale={width}:{height}:flags=area,format=gray16le"
    cmd = [
        "ffmpeg", "-v", "error", "-nostdin", "-noautorotate",
        *_hwaccel_args(hw_method, hw_device),
        "-i", str(path),
        "-map", "0:v:0", "-an", "-sn", "-dn", "-vf", vf,
        "-f", "rawvideo", "-pix_fmt", "gray16le", "pipe:1",
    ]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.stdout is None:
        raise RuntimeError("Failed to open ffmpeg stdout")
    frame_bytes = width * height * 2
    exhausted = False
    try:
        while True:
            buf = p.stdout.read(frame_bytes)
            if not buf:
                exhausted = True
                break
            if len(buf) != frame_bytes:
                raise RuntimeError(f"Short raw frame from ffmpeg: expected {frame_bytes}, got {len(buf)}")
            yield np.frombuffer(buf, dtype="<u2").reshape((height, width)).copy()
    finally:
        if p.stdout:
            p.stdout.close()
        stderr = p.stderr.read().decode("utf-8", errors="replace") if p.stderr else ""
        rc = p.wait()
        if rc != 0 and exhausted:
            raise RuntimeError(f"ffmpeg failed ({rc}) while reading {path}:\n{stderr}")


def opencv_frames(path: Path, width: int, height: int) -> Iterable[np.ndarray]:
    cap = cv2.VideoCapture(str(path))
    if hasattr(cv2, "CAP_PROP_ORIENTATION_AUTO"):
        cap.set(cv2.CAP_PROP_ORIENTATION_AUTO, 0)
    if not cap.isOpened():
        raise RuntimeError(f"OpenCV could not open video: {path}")

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if frame.ndim == 3:
                if frame.shape[2] == 4:
                    gray = cv2.cvtColor(frame, cv2.COLOR_BGRA2GRAY)
                else:
                    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            else:
                gray = frame
            if gray.shape[1] != width or gray.shape[0] != height:
                gray = cv2.resize(gray, (width, height), interpolation=cv2.INTER_AREA)
            if gray.dtype == np.uint16:
                yield gray.copy()
            elif gray.dtype == np.uint8:
                yield (gray.astype(np.uint16) * 257)
            else:
                yield np.clip(gray, 0, np.iinfo(np.uint16).max).astype(np.uint16)
    finally:
        cap.release()


def iter_decoded_frames(
    path: Path,
    width: int,
    height: int,
    cfg: dict[str, Any],
    hw_method: str = "none",
    hw_device: str | None = None,
) -> Iterable[np.ndarray]:
    decoder = str(cfg.get("decoder", "ffmpeg")).lower()
    if decoder == "ffmpeg":
        return ffmpeg_frames(path, width, height, hw_method, hw_device)
    if decoder == "opencv":
        return opencv_frames(path, width, height)
    raise ValueError(f"Unknown decoder '{decoder}'. Choices: ffmpeg, opencv")


def apply_detector_algorithm(cfg: dict[str, Any], algorithm: str | None = None) -> None:
    selected = algorithm or str(cfg.get("detector_algorithm") or "optimized_temporal_median")
    selected = DETECTOR_ALGORITHM_ALIASES.get(selected, selected)
    if selected not in DETECTOR_ALGORITHMS:
        choices = ", ".join(sorted(DETECTOR_ALGORITHMS))
        raise ValueError(f"Unknown detector algorithm '{selected}'. Choices: {choices}")
    cfg["detector_algorithm"] = selected
    cfg.update(DETECTOR_ALGORITHMS[selected])


def normalize_camera_class(camera_class: str | None) -> str:
    selected = str(camera_class or "sony_mirrorless").strip().lower()
    selected = selected.replace(" ", "_").replace("-", "_")
    selected = CAMERA_CLASS_ALIASES.get(selected, selected)
    if selected not in CAMERA_CLASSES:
        choices = ", ".join(sorted(CAMERA_CLASSES))
        raise ValueError(f"Unknown camera class '{camera_class}'. Choices: {choices}")
    return selected


def apply_camera_class(cfg: dict[str, Any], camera_class: str | None = None) -> None:
    selected = normalize_camera_class(camera_class or str(cfg.get("camera_class") or "sony_mirrorless"))
    cfg["camera_class"] = selected
    cfg.update(CAMERA_CLASSES[selected])


def _median_axis0_exact(stack: np.ndarray) -> np.ndarray:
    count = stack.shape[0]
    mid = count // 2
    partitioned = np.partition(stack, mid, axis=0)
    if count % 2:
        return partitioned[mid].astype(np.float32, copy=False)

    lower = np.max(partitioned[:mid], axis=0).astype(np.float32, copy=False)
    upper = partitioned[mid].astype(np.float32, copy=False)
    return (lower + upper) * 0.5


def _median_axis0_exact_inplace(stack: np.ndarray, out: np.ndarray) -> np.ndarray:
    count = stack.shape[0]
    mid = count // 2
    stack.partition(mid, axis=0)
    if count % 2:
        np.copyto(out, stack[mid], casting="unsafe")
        return out

    np.max(stack[:mid], axis=0, out=out)
    out += stack[mid]
    out *= 0.5
    return out


def _robust_temporal_model_median(sampled_frames: list[np.ndarray], noise_floor: float) -> tuple[np.ndarray, np.ndarray, np.ndarray, float]:
    stack = np.stack(sampled_frames, axis=0).astype(np.float32, copy=False)
    background = np.median(stack, axis=0)
    np.subtract(stack, background[None, ...], out=stack)
    np.abs(stack, out=stack)
    mad = np.median(stack, axis=0)
    sigma = np.maximum(float(noise_floor), 1.4826 * mad).astype(np.float32, copy=False)
    sigma_blur = cv2.GaussianBlur(sigma, (3, 3), 0)
    median_sigma = float(np.median(sigma[::8, ::8]))
    return background.astype(np.float32, copy=False), sigma, sigma_blur, median_sigma


def _batcher_odd_even_mergesort(count: int) -> list[tuple[int, int]]:
    """Comparator pairs of Batcher's odd-even mergesort, valid for any `count`."""
    comparators: list[tuple[int, int]] = []
    p = 1
    while p < count:
        k = p
        while k >= 1:
            for j in range(k % p, count - k, 2 * k):
                for i in range(min(k, count - j - k)):
                    if (i + j) // (p * 2) == (i + j + k) // (p * 2):
                        comparators.append((i + j, i + j + k))
            k //= 2
        p *= 2
    return comparators


@lru_cache(maxsize=64)
def _median_selection_network(count: int) -> tuple[tuple[int, int], ...]:
    """Comparators that place the median order statistic(s) correctly, and nothing else.

    Starts from Batcher's odd-even mergesort, then drops every comparator that cannot
    influence the middle position(s) by walking the network backwards and keeping only
    comparators touching a live wire. The result is a selection network rather than a sorting
    network: positions outside the middle are left in arbitrary order, which is fine because
    only the middle is ever read.

    For the default 13 samples this is 39 comparators against the 78 of the odd-even
    transposition sort it replaces, for identical order statistics. Both middle positions are
    targeted for an even count, which needs slots[mid - 1] and slots[mid] to average.
    """
    targets = {count // 2} if count % 2 else {count // 2 - 1, count // 2}
    live = set(targets)
    kept: list[tuple[int, int]] = []
    for i, j in reversed(_batcher_odd_even_mergesort(count)):
        if i in live or j in live:
            kept.append((i, j))
            live.add(i)
            live.add(j)
    kept.reverse()
    return tuple(kept)


def _median_axis0_selection_inplace(
    slots: list[np.ndarray], spare: np.ndarray, out: np.ndarray
) -> np.ndarray:
    """Exact median across slots[0], via a median selection network.

    Yields the same per-pixel order statistics as `_median_axis0_exact_inplace`
    (same values, same casting, just reached through elementwise min/max compare-
    exchanges instead of `np.partition`). numpy's partition kernel is not well
    vectorized for small uint16 stacks, so this is substantially faster there.

    It carries both the background stack and, when the sample count is odd, the
    absolute-deviation stack behind the MAD. On a float32 stack `np.partition`
    still wins, so an even sample count keeps that path.

    Each compare-exchange is two full-array passes, so runtime tracks the comparator count
    directly; `spare` rotates through the slots so no pass allocates.
    """
    count = len(slots)
    mid = count // 2
    for i, j in _median_selection_network(count):
        x, y = slots[i], slots[j]
        np.minimum(x, y, out=spare)
        np.maximum(x, y, out=y)
        slots[i], slots[j] = spare, y
        spare = x
    if count % 2:
        np.copyto(out, slots[mid], casting="unsafe")
        return out

    np.copyto(out, slots[mid - 1], casting="unsafe")
    out += slots[mid]
    out *= 0.5
    return out


def _robust_temporal_model_partition(
    sampled_frames: list[np.ndarray],
    noise_floor: float,
    scratch: TemporalModelScratch,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, float]:
    count = len(sampled_frames)
    for i, frame in enumerate(sampled_frames):
        np.copyto(scratch.selection_pool[i], frame)

    slots = scratch.selection_pool[:count]
    spare = scratch.selection_pool[count]
    if scratch.integer_medians:
        background_u16 = _median_axis0_selection_inplace(slots, spare, scratch.background_u16)
        background = scratch.background
        np.copyto(background, background_u16)
        for i, frame in enumerate(sampled_frames):
            cv2.absdiff(frame, background_u16, dst=scratch.deviation_pool[i])
        _median_axis0_selection_inplace(
            scratch.deviation_pool[:count], scratch.deviation_pool[count], scratch.sigma
        )
    else:
        background = _median_axis0_selection_inplace(slots, spare, scratch.background)
        for i, frame in enumerate(sampled_frames):
            scratch.stack_f32[i, ...] = frame
        np.subtract(scratch.stack_f32, background[None, ...], out=scratch.stack_f32)
        np.abs(scratch.stack_f32, out=scratch.stack_f32)
        _median_axis0_exact_inplace(scratch.stack_f32, scratch.sigma)

    np.multiply(scratch.sigma, 1.4826, out=scratch.sigma)
    np.maximum(scratch.sigma, float(noise_floor), out=scratch.sigma)
    sigma_blur = cv2.GaussianBlur(scratch.sigma, (3, 3), 0, dst=scratch.sigma_blur)
    median_sigma = float(np.median(scratch.sigma[::8, ::8]))
    return background, scratch.sigma, sigma_blur, median_sigma


def _robust_temporal_model(
    sampled_frames: list[np.ndarray],
    noise_floor: float,
    impl: str,
    scratch: TemporalModelScratch | None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, float]:
    if impl == "partition":
        if scratch is None:
            raise ValueError("partition temporal model requires scratch buffers")
        return _robust_temporal_model_partition(sampled_frames, noise_floor, scratch)
    return _robust_temporal_model_median(sampled_frames, noise_floor)


def _component_geometry(xs: np.ndarray, ys: np.ndarray) -> tuple[float, float, float, float]:
    if len(xs) < 2:
        return 0.0, 1.0, 1.0, 0.0
    xf = xs.astype(np.float32)
    yf = ys.astype(np.float32)
    mx = float(np.mean(xf))
    my = float(np.mean(yf))
    dx = xf - mx
    dy = yf - my
    cxx = float(np.mean(dx * dx))
    cyy = float(np.mean(dy * dy))
    cxy = float(np.mean(dx * dy))
    trace = cxx + cyy
    disc = math.sqrt(max(0.0, (cxx - cyy) * (cxx - cyy) + 4.0 * cxy * cxy))
    lmax = max(1e-6, 0.5 * (trace + disc))
    lmin = max(1e-6, 0.5 * (trace - disc))
    major_sigma = math.sqrt(lmax)
    minor_sigma = math.sqrt(lmin)
    angle = (0.5 * math.degrees(math.atan2(2.0 * cxy, cxx - cyy))) % 180.0
    length = 4.0 * major_sigma
    width = 4.0 * minor_sigma
    elong = major_sigma / max(minor_sigma, 0.35)
    return length, width, elong, angle


def _cheap_prefilter_block(
    get_frame,
    anchor: int,
    half: int,
    block_left: int,
    block_right: int,
    scan_width: int,
    cfg: dict[str, Any],
    profiler: Profiler,
) -> bool:
    """Return True if a block deserves the expensive robust analysis.

    The two far temporal references are used as a conservative static-scene reference.
    For each target frame we keep only positive signal above BOTH references. Static stars,
    terrain and monotonic twilight changes therefore mostly cancel. Residual energy is
    accumulated across the block, which helps long-shutter meteors that repeat over multiple
    encoded frames.

    This stage is intentionally permissive. False positives cost performance; false negatives
    can lose meteors, so thresholds should be tuned for recall rather than precision.
    """
    t0 = time.perf_counter()
    pw = min(int(cfg.get("prefilter_width", 480)), scan_width)
    step = max(1, int(round(scan_width / max(1, pw))))

    # Use views when the common 960 -> 480 factor is available. That avoids a resize entirely.
    def small(index: int) -> np.ndarray:
        f = get_frame(index)
        if step > 1:
            return f[::step, ::step]
        return f

    prev_ref = small(anchor - half)
    next_ref = small(anchor + half)
    static_ref = np.maximum(prev_ref, next_ref)
    accum = np.zeros_like(static_ref, dtype=np.uint16)

    margin = max(0, int(cfg.get("prefilter_margin_frames", 0)))
    start = max(anchor - half + 1, anchor - block_left - margin)
    end = min(anchor + half - 1, anchor + block_right + margin)

    threshold = int(round(float(cfg.get("prefilter_minimum_threshold", 180.0))))
    # int32 avoids unsigned wrap. We only keep values above the cheap absolute threshold.
    for idx in range(start, end + 1):
        cur = small(idx)
        diff = cur.astype(np.int32) - static_ref.astype(np.int32)
        np.maximum(diff, 0, out=diff)
        np.minimum(diff, np.iinfo(np.uint16).max, out=diff)
        np.maximum(accum, diff.astype(np.uint16), out=accum)

    # A tiny blur makes faint narrow streaks more coherent and is cheap at ~480x270.
    work = cv2.GaussianBlur(accum, (3, 3), 0)
    mask = (work >= threshold).astype(np.uint8)
    nz = int(cv2.countNonZero(mask))
    profiler.inc("prefilter_blocks")
    if nz < int(cfg.get("prefilter_min_component_area", 2)):
        profiler.inc("prefilter_rejected_blocks")
        profiler.add_time("prefilter", time.perf_counter() - t0)
        return False

    n, labels, stats, _centroids = cv2.connectedComponentsWithStats(mask, 8)
    min_area = int(cfg.get("prefilter_min_component_area", 2))
    max_area = int(cfg.get("prefilter_max_component_area", 900))
    min_len = float(cfg.get("prefilter_min_streak_length", 3.5))
    min_elong = float(cfg.get("prefilter_min_elongation", 1.6))
    max_width = float(cfg.get("prefilter_max_streak_width", 10.0))

    passed = False
    for label in range(1, n):
        x, y, w, h, area = [int(v) for v in stats[label]]
        if area < min_area or area > max_area:
            continue
        if max(w, h) < max(3, int(math.floor(min_len))):
            continue
        ys, xs = np.where(labels[y:y+h, x:x+w] == label)
        xs = xs + x
        ys = ys + y
        length, width, elong, _angle = _component_geometry(xs, ys)
        if length >= min_len and elong >= min_elong and width <= max_width:
            passed = True
            break

    profiler.inc("prefilter_passed_blocks" if passed else "prefilter_rejected_blocks")
    profiler.add_time("prefilter", time.perf_counter() - t0)
    return passed


def find_candidates(
    center: np.ndarray,
    background: np.ndarray,
    sigma_blur: np.ndarray,
    signal_threshold: np.ndarray,
    frame_index: int,
    cfg: dict[str, Any],
    profiler: Profiler,
    diagnostic_level: int = 1,
) -> CandidateDetection:
    t0 = time.perf_counter()
    residual = center.astype(np.float32) - background
    np.maximum(residual, 0.0, out=residual)
    work = cv2.GaussianBlur(residual, (3, 3), 0)
    abs_threshold = float(cfg["minimum_threshold"])
    mask = (work >= signal_threshold).astype(np.uint8) * 255
    diagnostic_mask = mask.copy() if diagnostic_level >= 2 else None
    profiler.add_time("residual_blur_threshold", time.perf_counter() - t0)

    # Cheap empty-mask rejection avoids morphology and connected-components work on quiet frames.
    t1 = time.perf_counter()
    profiler.inc("analyzed_frames")
    if cv2.countNonZero(mask) < int(cfg["minimum_component_area"]):
        profiler.inc("empty_masks")
        profiler.add_time("mask_morphology_components", time.perf_counter() - t1)
        return CandidateDetection(
            [],
            abs_threshold,
            residual=residual if diagnostic_level >= 2 else None,
            blurred_residual=work if diagnostic_level >= 2 else None,
            threshold_mask=diagnostic_mask,
        )

    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((2, 2), np.uint8))
    n, labels, stats, centroids = cv2.connectedComponentsWithStats(mask, 8)
    profiler.add_time("mask_morphology_components", time.perf_counter() - t1)

    t2 = time.perf_counter()
    out: list[Candidate] = []
    min_area = int(cfg["minimum_component_area"])
    max_area = int(cfg["maximum_component_area"])
    min_len = float(cfg["minimum_streak_length"])
    min_elong = float(cfg["minimum_elongation"])
    max_width = float(cfg["maximum_streak_width"])

    for label in range(1, n):
        x, y, w, h, area = [int(v) for v in stats[label]]
        if area < min_area or area > max_area:
            continue
        if max(w, h) < max(5, int(math.ceil(min_len * 0.75))):
            continue
        ys, xs = np.where(labels[y:y+h, x:x+w] == label)
        xs = xs + x
        ys = ys + y
        length, width, elong, angle = _component_geometry(xs, ys)
        if length < min_len or elong < min_elong or width > max_width:
            continue
        values = work[ys, xs]
        sigma_values = sigma_blur[ys, xs]
        cx, cy = centroids[label]
        out.append(Candidate(
            frame=frame_index, x=x, y=y, w=w, h=h, area=area,
            cx=round(float(cx), 3), cy=round(float(cy), 3),
            length=round(length, 3), width=round(width, 3),
            elongation=round(elong, 3), angle_deg=round(angle, 3),
            mean_signal=round(float(np.mean(values)), 3),
            peak_signal=round(float(np.max(values)), 3),
            peak_sigma=round(float(np.max(values / np.maximum(sigma_values, 1.0))), 3),
        ))
    if out:
        profiler.inc("candidate_frames")
        profiler.inc("candidates", len(out))
    profiler.add_time("component_geometry", time.perf_counter() - t2)
    return CandidateDetection(
        out,
        abs_threshold,
        residual=residual if diagnostic_level >= 2 else None,
        blurred_residual=work if diagnostic_level >= 2 else None,
        threshold_mask=diagnostic_mask,
    )


@dataclass
class BlockResult:
    """What one anchor block produced. Merged back on the main thread, in submission order."""
    anchor: int
    end: int
    candidates: list[Candidate]
    last_candidate_frame: int
    seconds: dict[str, float]
    counts: dict[str, int]


class BlockContext:
    """Everything an anchor block needs that does not vary between blocks.

    Holds the per-thread temporal model scratch. Those buffers are mutated in place, so
    workers must never share one; `scratch` hands each thread its own on first use.
    """

    def __init__(
        self,
        cfg: dict[str, Any],
        sw: int,
        sh: int,
        half: int,
        sample_offsets: list[int],
        sample_count: int,
        block_left: int,
        block_right: int,
        temporal_model_impl: str,
        diagnostic_level: int,
        diag_dir: Path,
        rotation: int,
        profile: bool,
    ) -> None:
        self.cfg = cfg
        self.sw = sw
        self.sh = sh
        self.half = half
        self.sample_offsets = sample_offsets
        self.sample_count = sample_count
        self.block_left = block_left
        self.block_right = block_right
        self.temporal_model_impl = temporal_model_impl
        self.diagnostic_level = diagnostic_level
        self.diag_dir = diag_dir
        self.rotation = rotation
        self.profile = profile
        self.use_prefilter = bool(cfg.get("fast_prefilter", False))
        self.ignore_camera_bumps = bool(cfg.get("ignore_camera_bumps", False))
        self.camera_bump_max_candidates = int(cfg.get("camera_bump_max_candidates_per_frame", 15))
        self.write_diagnostics = bool(cfg.get("diagnostic_jpegs", True))
        self.diagnostic_quality = int(cfg["diagnostic_quality"])
        self.noise_floor = float(cfg["local_noise_floor"])
        self.local_sigma_threshold = float(cfg["local_sigma_threshold"])
        self.minimum_threshold = float(cfg["minimum_threshold"])
        self._local = threading.local()

    @property
    def scratch(self) -> TemporalModelScratch | None:
        if self.temporal_model_impl != "partition":
            return None
        existing = getattr(self._local, "scratch", None)
        if existing is None:
            existing = TemporalModelScratch(self.sample_count, self.sh, self.sw)
            self._local.scratch = existing
        return existing


def analyze_block(
    ctx: BlockContext,
    anchor: int,
    start: int,
    end: int,
    window: list[np.ndarray],
    window_first: int,
) -> BlockResult:
    """Build one temporal model and detect over the frames it covers.

    `window` holds frames `window_first .. window_first + len(window) - 1`, which spans the
    whole sample window, so this runs without touching the decoder's shared frame buffer.
    Timings and counters accumulate locally and are merged by the caller, so no lock is needed.
    """
    profiler = Profiler(ctx.profile)
    result = BlockResult(anchor=anchor, end=end, candidates=[], last_candidate_frame=-1,
                         seconds={}, counts={})

    def get_frame(index: int) -> np.ndarray:
        pos = index - window_first
        if pos < 0 or pos >= len(window):
            raise IndexError(
                f"frame {index} is outside block window "
                f"{window_first}..{window_first + len(window) - 1}"
            )
        return window[pos]

    def finish() -> BlockResult:
        result.seconds = dict(profiler.seconds)
        result.counts = dict(profiler.counts)
        return result

    if ctx.use_prefilter:
        passed = _cheap_prefilter_block(
            get_frame, anchor, ctx.half, ctx.block_left, ctx.block_right, ctx.sw, ctx.cfg, profiler
        )
        if not passed:
            profiler.inc("deep_blocks_skipped")
            return finish()

    scratch = ctx.scratch
    t_model = time.perf_counter()
    sampled = [get_frame(anchor + off) for off in ctx.sample_offsets]
    background, _sigma, sigma_blur, median_sigma = _robust_temporal_model(
        sampled, ctx.noise_floor, ctx.temporal_model_impl, scratch
    )
    if scratch is not None:
        signal_threshold = scratch.signal_threshold
        np.maximum(sigma_blur, 1.0, out=signal_threshold)
        np.multiply(signal_threshold, ctx.local_sigma_threshold, out=signal_threshold)
        np.maximum(signal_threshold, ctx.minimum_threshold, out=signal_threshold)
    else:
        signal_threshold = np.maximum(
            ctx.minimum_threshold,
            ctx.local_sigma_threshold * np.maximum(sigma_blur, 1.0),
        ).astype(np.float32, copy=False)
    profiler.add_time("temporal_model", time.perf_counter() - t_model)
    profiler.inc("temporal_models")

    for idx in range(start, end + 1):
        center = get_frame(idx)
        detection = find_candidates(
            center, background, sigma_blur, signal_threshold, idx,
            ctx.cfg, profiler, ctx.diagnostic_level,
        )
        cands = detection.candidates
        if cands:
            if ctx.ignore_camera_bumps and len(cands) > ctx.camera_bump_max_candidates:
                profiler.inc("camera_bump_frames")
                profiler.inc("camera_bump_candidates", len(cands))
                continue
            result.candidates.extend(cands)
            result.last_candidate_frame = max(result.last_candidate_frame, idx)
            if ctx.write_diagnostics:
                td = time.perf_counter()
                _write_diag(
                    center, detection, idx, median_sigma, sigma_blur, signal_threshold,
                    ctx.diag_dir, ctx.diagnostic_quality, ctx.rotation, ctx.diagnostic_level,
                )
                profiler.add_time("diagnostics", time.perf_counter() - td)
    return finish()


def resolve_worker_threads(cfg: dict[str, Any]) -> int:
    """Worker count for block analysis; 1 means the sequential path.

    Auto deliberately picks a very small pool. Two effects cap this work long before it
    saturates cores: block analysis streams large buffers and saturates memory bandwidth, and
    on candidate-dense frames the per-component geometry loop is Python-level and holds the
    GIL. Measured end to end, 2-4 workers is the whole win and more workers get slower.
    """
    requested = int(cfg.get("worker_threads", 0) or 0)
    if requested > 0:
        return requested
    return max(1, min(3, (os.cpu_count() or 1) - 1))


def _angle_difference(a: float, b: float) -> float:
    d = abs(a - b) % 180.0
    return min(d, 180.0 - d)


def _confidence(cands: list[Candidate]) -> float:
    if not cands:
        return 0.0
    best_len = max(c.length for c in cands)
    best_elong = max(c.elongation for c in cands)
    frames = len({c.frame for c in cands})
    score = 0.25
    score += min(0.25, max(0.0, (best_len - 5.0) / 30.0))
    score += min(0.25, max(0.0, (best_elong - 2.8) / 8.0))
    score += min(0.25, frames / 6.0)
    return round(min(0.99, score), 3)


def group_events(filename: str, candidates: list[Candidate], cfg: dict[str, Any]) -> list[Event]:
    if not candidates:
        return []
    gap = int(cfg["event_gap_frames"])
    max_dist = float(cfg["event_max_center_distance"])
    max_angle = float(cfg["event_max_angle_difference_deg"])
    include = bool(cfg.get("include_candidates_in_json", False))

    tracks: list[list[Candidate]] = []
    for cand in sorted(candidates, key=lambda c: (c.frame, -c.peak_signal)):
        best_idx = None
        best_score = None
        for idx, tr in enumerate(tracks):
            last = tr[-1]
            dt = cand.frame - last.frame
            if dt < 0 or dt > gap:
                continue
            dist = math.hypot(cand.cx - last.cx, cand.cy - last.cy)
            allowed_dist = max(max_dist, 2.5 * max(cand.length, last.length))
            if dist > allowed_dist:
                continue
            ad = _angle_difference(cand.angle_deg, last.angle_deg)
            if ad > max_angle:
                continue
            score = dist + 2.0 * ad + 5.0 * dt
            if best_score is None or score < best_score:
                best_score, best_idx = score, idx
        if best_idx is None:
            tracks.append([cand])
        else:
            tracks[best_idx].append(cand)

    stem = Path(filename).stem
    events: list[Event] = []
    for tr in tracks:
        frames = sorted({c.frame for c in tr})
        peak = max(tr, key=lambda c: c.peak_signal)
        if len(frames) < int(cfg.get("minimum_multiframe_event_frames", 2)):
            best = max(tr, key=lambda c: (c.length, c.peak_sigma, c.peak_signal))
            if not (
                best.length >= float(cfg.get("single_frame_min_streak_length", 16.0))
                and best.elongation >= float(cfg.get("single_frame_min_elongation", 5.5))
                and best.peak_sigma >= float(cfg.get("single_frame_min_peak_sigma", 5.5))
                and best.peak_signal >= float(cfg.get("single_frame_min_peak_signal", 700.0))
            ):
                continue

        events.append(Event(
            id="", start_frame=frames[0], end_frame=frames[-1], peak_frame=peak.frame,
            video_frame_count=frames[-1] - frames[0] + 1,
            confidence=_confidence(tr), peak_signal=max(c.peak_signal for c in tr),
            peak_sigma=max(c.peak_sigma for c in tr),
            max_streak_length_scan_px=max(c.length for c in tr),
            max_area_scan_px=max(c.area for c in tr), candidate_count=len(tr),
            candidates=[asdict(c) for c in tr] if include else None,
        ))
    events.sort(key=lambda e: e.peak_frame)
    for idx, ev in enumerate(events, start=1):
        ev.id = f"{stem}-{idx:06d}"
    return events


def _candidate_from_json(data: dict[str, Any]) -> Candidate:
    return Candidate(
        frame=int(data["frame"]),
        x=int(data["x"]),
        y=int(data["y"]),
        w=int(data["w"]),
        h=int(data["h"]),
        area=int(data["area"]),
        cx=float(data["cx"]),
        cy=float(data["cy"]),
        length=float(data["length"]),
        width=float(data["width"]),
        elongation=float(data["elongation"]),
        angle_deg=float(data["angle_deg"]),
        mean_signal=float(data["mean_signal"]),
        peak_signal=float(data["peak_signal"]),
        peak_sigma=float(data["peak_sigma"]),
    )


def load_scan_checkpoint(path: Path, source_path: Path) -> ScanCheckpoint:
    with path.open("r", encoding="utf-8") as f:
        payload = json.load(f)

    if not bool(payload.get("partial", False)):
        raise ValueError(f"Partial checkpoint is not marked partial: {path}")

    files = payload.get("files") or []
    if not files:
        raise ValueError(f"Partial checkpoint does not contain file metadata: {path}")

    file_result = files[0]
    checkpoint_source_text = str(file_result.get("path") or payload.get("source_path") or "")
    if not checkpoint_source_text:
        raise ValueError(f"Partial checkpoint does not identify a source video: {path}")
    if Path(checkpoint_source_text).resolve() != source_path.resolve():
        raise ValueError(f"Partial checkpoint source does not match input: {path}")

    frame_progress = int(payload.get("frame_progress", file_result.get("frame_progress", 0)))
    candidates = [_candidate_from_json(item) for item in payload.get("partial_candidates", [])]
    return ScanCheckpoint(frame_progress=frame_progress, candidates=candidates)


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")
    tmp.replace(path)


def _partial_payload(
    path: Path,
    info: dict[str, Any],
    sw: int,
    sh: int,
    cfg: dict[str, Any],
    frame_progress: int,
    candidates: list[Candidate],
    events: list[Event],
    profile_data: dict[str, Any] | None = None,
    hardware_decoder: str | None = None,
) -> dict[str, Any]:
    file_result = {
        "filename": path.name,
        "path": str(path.resolve()),
        **info,
        "decoder": str(cfg.get("decoder", "ffmpeg")),
        # The decoder actually in use, which is "none" when a requested accelerator was
        # unavailable and the scan fell back to software.
        "hardware_decoder": hardware_decoder if hardware_decoder is not None
        else normalize_hardware_decoder(cfg.get("hardware_decoder")),
        "camera_class": str(cfg.get("camera_class", "sony_mirrorless")),
        "scan_width": sw,
        "scan_height": sh,
        "detector_algorithm": str(cfg.get("detector_algorithm", "optimized_temporal_median")),
        "temporal_window_frames": int(cfg["temporal_window_frames"]),
        "temporal_sample_stride": int(cfg.get("temporal_sample_stride", 1)),
        "temporal_model_stride": int(cfg.get("temporal_model_stride", 1)),
        "fast_prefilter": bool(cfg.get("fast_prefilter", False)),
        "ignore_camera_bumps": bool(cfg.get("ignore_camera_bumps", False)),
        "diagnostic_level": int(cfg.get("diagnostic_level", 1)),
        "partial": True,
        "frame_progress": frame_progress,
        "events": [
            {k: v for k, v in asdict(e).items() if v is not None}
            for e in events
        ],
    }
    if profile_data is not None:
        file_result["profile"] = profile_data

    return {
        "format": "resolve-meteor-detector",
        "format_version": 1,
        "detector_version": __version__,
        "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "partial": True,
        "frame_progress": frame_progress,
        "source_path": str(path.resolve()),
        "config": cfg,
        "files": [file_result],
        "failures": [],
        "partial_candidates": [asdict(c) for c in candidates],
    }


def write_partial_checkpoint(
    partial_output_path: Path,
    path: Path,
    info: dict[str, Any],
    sw: int,
    sh: int,
    cfg: dict[str, Any],
    frame_progress: int,
    candidates: list[Candidate],
    events: list[Event] | None = None,
    profile_data: dict[str, Any] | None = None,
    hardware_decoder: str | None = None,
) -> None:
    events = group_events(path.name, candidates, cfg) if events is None else events
    payload = _partial_payload(path, info, sw, sh, cfg, frame_progress, candidates, events,
                               profile_data, hardware_decoder)
    _atomic_write_json(partial_output_path, payload)


def _rotate_for_display(img: np.ndarray, rotation: int) -> np.ndarray:
    r = rotation % 360
    if r == 90:
        return cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
    if r == 180:
        return cv2.rotate(img, cv2.ROTATE_180)
    if r == 270:
        return cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)
    return img


def _float_to_u8(img: np.ndarray, percentiles: tuple[float, float] = (0.5, 99.8)) -> np.ndarray:
    lo, hi = np.percentile(img, percentiles)
    if hi <= lo:
        hi = lo + 1
    return np.clip((img.astype(np.float32) - lo) * 255.0 / (hi - lo), 0, 255).astype(np.uint8)


def _write_diag_image(path: Path, img: np.ndarray, quality: int, rotation: int) -> None:
    view = _rotate_for_display(img, rotation)
    cv2.imwrite(str(path), view, [cv2.IMWRITE_JPEG_QUALITY, quality])


def _write_diag(frame_u16: np.ndarray, detection: CandidateDetection, frame_idx: int,
                noise: float, sigma_blur: np.ndarray, signal_threshold: np.ndarray,
                diag_dir: Path, quality: int, rotation: int, diagnostic_level: int) -> None:
    lo, hi = np.percentile(frame_u16, [0.5, 99.8])
    if hi <= lo:
        hi = lo + 1
    view = np.clip((frame_u16.astype(np.float32) - lo) * 255.0 / (hi - lo), 0, 255).astype(np.uint8)
    view = cv2.cvtColor(view, cv2.COLOR_GRAY2BGR)
    for c in detection.candidates:
        cv2.rectangle(view, (c.x, c.y), (c.x + c.w, c.y + c.h), (255, 255, 255), 1)
    cv2.putText(view, f"frame {frame_idx}  abs thr {detection.threshold:.0f}  model noise {noise:.1f}",
                (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1, cv2.LINE_AA)
    _write_diag_image(diag_dir / f"frame_{frame_idx:08d}.jpg", view, quality, rotation)

    if diagnostic_level < 2:
        return

    base = diag_dir / f"frame_{frame_idx:08d}"
    if detection.residual is not None:
        _write_diag_image(base.with_name(f"{base.name}_residual.jpg"),
                          _float_to_u8(detection.residual), quality, rotation)
    if detection.blurred_residual is not None:
        _write_diag_image(base.with_name(f"{base.name}_residual_blur.jpg"),
                          _float_to_u8(detection.blurred_residual), quality, rotation)
    if detection.threshold_mask is not None:
        _write_diag_image(base.with_name(f"{base.name}_threshold_mask.jpg"),
                          detection.threshold_mask, quality, rotation)

    _write_diag_image(base.with_name(f"{base.name}_sigma.jpg"),
                      _float_to_u8(sigma_blur), quality, rotation)
    _write_diag_image(base.with_name(f"{base.name}_threshold.jpg"),
                      _float_to_u8(signal_threshold), quality, rotation)

    stats = {
        "frame": frame_idx,
        "minimum_threshold": detection.threshold,
        "median_model_noise": noise,
        "candidate_count": len(detection.candidates),
        "candidates": [asdict(c) for c in detection.candidates],
    }
    with base.with_name(f"{base.name}_candidates.json").open("w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2)
        f.write("\n")


# Stages the main thread spends wall-clock time in. These are serial, so they are shown as a
# share of total runtime.
PIPELINE_STAGES = ("decode_wait", "block_wait", "event_grouping")

# Stages inside block analysis. With a worker pool these are summed across workers and overlap
# the pipeline stages, so they are shown as a share of analysis time, not of the wall clock.
ANALYSIS_STAGES = (
    "prefilter",
    "temporal_model",
    "residual_blur_threshold",
    "mask_morphology_components",
    "component_geometry",
    "diagnostics",
)


def format_profile(profile: dict[str, Any], filename: str) -> str:
    total = float(profile.get("total_seconds", 0.0))
    stages = profile.get("stages_seconds", {}) or {}
    counts = profile.get("counts", {}) or {}
    workers = int(profile.get("worker_threads", 1) or 1)
    decoded = int(counts.get("decoded_frames", 0))
    fps = decoded / total if total > 0 else 0.0
    analysis_total = sum(float(stages.get(name, 0.0)) for name in ANALYSIS_STAGES)
    lines = [
        f"Performance profile: {filename}",
        "-" * (21 + len(filename)),
        f"Frames decoded:             {decoded}",
        f"Total time:                 {total:9.3f} s",
        f"Effective throughput:       {fps:9.2f} fps",
        f"Worker threads:             {workers:9d}",
        "",
        "Pipeline (main thread, share of wall clock):",
    ]
    for name in PIPELINE_STAGES:
        value = float(stages.get(name, 0.0))
        pct = (100.0 * value / total) if total > 0 else 0.0
        lines.append(f"  {name:29s} {value:9.3f} s  {pct:5.1f}%")

    if workers > 1:
        header = f"Analysis (summed across {workers} workers, overlapping the above):"
    else:
        header = "Analysis (share of analysis time):"
    lines += ["", header]
    for name in ANALYSIS_STAGES:
        value = float(stages.get(name, 0.0))
        pct = (100.0 * value / analysis_total) if analysis_total > 0 else 0.0
        lines.append(f"  {name:29s} {value:9.3f} s  {pct:5.1f}%")
    overlap = (analysis_total / total) if total > 0 else 0.0
    lines.append(f"  {'analysis total':29s} {analysis_total:9.3f} s  {overlap:5.2f}x wall")
    lines += [
        "",
        "Counters:",
        f"  Temporal models built:    {int(counts.get('temporal_models', 0))}",
        f"  Frames analyzed deeply:   {int(counts.get('analyzed_frames', 0))}",
        f"  Empty deep masks:         {int(counts.get('empty_masks', 0))}",
        f"  Candidate frames:         {int(counts.get('candidate_frames', 0))}",
        f"  Candidates:               {int(counts.get('candidates', 0))}",
        f"  Camera bump frames:       {int(counts.get('camera_bump_frames', 0))}",
        f"  Camera bump candidates:   {int(counts.get('camera_bump_candidates', 0))}",
        f"  Prefilter blocks:         {int(counts.get('prefilter_blocks', 0))}",
        f"  Prefilter passed:         {int(counts.get('prefilter_passed_blocks', 0))}",
        f"  Prefilter rejected:       {int(counts.get('prefilter_rejected_blocks', 0))}",
        f"  Deep blocks skipped:      {int(counts.get('deep_blocks_skipped', 0))}",
        f"  Meteor events:            {int(counts.get('meteor_events', 0))}",
    ]
    return "\n".join(lines)


def scan_file(
    path: Path,
    out_dir: Path,
    cfg: dict[str, Any],
    *,
    profile: bool = False,
    initial_candidates: list[Candidate] | None = None,
    analysis_start_frame: int = 0,
    partial_output_path: Path | None = None,
    pause_request_path: Path | None = None,
    checkpoint_interval_frames: int = PARTIAL_CHECKPOINT_INTERVAL_FRAMES,
) -> dict[str, Any]:
    profiler = Profiler(profile)
    if "temporal_model_impl" not in cfg:
        apply_detector_algorithm(cfg)
    info = probe_video(path)
    sw, sh = _scan_dimensions(info["width"], info["height"], int(cfg["scan_width"]))
    diag_dir = path.parent / "meteordetect_diagnostics" / path.stem
    if cfg.get("diagnostic_jpegs", True):
        diag_dir.mkdir(parents=True, exist_ok=True)

    win = int(cfg["temporal_window_frames"])
    if win < 9:
        raise ValueError("temporal_window_frames must be >= 9")
    if win % 2 == 0:
        win += 1
    half = win // 2
    sample_stride = max(1, int(cfg.get("temporal_sample_stride", 1)))
    model_stride = max(1, int(cfg.get("temporal_model_stride", 1)))
    sample_offsets = list(range(-half, half + 1, sample_stride))
    if 0 not in sample_offsets:
        sample_offsets.append(0)
        sample_offsets.sort()
    if len(sample_offsets) < 7:
        raise ValueError("temporal_window_frames / temporal_sample_stride must yield at least 7 samples")

    estimated = info.get("estimated_frames") or 0
    analysis_start_frame = max(0, int(analysis_start_frame))
    all_candidates: list[Candidate] = list(initial_candidates or [])
    algorithm = str(cfg.get("detector_algorithm", "optimized_temporal_median"))
    decoder = str(cfg.get("decoder", "ffmpeg"))
    hw_method, hw_device = resolve_hardware_decoder(path, cfg, info.get("codec_name"))
    temporal_model_impl = str(cfg.get("temporal_model_impl", "median"))
    camera_class = str(cfg.get("camera_class", "sony_mirrorless"))
    diagnostic_level = int(cfg.get("diagnostic_level", 1))
    if diagnostic_level not in (1, 2):
        raise ValueError("diagnostic_level must be 1 or 2")
    use_prefilter = bool(cfg.get("fast_prefilter", False))
    ignore_camera_bumps = bool(cfg.get("ignore_camera_bumps", False))

    buf: deque[tuple[int, np.ndarray]] = deque()
    next_anchor = half
    processed_through = half - 1
    submitted_through = half - 1
    block_left = model_stride // 2
    block_right = model_stride - block_left - 1
    workers = max(1, resolve_worker_threads(cfg))
    profiler.worker_threads = workers
    ctx = BlockContext(
        cfg, sw, sh, half, sample_offsets, len(sample_offsets), block_left, block_right,
        temporal_model_impl, diagnostic_level, diag_dir, int(info.get("rotation", 0)), profile,
    )
    last_candidate_frame = max((candidate.frame for candidate in all_candidates), default=-1)
    next_checkpoint_frame = max(checkpoint_interval_frames, analysis_start_frame + checkpoint_interval_frames)
    if pause_request_path is not None:
        print(f"[{path.name}] pause request file: {pause_request_path}", file=sys.stderr)

    def get_frame(index: int) -> np.ndarray:
        first = buf[0][0]
        pos = index - first
        if pos < 0 or pos >= len(buf):
            raise IndexError(f"frame {index} is outside buffered range {first}..{buf[-1][0]}")
        return buf[pos][1]

    # Blocks are submitted in anchor order and merged in that same order, so candidates land in
    # exactly the sequence the sequential path produced. That matters: group_events sorts with a
    # stable sort, so input order still decides ties.
    pending: deque[tuple[int, Any]] = deque()

    def submit_anchor(anchor: int) -> None:
        nonlocal submitted_through
        start = max(half, anchor - block_left, submitted_through + 1)
        end = anchor + block_right
        submitted_through = max(submitted_through, end)
        if end < analysis_start_frame:
            pending.append((end, BlockResult(anchor, end, [], -1, {}, {})))
            return
        start = max(start, analysis_start_frame)

        # Copy the frame references the block needs. They are refcounted, so the decoder is
        # free to drop them from its buffer while a worker is still using them.
        window_first = anchor - half
        window = [get_frame(idx) for idx in range(window_first, anchor + half + 1)]
        if executor is None:
            pending.append((end, analyze_block(ctx, anchor, start, end, window, window_first)))
        else:
            pending.append((end, executor.submit(
                analyze_block, ctx, anchor, start, end, window, window_first)))

    def merge_result(end: int, result: BlockResult) -> None:
        nonlocal processed_through, last_candidate_frame
        all_candidates.extend(result.candidates)
        if result.last_candidate_frame >= 0:
            last_candidate_frame = max(last_candidate_frame, result.last_candidate_frame)
        for name, seconds in result.seconds.items():
            profiler.add_time(name, seconds)
        for name, value in result.counts.items():
            profiler.inc(name, value)
        processed_through = max(processed_through, end)

    def drain(max_inflight: int = 0) -> None:
        while len(pending) > max_inflight:
            end, item = pending.popleft()
            if isinstance(item, Future):
                # Time spent here is the pool falling behind the decoder, which is worth
                # telling apart from decoding itself.
                tw = time.perf_counter()
                item = item.result()
                profiler.add_time("block_wait", time.perf_counter() - tw)
            merge_result(end, item)
            maybe_write_checkpoint()

    def maybe_write_checkpoint() -> None:
        nonlocal next_checkpoint_frame
        if partial_output_path is None or checkpoint_interval_frames <= 0:
            return
        if processed_through < next_checkpoint_frame:
            return
        pause_requested = pause_request_path is not None and pause_request_path.exists()
        if pause_request_path is not None:
            print(
                f"[{path.name}] pause checkpoint check: frame={processed_through} "
                f"exists={pause_requested}",
                file=sys.stderr,
            )
        if not pause_requested and last_candidate_frame == processed_through:
            return

        profile_data = profiler.snapshot() if profile else None
        write_partial_checkpoint(
            partial_output_path,
            path,
            info,
            sw,
            sh,
            cfg,
            processed_through,
            all_candidates,
            profile_data=profile_data,
            hardware_decoder=hw_method,
        )
        print(f"[{path.name}] partial progress saved: frame={processed_through} path={partial_output_path}", file=sys.stderr)
        next_checkpoint_frame = processed_through + checkpoint_interval_frames

        if pause_requested:
            try:
                pause_request_path.unlink()
            except FileNotFoundError:
                pass
            print(f"[{path.name}] detection paused: frame={processed_through}", file=sys.stderr)
            raise PauseRequested(processed_through, partial_output_path)

    last_idx = -1
    last_progress_reported = 0

    def report_progress(processed_frames: int) -> None:
        nonlocal last_progress_reported
        suffix = f"/{estimated}" if estimated else ""
        print(f"[{path.name}] frame {processed_frames}{suffix}, candidates={len(all_candidates)}", file=sys.stderr)
        last_progress_reported = processed_frames

    # OpenCV parallelises inside single calls. With a worker pool on top, both layers compete
    # for the same cores, so hand the outer level the parallelism and restore the setting after.
    opencv_threads = cv2.getNumThreads()
    executor = None
    if workers > 1:
        cv2.setNumThreads(1)
        executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="meteor-block")
        print(f"[{path.name}] analysing blocks with {workers} worker threads", file=sys.stderr)
    # Keep a couple of blocks queued per worker so decoding never waits on a free slot.
    max_inflight = 0 if executor is None else workers * 2

    frames_iter = iter(iter_decoded_frames(path, sw, sh, cfg, hw_method, hw_device))
    i = 0
    try:
        while True:
            td = time.perf_counter()
            try:
                frame = next(frames_iter)
            except StopIteration:
                break
            profiler.add_time("decode_wait", time.perf_counter() - td)
            profiler.inc("decoded_frames")
            last_idx = i
            buf.append((i, frame))

            while i >= max(next_anchor + half, next_anchor + block_right):
                submit_anchor(next_anchor)
                next_anchor += model_stride
                keep_from = min(next_anchor - half, submitted_through + 1)
                while buf and buf[0][0] < keep_from:
                    buf.popleft()
                drain(max_inflight)
            decoded_frame_count = i + 1
            if decoded_frame_count % PROGRESS_LOG_INTERVAL_FRAMES == 0:
                report_progress(decoded_frame_count)
            i += 1
            maybe_write_checkpoint()

        max_target = last_idx - half
        while next_anchor <= max_target and buf and next_anchor + half <= last_idx:
            submit_anchor(next_anchor)
            next_anchor += model_stride
            drain(max_inflight)
        drain()
    finally:
        if executor is not None:
            executor.shutdown(cancel_futures=True)
        cv2.setNumThreads(opencv_threads)

    if i and i != last_progress_reported:
        report_progress(i)

    tg = time.perf_counter()
    events = group_events(path.name, all_candidates, cfg)
    profiler.add_time("event_grouping", time.perf_counter() - tg)
    profiler.inc("meteor_events", len(events))
    profile_data = profiler.snapshot() if profile else None

    result = {
        "filename": path.name,
        "path": str(path.resolve()),
        **info,
        "decoder": decoder,
        "hardware_decoder": hw_method,
        "camera_class": camera_class,
        "scan_width": sw,
        "scan_height": sh,
        "detector_algorithm": algorithm,
        "temporal_window_frames": win,
        "temporal_sample_stride": sample_stride,
        "temporal_model_stride": model_stride,
        "fast_prefilter": use_prefilter,
        "worker_threads": workers,
        "ignore_camera_bumps": ignore_camera_bumps,
        "diagnostic_level": diagnostic_level,
        "events": [
            {k: v for k, v in asdict(e).items() if v is not None}
            for e in events
        ],
    }
    if profile_data is not None:
        result["profile"] = profile_data
        print(format_profile(profile_data, path.name), file=sys.stderr)
    return result


def load_config(path: Path | None) -> dict[str, Any]:
    cfg = dict(DEFAULT_CONFIG)
    user: dict[str, Any] = {}
    if path is not None:
        with path.open("r", encoding="utf-8") as f:
            loaded = json.load(f)
        if not isinstance(loaded, dict):
            raise ValueError("Config JSON must contain an object")
        user = loaded

    apply_camera_class(cfg, user.get("camera_class", cfg.get("camera_class")))
    cfg.update(user)
    if "detector_algorithm" not in user and bool(user.get("fast_prefilter", False)):
        cfg["detector_algorithm"] = "temporal_median_mad_prefilter"
    apply_detector_algorithm(cfg)
    cfg.update(user)
    if "detector_algorithm" not in user and bool(user.get("fast_prefilter", False)):
        cfg["detector_algorithm"] = "temporal_median_mad_prefilter"
    cfg["camera_class"] = normalize_camera_class(str(cfg.get("camera_class", "sony_mirrorless")))
    cfg["detector_algorithm"] = DETECTOR_ALGORITHM_ALIASES.get(
        str(cfg.get("detector_algorithm", "optimized_temporal_median")),
        str(cfg.get("detector_algorithm", "optimized_temporal_median")),
    )
    cfg["hardware_decoder"] = normalize_hardware_decoder(cfg.get("hardware_decoder"))
    return cfg
