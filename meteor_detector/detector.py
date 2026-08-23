from __future__ import annotations

import json
import math
import subprocess
import sys
import time
from collections import defaultdict, deque
from dataclasses import asdict, dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any, Iterable

import cv2
import numpy as np


DEFAULT_CONFIG: dict[str, Any] = {
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
    "diagnostic_quality": 92,
    "include_candidates_in_json": False,

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
            "stages_seconds": stages,
            "counts": dict(sorted(self.counts.items())),
        }


def _run_json(cmd: list[str]) -> dict[str, Any]:
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"Command failed ({p.returncode}): {' '.join(cmd)}\n{p.stderr}")
    return json.loads(p.stdout)


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
    rate = s.get("avg_frame_rate") or s.get("r_frame_rate")
    fps = Fraction(rate)
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
    nb_frames = None
    if str(s.get("nb_frames", "")).isdigit():
        nb_frames = int(s["nb_frames"])
    if nb_frames is None and duration > 0:
        nb_frames = int(round(duration * float(fps)))
    return {
        "codec_name": s.get("codec_name"),
        "width": int(s["width"]),
        "height": int(s["height"]),
        "pix_fmt": s.get("pix_fmt"),
        "fps_num": fps.numerator,
        "fps_den": fps.denominator,
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


def ffmpeg_frames(path: Path, width: int, height: int) -> Iterable[np.ndarray]:
    vf = f"scale={width}:{height}:flags=area,format=gray16le"
    cmd = [
        "ffmpeg", "-v", "error", "-nostdin", "-noautorotate", "-i", str(path),
        "-map", "0:v:0", "-an", "-sn", "-dn", "-vf", vf,
        "-f", "rawvideo", "-pix_fmt", "gray16le", "pipe:1",
    ]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.stdout is None:
        raise RuntimeError("Failed to open ffmpeg stdout")
    frame_bytes = width * height * 2
    try:
        while True:
            buf = p.stdout.read(frame_bytes)
            if not buf:
                break
            if len(buf) != frame_bytes:
                raise RuntimeError(f"Short raw frame from ffmpeg: expected {frame_bytes}, got {len(buf)}")
            yield np.frombuffer(buf, dtype="<u2").reshape((height, width)).copy()
    finally:
        if p.stdout:
            p.stdout.close()
        stderr = p.stderr.read().decode("utf-8", errors="replace") if p.stderr else ""
        rc = p.wait()
        if rc != 0:
            raise RuntimeError(f"ffmpeg failed ({rc}) while reading {path}:\n{stderr}")


def _robust_temporal_model(sampled_frames: list[np.ndarray], noise_floor: float) -> tuple[np.ndarray, np.ndarray, np.ndarray, float]:
    stack = np.stack(sampled_frames, axis=0).astype(np.float32, copy=False)
    background = np.median(stack, axis=0)
    np.subtract(stack, background[None, ...], out=stack)
    np.abs(stack, out=stack)
    mad = np.median(stack, axis=0)
    sigma = np.maximum(float(noise_floor), 1.4826 * mad).astype(np.float32, copy=False)
    sigma_blur = cv2.GaussianBlur(sigma, (3, 3), 0)
    median_sigma = float(np.median(sigma[::8, ::8]))
    return background.astype(np.float32, copy=False), sigma, sigma_blur, median_sigma


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
    frame_index: int,
    cfg: dict[str, Any],
    profiler: Profiler,
) -> tuple[list[Candidate], float]:
    t0 = time.perf_counter()
    residual = center.astype(np.float32) - background
    np.maximum(residual, 0.0, out=residual)
    work = cv2.GaussianBlur(residual, (3, 3), 0)
    z = work / np.maximum(sigma_blur, 1.0)
    abs_threshold = float(cfg["minimum_threshold"])
    z_threshold = float(cfg["local_sigma_threshold"])
    mask = ((work >= abs_threshold) & (z >= z_threshold)).astype(np.uint8) * 255
    profiler.add_time("residual_blur_threshold", time.perf_counter() - t0)

    # Cheap empty-mask rejection avoids morphology and connected-components work on quiet frames.
    t1 = time.perf_counter()
    profiler.inc("analyzed_frames")
    if cv2.countNonZero(mask) < int(cfg["minimum_component_area"]):
        profiler.inc("empty_masks")
        profiler.add_time("mask_morphology_components", time.perf_counter() - t1)
        return [], abs_threshold

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
        cx, cy = centroids[label]
        out.append(Candidate(
            frame=frame_index, x=x, y=y, w=w, h=h, area=area,
            cx=round(float(cx), 3), cy=round(float(cy), 3),
            length=round(length, 3), width=round(width, 3),
            elongation=round(elong, 3), angle_deg=round(angle, 3),
            mean_signal=round(float(np.mean(values)), 3),
            peak_signal=round(float(np.max(values)), 3),
            peak_sigma=round(float(np.max(z[ys, xs])), 3),
        ))
    if out:
        profiler.inc("candidate_frames")
        profiler.inc("candidates", len(out))
    profiler.add_time("component_geometry", time.perf_counter() - t2)
    return out, abs_threshold


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


def _rotate_for_display(img: np.ndarray, rotation: int) -> np.ndarray:
    r = rotation % 360
    if r == 90:
        return cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
    if r == 180:
        return cv2.rotate(img, cv2.ROTATE_180)
    if r == 270:
        return cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)
    return img


def _write_diag(frame_u16: np.ndarray, candidates: list[Candidate], frame_idx: int,
                threshold: float, noise: float, diag_dir: Path, quality: int, rotation: int) -> None:
    lo, hi = np.percentile(frame_u16, [0.5, 99.8])
    if hi <= lo:
        hi = lo + 1
    view = np.clip((frame_u16.astype(np.float32) - lo) * 255.0 / (hi - lo), 0, 255).astype(np.uint8)
    view = cv2.cvtColor(view, cv2.COLOR_GRAY2BGR)
    for c in candidates:
        cv2.rectangle(view, (c.x, c.y), (c.x + c.w, c.y + c.h), (255, 255, 255), 1)
    cv2.putText(view, f"frame {frame_idx}  abs thr {threshold:.0f}  model noise {noise:.1f}",
                (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1, cv2.LINE_AA)
    view = _rotate_for_display(view, rotation)
    cv2.imwrite(str(diag_dir / f"frame_{frame_idx:08d}.jpg"), view,
                [cv2.IMWRITE_JPEG_QUALITY, quality])


def format_profile(profile: dict[str, Any], filename: str) -> str:
    total = float(profile.get("total_seconds", 0.0))
    stages = profile.get("stages_seconds", {}) or {}
    counts = profile.get("counts", {}) or {}
    decoded = int(counts.get("decoded_frames", 0))
    fps = decoded / total if total > 0 else 0.0
    lines = [
        f"Performance profile: {filename}",
        "-" * (21 + len(filename)),
        f"Frames decoded:             {decoded}",
        f"Total time:                 {total:9.3f} s",
        f"Effective throughput:       {fps:9.2f} fps",
        "",
        "Stage timings:",
    ]
    for name in (
        "decode_wait",
        "prefilter",
        "temporal_model",
        "residual_blur_threshold",
        "mask_morphology_components",
        "component_geometry",
        "diagnostics",
        "event_grouping",
    ):
        value = float(stages.get(name, 0.0))
        pct = (100.0 * value / total) if total > 0 else 0.0
        lines.append(f"  {name:29s} {value:9.3f} s  {pct:5.1f}%")
    lines += [
        "",
        "Counters:",
        f"  Temporal models built:    {int(counts.get('temporal_models', 0))}",
        f"  Frames analyzed deeply:   {int(counts.get('analyzed_frames', 0))}",
        f"  Empty deep masks:         {int(counts.get('empty_masks', 0))}",
        f"  Candidate frames:         {int(counts.get('candidate_frames', 0))}",
        f"  Candidates:               {int(counts.get('candidates', 0))}",
        f"  Prefilter blocks:         {int(counts.get('prefilter_blocks', 0))}",
        f"  Prefilter passed:         {int(counts.get('prefilter_passed_blocks', 0))}",
        f"  Prefilter rejected:       {int(counts.get('prefilter_rejected_blocks', 0))}",
        f"  Deep blocks skipped:      {int(counts.get('deep_blocks_skipped', 0))}",
        f"  Meteor events:            {int(counts.get('meteor_events', 0))}",
    ]
    return "\n".join(lines)


def scan_file(path: Path, out_dir: Path, cfg: dict[str, Any], *, profile: bool = False) -> dict[str, Any]:
    profiler = Profiler(profile)
    info = probe_video(path)
    sw, sh = _scan_dimensions(info["width"], info["height"], int(cfg["scan_width"]))
    diag_dir = out_dir / "diagnostics" / path.stem
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
    all_candidates: list[Candidate] = []
    use_prefilter = bool(cfg.get("fast_prefilter", False))

    buf: deque[tuple[int, np.ndarray]] = deque()
    next_anchor = half
    processed_through = half - 1
    block_left = model_stride // 2
    block_right = model_stride - block_left - 1

    def get_frame(index: int) -> np.ndarray:
        first = buf[0][0]
        pos = index - first
        if pos < 0 or pos >= len(buf):
            raise IndexError(f"frame {index} is outside buffered range {first}..{buf[-1][0]}")
        return buf[pos][1]

    def process_anchor(anchor: int) -> None:
        nonlocal processed_through
        start = max(half, anchor - block_left, processed_through + 1)
        end = anchor + block_right

        if use_prefilter:
            passed = _cheap_prefilter_block(
                get_frame, anchor, half, block_left, block_right, sw, cfg, profiler
            )
            if not passed:
                profiler.inc("deep_blocks_skipped")
                processed_through = max(processed_through, end)
                return

        t_model = time.perf_counter()
        sampled = [get_frame(anchor + off) for off in sample_offsets]
        background, _sigma, sigma_blur, median_sigma = _robust_temporal_model(
            sampled, float(cfg["local_noise_floor"])
        )
        profiler.add_time("temporal_model", time.perf_counter() - t_model)
        profiler.inc("temporal_models")

        for idx in range(start, end + 1):
            center = get_frame(idx)
            cands, threshold = find_candidates(center, background, sigma_blur, idx, cfg, profiler)
            if cands:
                all_candidates.extend(cands)
                if cfg.get("diagnostic_jpegs", True):
                    td = time.perf_counter()
                    _write_diag(center, cands, idx, threshold, median_sigma, diag_dir,
                                int(cfg["diagnostic_quality"]), int(info.get("rotation", 0)))
                    profiler.add_time("diagnostics", time.perf_counter() - td)
        processed_through = max(processed_through, end)

    last_idx = -1
    last_progress_reported = 0

    def report_progress(processed_frames: int) -> None:
        nonlocal last_progress_reported
        suffix = f"/{estimated}" if estimated else ""
        print(f"[{path.name}] frame {processed_frames}{suffix}, candidates={len(all_candidates)}", file=sys.stderr)
        last_progress_reported = processed_frames

    frames_iter = iter(ffmpeg_frames(path, sw, sh))
    i = 0
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
            process_anchor(next_anchor)
            next_anchor += model_stride
            keep_from = min(next_anchor - half, processed_through + 1)
            while buf and buf[0][0] < keep_from:
                buf.popleft()
        decoded_frames = i + 1
        if decoded_frames % 100 == 0:
            report_progress(decoded_frames)
        i += 1

    max_target = last_idx - half
    while next_anchor <= max_target and buf and next_anchor + half <= last_idx:
        process_anchor(next_anchor)
        next_anchor += model_stride

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
        "scan_width": sw,
        "scan_height": sh,
        "temporal_window_frames": win,
        "temporal_sample_stride": sample_stride,
        "temporal_model_stride": model_stride,
        "fast_prefilter": use_prefilter,
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
    if path is not None:
        with path.open("r", encoding="utf-8") as f:
            user = json.load(f)
        if not isinstance(user, dict):
            raise ValueError("Config JSON must contain an object")
        cfg.update(user)
    return cfg
