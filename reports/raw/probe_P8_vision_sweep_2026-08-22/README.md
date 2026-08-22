# P8 vision — image-size sweep, 2026-08-22

Raw evidence for `packages/core/deepseek_harness/cache.py::estimate_image_tokens` and the anchor table in `spec/07_multimodal.md` §7.2.

## Design

5 solid-orange PNG images at 100², 200², 512², 1000², 1500². Same request template each time: user message with a single-character text prompt (`"x"`) plus the image, `max_tokens: 5`, `stream: false`, model `deepseek-v4-flash-vision-exp`. The tiny `max_tokens` and constant text keep the response cost near-zero and isolate `prompt_tokens` variation to the image alone.

## Files

- `sweep.json` — 5 rows: image edge size, HTTP status, `prompt_tokens`, `completion_tokens`, `prompt_tokens_details`.

## Headline findings

The `prompt_tokens` returned by the server for the constant text/wrapper (~13 tokens) plus one image:

| edge | `prompt_tokens` | derived image cost |
|---|---|---|
| 100 | 199 | ~186 |
| 200 | 199 | ~186 |
| 512 | 283 | ~270 |
| 1000 | 431 | ~418 |
| 1500 | 431 | **~418 (plateau)** |

**Interpretation:**
- Flat baseline **186 tokens** while long edge ≤ 512.
- Tile cost jumps in steps: baseline → 270 → 418.
- Server tile cap: 1500² and larger stay at 418.

The `estimate_image_tokens(w, h)` function in `cache.py` uses this anchor table directly (`IMAGE_TOKENS_ANCHORS = ((512, 186), (1024, 270), (2048, 418))`, plateau `IMAGE_TOKENS_PLATEAU = 418`). Tests in `packages/core/tests/test_multimodal.py::test_estimate_image_tokens_scales_beyond_baseline` pin the function output to the measured values.

## Why constants, not a live table

Cache-hit estimation must be deterministic across process starts — a live lookup could silently shift the token count and break `estimate_cache_hit` comparisons. When DeepSeek publishes an authoritative schedule, replace these constants and re-run the sweep to confirm.

## Reproduce

```bash
# Preserved probe script:
DEEPSEEK_API_KEY=sk-... python3 vision-live/sweep.py
```
