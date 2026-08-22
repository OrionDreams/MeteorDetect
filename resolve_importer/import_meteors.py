#!/usr/bin/env python3
"""Import meteor detections as Pink *clip markers* in the current Resolve timeline.

Designed for DaVinci Resolve Studio 21.0.4 on Linux, while using only longstanding
scripting calls. Run externally with Resolve open:

    python import_meteors.py /path/to/meteors.json

It can also be installed as a Resolve Workspace script. In that mode, set
METEOR_JSON=/path/to/meteors.json or put meteors.json in your home directory.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

MARKER_COLOR = "Pink"
MARKER_NAME = "Meteor"
CUSTOM_PREFIX = "resolve-meteor-detector:"


def _import_resolve_module():
    try:
        import DaVinciResolveScript as dvr_script  # type: ignore
        return dvr_script
    except ImportError:
        candidates = [
            os.environ.get("RESOLVE_SCRIPT_API"),
            "/opt/resolve/Developer/Scripting",
            "/opt/resolve/Developer/Scripting/Modules",
        ]
        for base in candidates:
            if not base:
                continue
            p = Path(base)
            module_dir = p / "Modules" if (p / "Modules").is_dir() else p
            if module_dir.is_dir() and str(module_dir) not in sys.path:
                sys.path.insert(0, str(module_dir))
        try:
            import DaVinciResolveScript as dvr_script  # type: ignore
            return dvr_script
        except ImportError as exc:
            raise RuntimeError(
                "Could not import DaVinciResolveScript. On a normal Linux install, set:\n"
                "  export RESOLVE_SCRIPT_API=/opt/resolve/Developer/Scripting\n"
                "  export RESOLVE_SCRIPT_LIB=/opt/resolve/libs/Fusion/fusionscript.so\n"
                "  export PYTHONPATH=\"$PYTHONPATH:$RESOLVE_SCRIPT_API/Modules\""
            ) from exc


def _json_path() -> Path:
    if len(sys.argv) >= 2 and not sys.argv[1].startswith("-"):
        return Path(sys.argv[1]).expanduser().resolve()
    env = os.environ.get("METEOR_JSON")
    if env:
        return Path(env).expanduser().resolve()
    return Path.home() / "meteors.json"


def _norm_name(s: str) -> str:
    return Path(s or "").name.casefold()


def _clip_filename(item) -> str:
    mpi = item.GetMediaPoolItem()
    if not mpi:
        return ""
    # File Path is the most reliable property when available. Fall back to clip name.
    try:
        props = mpi.GetClipProperty() or {}
    except Exception:
        props = {}
    for key in ("File Path", "FilePath", "Filename", "File Name"):
        if props.get(key):
            return Path(str(props[key])).name
    try:
        name = mpi.GetName()
        if name:
            return str(name)
    except Exception:
        pass
    try:
        return str(item.GetName() or "")
    except Exception:
        return ""


def _existing_custom_data(item) -> set[str]:
    found: set[str] = set()
    try:
        markers = item.GetMarkers() or {}
    except Exception:
        markers = {}
    for info in markers.values():
        if isinstance(info, dict):
            c = info.get("customData") or info.get("customdata")
            if c:
                found.add(str(c))
    return found


def _source_range(item) -> tuple[int, int] | None:
    """Return inclusive source-relative frame range represented by this timeline item.

    Resolve TimelineItem marker frame IDs are source-relative. GetLeftOffset() is the
    source offset at the visible beginning of the edit. This also lets us skip detections
    that were trimmed out of a timeline instance.
    """
    try:
        left = int(round(float(item.GetLeftOffset())))
        duration = int(round(float(item.GetDuration())))
        if duration <= 0:
            return None
        return left, left + duration - 1
    except Exception:
        return None


def _frame_mode() -> str:
    mode = os.environ.get("METEOR_FRAME_MODE", "source").strip().lower()
    for arg in sys.argv[2:]:
        if arg.startswith("--frame-mode="):
            mode = arg.split("=", 1)[1].strip().lower()
    if mode not in {"source", "clip-relative"}:
        raise RuntimeError("METEOR_FRAME_MODE/--frame-mode must be source or clip-relative")
    return mode


def main() -> int:
    jpath = _json_path()
    frame_mode = _frame_mode()
    if not jpath.exists():
        print(f"Meteor JSON not found: {jpath}")
        print("Pass it as argv[1], set METEOR_JSON, or copy it to ~/meteors.json")
        return 2
    with jpath.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if data.get("format") != "resolve-meteor-detector":
        raise RuntimeError("Not a resolve-meteor-detector JSON file")

    detections: dict[str, dict[str, Any]] = {}
    duplicates: set[str] = set()
    for fdata in data.get("files", []):
        name = _norm_name(str(fdata.get("filename", "")))
        if not name:
            continue
        if name in detections:
            duplicates.add(name)
        detections[name] = fdata
    if duplicates:
        raise RuntimeError("Duplicate source filenames in JSON are ambiguous: " + ", ".join(sorted(duplicates)))

    dvr_script = _import_resolve_module()
    resolve = dvr_script.scriptapp("Resolve")
    if not resolve:
        raise RuntimeError("Could not connect to Resolve. Make sure Resolve is running and external scripting is allowed.")
    pm = resolve.GetProjectManager()
    project = pm.GetCurrentProject() if pm else None
    timeline = project.GetCurrentTimeline() if project else None
    if not timeline:
        raise RuntimeError("No current timeline is open")

    added = 0
    skipped_trim = 0
    already = 0
    unmatched: set[str] = set(detections.keys())
    matched_items = 0

    track_count = int(timeline.GetTrackCount("video") or 0)
    for track in range(1, track_count + 1):
        items = timeline.GetItemListInTrack("video", track) or []
        for item in items:
            filename = _norm_name(_clip_filename(item))
            if not filename or filename not in detections:
                continue
            matched_items += 1
            unmatched.discard(filename)
            fdata = detections[filename]
            existing = _existing_custom_data(item)
            src_range = _source_range(item)

            for event in fdata.get("events", []):
                source_frame = int(event["peak_frame"])
                if src_range is not None and not (src_range[0] <= source_frame <= src_range[1]):
                    skipped_trim += 1
                    continue
                event_id = str(event.get("id") or f"{Path(filename).stem}-{source_frame}")
                custom = CUSTOM_PREFIX + event_id
                if custom in existing:
                    already += 1
                    continue
                note = (
                    f"Detected meteor\n"
                    f"Source: {fdata.get('filename', filename)}\n"
                    f"Frames: {event.get('start_frame')}–{event.get('end_frame')}\n"
                    f"Peak frame: {source_frame}\n"
                    f"Confidence: {event.get('confidence', 'n/a')}"
                )
                # Resolve versions/workflows can be validated with either mapping. The default
                # is source-relative; clip-relative is available as an explicit fallback.
                marker_frame = source_frame
                if frame_mode == "clip-relative" and src_range is not None:
                    marker_frame = source_frame - src_range[0]
                ok = item.AddMarker(marker_frame, MARKER_COLOR, MARKER_NAME, note, 1, custom)
                if ok:
                    added += 1
                    existing.add(custom)
                else:
                    print(f"WARNING: Resolve rejected marker {event_id} on {filename} at source frame {source_frame}")

    print(f"Timeline: {timeline.GetName()}")
    print(f"Marker frame mode: {frame_mode}")
    print(f"Matched timeline clip instances: {matched_items}")
    print(f"Added Pink clip markers: {added}")
    print(f"Already present: {already}")
    print(f"Skipped because detection is outside a trimmed edit: {skipped_trim}")
    if unmatched:
        print("JSON files not present on this timeline:")
        for name in sorted(unmatched):
            print(f"  {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
