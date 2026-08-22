# Project Notes

## User / environment

Reference environment established during development:

- OS: CachyOS Linux
- DaVinci Resolve Studio: 21.0.4 Build 5
- Camera: Sony A7 IV
- Lens: Sigma 20 mm, but field-of-view calculations are intentionally out of scope for the current detector
- Camera is stationary on a tripod
- Video: 3840×2160
- Codec: H.264 High 4:2:2, about 100 Mb/s
- Pixel format from FFprobe: `yuv422p10le(pc, progressive)`
- Frame rate: exactly `24000/1001`
- Time base: `1/24000`
- Gamma: S-Log3-Cine
- Primaries: S-Gamut3-Cine
- Coding equations: Rec.709
- Typical clips: 15–90 minutes
- Sony files can contain a 90-degree display rotation and RTMD timed metadata

## Important imaging behavior

The user may record 23.976 fps with shutter times such as 1/10 s. Consequently one sensor exposure can span multiple encoded video frames. A meteor may therefore appear essentially unchanged in two consecutive frames.

Any detector that assumes `meteor == object that changes position every frame` is invalid for this project.

## Desired output

Current goal: one Pink Resolve marker per meteor.

Preferred destination: marker on the actual timeline clip (`TimelineItem`) rather than only a timeline-global marker.

Future ideas, not required for current versions:

- Small/Big marker classes
- classification from duration, brightness and illuminated pixel count
- magnitude-like scoring
- angular measurements using lens/FOV

## Architecture decision

Keep detection independent of DaVinci Resolve.

1. external Python/FFmpeg/OpenCV detector scans video;
2. detector writes `meteors.json` using source frame numbers;
3. separate Resolve Python importer matches filenames and adds clip markers.

This separation is intentional for safety, tuning and batch processing.

## Detection history

### v0.1 / v0.2

Early simple temporal/background approaches detected huge numbers of stars and foreground features. One run generated a `meteors.json` with about 236,000 lines.

Lesson: global residual thresholds and weak geometry are insufficient for this footage.

### v0.3

Per-pixel robust temporal noise normalization (median/MAD) plus stricter line morphology produced almost zero false positives and successfully detected meteors.

Major problem: speed. User observed roughly 5,000 frames in 30 minutes.

### v0.4

Reused one robust temporal model over an 8-frame block and temporally subsampled the model window. Accuracy stayed strong and speed improved to approximately 25,000 frames in 15 minutes on the user's hardware — about 100,000 frames/hour.

User's target is closer to 100,000 frames in ~10 minutes if feasible.

### v0.5

Adds profiling and an experimental coarse CPU prefilter. See `PERFORMANCE.md`.

## Real sample findings

The user supplied an original 4K sample:

`C2738-00.01.58.243-00.02.00.996.MP4`

It contains exactly one meteor.

The meteor is faint/moderate in an individual encoded frame but coherent and elongated across multiple frames. v0.4/v0.5 deep detection returns one event spanning source frames 29–31 in the supplied trimmed clip.

This is a key design finding: multi-frame line coherence is more informative than requiring a very strong individual-frame signal.

## Current optimization constraint

The user explicitly wants CPU optimization first so the software can eventually be available regardless of GPU vendor. Do not make GPU acceleration a dependency. GPU mode may be considered later as optional acceleration.

## Resolve integration direction (v0.6)

End-user Resolve integration should be an **in-Resolve Lua Utility script**, not a requirement to invoke the importer from an external Python/Distrobox environment. The detector remains external and communicates through `meteors.json`. Keep the Lua importer self-contained and dependency-free where practical; the Python importer is a debugging/reference implementation.
