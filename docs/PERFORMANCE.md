# Performance and Profiling

## Current observed performance

User measurements:

- v0.3: ~5,000 frames / 30 minutes
- v0.4: ~25,000 frames / 15 minutes
- desired ballpark: ~100,000 frames / 10 minutes

The desired improvement from v0.4 is therefore roughly 6×.

## Profiling

Use:

```bash
python -m meteor_detector.cli INPUT.MP4 -o profile.json --no-diagnostics --profile
```

Then repeat with:

```bash
python -m meteor_detector.cli INPUT.MP4 -o profile-fast.json --no-diagnostics --profile --detector-algorithm temporal_median_mad_prefilter
```

Compare the exact same video.

Detector progress is intentionally coarse. The Python detector reports every 100 decoded frames and once at completion so the desktop UI can update progress without per-frame logging overhead.

### Stage meanings

`decode_wait`
: Time spent obtaining frames from FFmpeg, including decode, scaling, pipe transfer, NumPy view/copy.

`prefilter`
: Optional coarse temporal streak filtering.

`temporal_model`
: Stack creation, temporal median, MAD, sigma floor and sigma blur.

`residual_blur_threshold`
: Per-frame positive residual, Gaussian blur, sigma normalization and threshold mask.

`mask_morphology_components`
: Empty-mask test, morphological close, connected components.

`component_geometry`
: Coordinate extraction, second moments and candidate properties.

`diagnostics`
: Percentile stretch, annotation and JPEG write.

`event_grouping`
: Candidate-track grouping and event acceptance.

## Important counters

- `temporal_models`: expensive robust models actually built
- `analyzed_frames`: frames sent through the deep detector
- `empty_masks`: deep frames that produced no significant mask
- `prefilter_blocks`: coarse blocks considered
- `prefilter_passed_blocks`
- `prefilter_rejected_blocks`
- `deep_blocks_skipped`

For a useful prefilter on astronomical-night footage, `deep_blocks_skipped` should be substantial while known meteors remain present.

## Optimization candidates after profiling

Do not implement all of these at once. Measure first.

### Low-risk deep-path optimizations

1. Precompute the local threshold map per temporal model instead of dividing a full frame by `sigma_blur` every target frame.
2. Eliminate the full-frame `z` temporary; calculate peak sigma only for surviving component pixels.
3. Reuse preallocated residual/work/mask buffers where OpenCV/NumPy allow it cleanly.
4. Avoid repeated kernel allocation for morphology.
5. Test cheaper equivalent blur operations only against known-positive regression clips.

### Temporal model optimizations

1. Increase `temporal_model_stride` only after recall testing.
2. Investigate approximate median/MAD methods.
3. Investigate rolling statistics that exploit overlap between neighboring model windows.
4. Consider bounded 10-bit histogram/order-statistic methods if profiling shows median/MAD remains dominant.

### Parallelism

Parallelism can help, but should follow single-process profiling.

- Multiple independent video files: straightforward process-level parallelism.
- One long file: possible chunk-level multiprocessing with temporal overlap at chunk boundaries.
- Avoid Python threads as the primary architecture.
- Chunk workers may contend for H.264 decode resources, memory bandwidth and storage; benchmark rather than assume linear scaling.

### GPU

Not part of the baseline roadmap. The user wants a portable CPU mode suitable for everyone regardless of GPU vendor. Optional GPU acceleration may be investigated only later.

## Development sample profile

On the short known-positive clip inside the development environment, v0.5 baseline and prefilter both retained the one event at frames 29–31. The short clip is too small for representative throughput conclusions, but it verifies basic correctness of the prefilter path.
