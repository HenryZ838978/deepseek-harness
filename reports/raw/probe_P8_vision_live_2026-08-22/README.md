# P8 vision — live probe, 2026-08-22

Raw evidence for the `P8-multimodal-preflight` doctor probe in `packages/cli/deepseek_harness_cli/doctor_node/p8_multimodal_preflight.py` and for `spec/07_multimodal.md`. Sent against `api.deepseek.com` on 2026-08-22, one day after `@deepseek-ai/dsh` 0.1.1-rc.2 published `deepseek-v4-flash-vision-exp` in its default catalog.

## Design

Five cases, one baseline + four error exercises, all via
`POST /chat/completions`, `stream: false` (except A which streams).

| case | model | messages | expectation |
|---|---|---|---|
| A_baseline               | deepseek-v4-flash-vision-exp | user: [text + image] "describe" | 200 |
| B_image_on_assistant     | deepseek-v4-flash-vision-exp | user text, assistant: [image], user text | 400 |
| C_wrong_model_deepseek-chat | deepseek-chat                | user: [text + image] | 400 |
| D_empty_url              | deepseek-v4-flash-vision-exp | user: [text + image_url with url=""] | 400 |
| E_vl2_id                 | deepseek-vl2                 | user: [text + image] | 400 |

Image: 200×200 PNG with white text on orange background, tiny (1414 bytes source, 1888 bytes base64).

## Headline findings

**Confirmed** in `results.json`:

- **A baseline** returns 200 with `usage.prompt_tokens = 207` (image ≈ 187 tokens after wrappers), enters thinking mode automatically (40 reasoning frames, new field `completion_tokens_details.reasoning_tokens: 40`), correctly identifies text in the image.
- **B image on assistant role** → 400 "Image in assistant message is not supported" — matches `assert_multimodal_shape` invariant.
- **C wrong model** → 400 "This model does not support image" — validates P8 preflight logic.
- **D empty url** → 400 "Unsupported image_url format" — validates `assert_multimodal_shape` empty-url check.
- **E wrong model id `deepseek-vl2`** → 400 with the error listing the three legal model ids: `deepseek-v4-pro`, `deepseek-v4-flash`, `deepseek-v4-flash-vision-exp`. **Confirms the catalog in `packages/core/deepseek_harness/models.py`.**

## Reproduce

```bash
# Preserved probe script:
DEEPSEEK_API_KEY=sk-... python3 vision-live/probe.py
```

## Related

- Companion file: `../probe_P8_vision_sweep_2026-08-22/sweep.json` — 5-point image-size sweep that anchors the constants in `packages/core/deepseek_harness/cache.py::estimate_image_tokens`.
- Contract: [`spec/07_multimodal.md`](../../../spec/07_multimodal.md).
- Probe: `packages/cli/deepseek_harness_cli/doctor_node/p8_multimodal_preflight.py`.
