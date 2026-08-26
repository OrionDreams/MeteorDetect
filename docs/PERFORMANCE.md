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

### Reading the report

The report has two sections, because they do not share a clock.

**Pipeline** stages run on the main thread and are serial, so they are shown as a share of wall
time. **Analysis** stages run inside block workers; with a pool they are summed across workers
and overlap the pipeline, so they are shown as a share of analysis time, with an
`analysis total` line giving the overlap factor against the wall clock. A factor above 1.0x
means workers were genuinely running concurrently — it is not an error. Adding the two sections
together is meaningless.

`decode_wait` is also much larger with a worker pool than without, and that is expected rather
than a regression. Sequentially the main thread pauses to analyse, which lets FFmpeg decode
ahead and hides most decode latency; with analysis offloaded the main thread does nothing but
read frames, so the figure converges on the true cost of decoding. It is the honest number, and
on 4K H.264 it lands within a few percent of the standalone decode ceiling.

### Stage meanings

`decode_wait`
: Time spent obtaining frames from FFmpeg, including decode, scaling, pipe transfer, NumPy view/copy.

`block_wait`
: Main-thread time waiting for a block worker to finish, i.e. the pool falling behind the decoder. Near zero means analysis is keeping up and decode sets the pace.

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

- exact temporal median/MAD, computed via a vectorized comparator network over uint16 stacks
  (numpy's `partition` kernel is not well vectorized for small uint16 stacks; the network is
  ~8x faster there and verified bit-exact against the partition result). With an odd sample
  count the background median is the middle sample, so it is always an exact integer and every
  `|frame - background|` fits a uint16 unchanged; the MAD therefore runs on a uint16 deviation
  stack through the same network, about 2.5x faster than partitioning a float32 stack and
  bit-exact against it. An even sample count averages the two middle samples and can land on a
  half-integer, so it keeps the float32 `np.partition` path;
- a median *selection* network rather than a full sort. Batcher's odd-even mergesort is pruned
  by backward liveness to the middle position(s), dropping every comparator that cannot
  influence the median. For the default 13 samples that is 39 comparators against the 78 of the
  odd-even transposition sort it replaced (25 samples: 300 -> 113). Each comparator is two
  full-array passes, so cost tracks comparator count. Order statistics are unchanged, so this
  is bit-exact; correctness is checked by the 0-1 principle, exhaustively for every sample
  count up to 16;
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

### Hardware decoding

Off by default. `--hw-decoder auto` (or a specific `vaapi`/`cuda`/`qsv`/`videotoolbox`/
`d3d11va`/`dxva2`) moves codec reconstruction to the GPU; `--hw-decoder-device` picks the
device when autodetection guesses wrong. Anything unavailable falls back to software with a
`[hw]` note on stderr, and the resolved decoder is recorded as `hardware_decoder` in the JSON.

Scaling deliberately stays on the CPU. H.264/HEVC reconstruction is exact per spec, so a
compliant hardware decoder returns the same samples and the decoded frames are bit-identical
to the software path — verified by hashing the whole frame stream. Scaling on the GPU as well
is faster still, but its scaler is not area-averaging: 2.4% of samples moved by more than one
8-bit level, which would change detection and is why the option is not offered.

The trade changed once the detector got fast enough to contend with software decode. Software
decode spends ~9-12 cores, and while the detector was the slow side that was free parallelism;
now it is competition for cores and memory bandwidth. On the 1800-frame 4K H.264 clip:

| Variant | fps | CPU cores |
| --- | --- | --- |
| software decode | 144 | 11.6 |
| `--hw-decoder cuda` | 150 | 2.6 |
| `--hw-decoder auto` (vaapi) | 146 | 2.7 |

So hardware decode is now marginally faster *and* about 4.4x cheaper in CPU. On earlier,
slower revisions of the detector it measured as a throughput regression, because the CPU-side
area scale loses ffmpeg's decode threading and nothing else was competing. Expect the gap to
widen with parallel detection, where those freed cores are the whole point.

Note that `-hwaccel` alone is best effort — ffmpeg silently decodes in software when the GPU
cannot handle the codec, and still exits 0. MPEG-4 part 2 does exactly this on current Intel
and NVIDIA hardware. The detector therefore probes with `-hwaccel_output_format` before
committing, so a reported `hardware_decoder` means acceleration actually happened.

### Parallel block analysis

Anchor blocks are independent, so `--workers N` analyses them on a small thread pool while the
main thread decodes. Blocks are submitted and merged in anchor order, so candidates land in the
same sequence as the sequential path and results are byte-identical — verified against the
sequential path for the default config, an even sample count, both fallback algorithms, the
prefilter, camera-bump filtering, hardware decode, and pause/resume.

**The payoff is small, and the reason is worth understanding before tuning it.** Measured on an
1800-frame 4K H.264 clip:

| Workers | fps (normal) | fps (candidate-dense) |
| --- | --- | --- |
| 1 | 158 | 50 |
| 2 | 174 | 59 |
| 3 | 171 | 63 |
| 4 | 169 | 65 |
| 8 | 165 | 62 |

About 1.1x normally and 1.3x on candidate-dense footage, peaking at 2-4 workers and going
backwards above that. `worker_threads: 0` therefore auto-selects at most 3.

Two things cap it. Block analysis streams large buffers and saturates memory bandwidth rather
than cores; and on candidate-dense frames the per-component geometry loop is Python-level, so
it holds the GIL and does not parallelise at all. An isolated benchmark of block analysis
suggests ~2.5x, which does not survive contact with the full pipeline.

### The real ceiling is decode

With analysis removed entirely — just draining the decoder — this pipeline tops out at **202
fps** (software) or **182 fps** (cuda) for 4K H.264 on a 22-core machine. Current scanning
reaches 166 fps, i.e. **82-92% of that ceiling**, so at most ~1.2x remains available to any
amount of analysis optimisation.

Decoding in parallel chunks does not lift it either. Software decode already frame-threads
across ~13 cores, so extra decoder processes oversubscribe, and CUDA has a single NVDEC engine:

| Parallel decoders | software fps | cuda fps |
| --- | --- | --- |
| 1 | 206 | 173 |
| 2 | 218 | 166 |
| 4 | 188 | 140 |
| 8 | 140 | 108 |

So further throughput work should target *decode cost*, not analysis: a smaller `scan_width`,
lower-resolution or faster-decoding source material, or GPU scaling (which is not bit-exact —
see the hardware decoding section). Note that the original goal of ~100,000 frames in 10
minutes is 167 fps, which the current detector meets on this hardware.

### Parallelism (further options)

Parallelism can help, but should follow single-process profiling.

- Multiple independent video files: straightforward process-level parallelism.
- One long file: possible chunk-level multiprocessing with temporal overlap at chunk boundaries.
- Avoid Python threads as the primary architecture.
- Chunk workers may contend for H.264 decode resources, memory bandwidth and storage; benchmark rather than assume linear scaling.

### GPU

Not part of the baseline roadmap. The user wants a portable CPU mode suitable for everyone regardless of GPU vendor. Optional GPU acceleration may be investigated only later.

## Development sample profile

On the short known-positive clip inside the development environment, v0.5 baseline and prefilter both retained the one event at frames 29–31. The short clip is too small for representative throughput conclusions, but it verifies basic correctness of the prefilter path.
