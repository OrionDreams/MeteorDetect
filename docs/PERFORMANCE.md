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
python -m meteor_detector.cli INPUT.MP4 -o optimized.json --no-diagnostics --profile
```

If the optimized default misses a meteor, compare with the original slower baseline:

```bash
python -m meteor_detector.cli INPUT.MP4 -o original-baseline.json --no-diagnostics --profile --detector-algorithm temporal_median_mad
```

The Fast Prefilter path can still be profiled, but it is not recommended for normal
processing because it missed real meteors on longer validation footage:

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
: Stack creation or scratch-buffer reuse, temporal median, MAD, sigma floor and sigma blur.

`residual_blur_threshold`
: Per-frame positive residual, Gaussian blur and local threshold mask.

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

For a useful prefilter on astronomical-night footage, `deep_blocks_skipped` should be substantial while known meteors remain present. Current validation does not meet that bar, so the prefilter should remain experimental.

## Optimization candidates after profiling

Do not implement all of these at once. Measure first.

### Low-risk deep-path optimizations

1. Reuse preallocated residual/work/mask buffers where OpenCV/NumPy allow it cleanly.
2. Avoid repeated kernel allocation for morphology.
3. Test cheaper equivalent blur operations only against known-positive regression clips.

Already applied in `optimized_temporal_median`:

- exact temporal median/MAD, computed via `np.partition` for the float32 MAD stack and via a
  vectorized odd-even transposition sort network for the uint16 background stack (numpy's
  `partition` kernel is not well vectorized for small uint16 stacks; the sort network is ~8x
  faster there and verified bit-exact against the partition result);
- reusable temporal model scratch buffers;
- precomputed local threshold map per temporal model;
- no full-frame `z` temporary during candidate extraction.

### Temporal model optimizations

1. Increase `temporal_model_stride` only after recall testing.
2. Investigate approximate median/MAD methods.
3. Investigate rolling statistics that exploit overlap between neighboring model windows.
4. Consider bounded 10-bit histogram/order-statistic methods if profiling shows median/MAD remains dominant.

`optimized_temporal_median` currently keeps `temporal_model_stride=8` and changes only the
robust model implementation to exact partition-based median/MAD with reusable scratch
buffers. On C2746, earlier FastDetect stride experiments missed or changed real events:
stride 16 missed the event peaking at frame 2485, while stride 12 recovered that event but
lost other baseline events and introduced a new event. Larger strides are not safe enough yet.

The older `temporal_median_mad` path remains available as a slower fallback when comparing
results or investigating a suspected missed meteor.

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
