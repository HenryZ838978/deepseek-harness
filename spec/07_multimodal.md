# 07 · Multimodal (Vision) Contract

**Status.** Added 2026-08-22 in `deepseek-harness` 0.3.0 / `deepseek-harness-cli` 0.4.0. Tracks DeepSeek's vision-capable chat models, first the `deepseek-v4-flash-vision-exp` preview (`@deepseek-ai/dsh` 0.1.1-rc.2 default catalog entry, 2026-08-21), now the canonical `deepseek-flash` (V4.1 Flash, which reads images by default).

**2026-09-10 update (V4.1 Flash).** The endpoint's `GET /models` now returns exactly two ids — `deepseek-flash` and `deepseek-v4-pro` — and an unknown id is rejected with an error listing exactly those two. Sending `deepseek-v4-flash`, `deepseek-v4-flash-vision-exp`, `deepseek-reasoner`, or `deepseek-chat` returns HTTP 200 with the response `model` field set to `deepseek-flash`: the server silently re-points every legacy id. `deepseek-flash` accepts `image_url` content parts; `deepseek-v4-pro` does **not** — it accepts the request (HTTP 200) but drops the image part and charges text-only tokens, so routing images to it fails silently rather than with an error. Verified live on 2026-09-10; see `reports/raw/probe_P12_v41_flash_live_2026-09-10.jsonl`.

**RFC 2119 keywords apply.**

## Scope

This contract covers vision-capable calls to the DeepSeek chat/completions endpoint. Adapters MUST route image content via OpenAI-compatible `image_url` parts. Behaviour first observed on `deepseek-v4-flash-vision-exp` between 2026-08-21 and 2026-08-22; the canonical target is now `deepseek-flash`.

## §7.1 Message shape

Vision-bearing user messages MUST use the OpenAI content-parts shape:

```jsonc
{
  "role": "user",
  "content": [
    {"type": "text", "text": "describe:"},
    {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}
  ]
}
```

Assistant and tool messages MUST NOT carry `image_url` parts (DeepSeek's serializer rejects). See `normalize.assert_multimodal_shape` for the enforcement helper.

Data URLs of the form `data:<mediaType>;base64,<payload>` are accepted; HTTP(S) URLs are accepted only when the deployment permits egress. The Python-side harness does not fetch HTTP(S) URLs — it forwards them and lets the server dereference.

## §7.2 Image token accounting

DeepSeek charges vision tokens against `usage.prompt_tokens` and (for reasoner-capable models) reports the model's own thinking budget separately under `usage.completion_tokens_details.reasoning_tokens`.

**Measured baseline** against `api.deepseek.com` on 2026-09-10, `deepseek-flash` (V4.1 Flash), dense sweep with solid orange PNGs, `max_tokens=1` (text-only wrapper measured 32 tokens on the same prompt):

| long edge | `prompt_tokens` | derived image cost |
|---|---|---|
| ≤ 512 | 216 | 184 |
| 640 | 306 | 274 |
| 768 | 414 | 382 |
| 896 | 540 | 508 |
| 1024 | 684 | 652 |
| 1280 | 1026 | 994 |
| > 1280 | 1026 | 994 (**plateau** — server tile cap) |

The `deepseek-v4-flash-vision-exp` alias returns identical counts, so the curve is a property of the V4.1 Flash model, not the id. Raw payloads in `reports/raw/probe_P12_v41_flash_live_2026-09-10.jsonl`; the dense sweep is reproduced in [HISTORY.md](../HISTORY.md)'s 2026-09-10 entry. `estimate_image_tokens(w, h)` in this package reproduces the table with `IMAGE_TOKENS_BASELINE = 184` and `IMAGE_TOKENS_ANCHORS` at the measured edges.

> **Superseded:** the 2026-08-22 sweep on the pre-release `deepseek-v4-flash-vision-exp` measured 186 / 270 / 418. Those anchors no longer match the server — the V4.1 Flash generation roughly doubled the per-tile cost and the plateau (418 → 994). If you pinned the old constants, re-measure.

**`detail` parameter.** The OpenAI convention distinguishes `low` / `high` detail; DeepSeek's endpoint does not honour this hint and picks the tile count deterministically from image dimensions. The parameter is accepted for API parity and does not affect the returned estimate.

**Constants are pinned in code.** Cache-hit estimation MUST be reproducible across process starts; a live table lookup cannot silently move the token count. When DeepSeek publishes an authoritative per-model schedule, replace the constants in `cache.py` and re-run the sweep to confirm.

## §7.3 Prefix cache with images

**Byte-for-byte prefix rule (§4) still applies.** Multimodal prefix cache hits require that the entire image payload (data URL bytes, in order, including base64 padding) be byte-identical between requests.

Consequences:

- **Any re-encoding invalidates the cache.** A round-trip through a resize step, an EXIF strip, or a re-quantise breaks the prefix. Adapters that normalize images (as `@deepseek-ai/dsh` 0.1.1-rc.2 does via sharp) MUST document the normalization version and treat it as part of the cache key.
- **Files API references (`file_id`) create a new failure mode.** When the request cites a stored file rather than an inline data URL, cache hit depends on the file_id being byte-for-byte identical across requests. A deleted-and-re-uploaded file gets a new id; the prefix breaks. See P9-files-quota-scope in the dsh doctor.
- **Image position matters.** Moving an image up or down in the content parts list invalidates from the move point onward. Moving text around images has the same effect.

The `estimate_cache_hit` estimator canonicalises image URLs to a 12-hex placeholder (sha256 of the URL bytes) before tokenizing, so it reports meaningful prefix diffs even when actual image payloads are megabytes. This is a diagnostic aid; the server sees full bytes and enforces the byte-for-byte rule.

## §7.4 Client-side downscale is out of scope for this contract

The official Node harness (`@deepseek-ai/dsh` 0.1.1-rc.2) downscales images to a per-model pixel budget before upload. This is a policy choice, not a protocol requirement — the DeepSeek endpoint accepts the raw image at whatever resolution the client sends (subject to `maxBytes`). Callers that require full-resolution transmission SHOULD bypass any harness-level downscaler and send the raw bytes themselves, at the cost of prefix cache invalidation on any re-encode.

The Python harness (this repository) does no client-side downscale as of 0.3.0/0.4.0. If future versions add one, the version MUST be recorded here so cache-hit estimation remains deterministic.

## §7.5 Assistant / tool messages MUST NOT carry images

`serialize.ts::assertSupportedImageRoles` in `@deepseek-ai/dsh-llm-deepseek` throws `UNSUPPORTED_CONTENT` when any non-user message carries image content. The Python harness mirrors this via `assert_multimodal_shape` at contract level. Adapters MAY tolerate image parts on tool messages by inlining them into a follow-up user message; this deviation MUST be logged.

## §7.6 Half-turn commit on missing attachment service (official Node bug)

`@deepseek-ai/dsh-llm-deepseek/adapter.ts:245-249` throws `UNSUPPORTED_CONTENT` inside `stream()` when a user turn carries an image but the attachment service (`@deepseek-ai/dsh-attachment-local`) is not mounted. The throw happens **after** the user turn was appended to the session log, leaving the session with an image-bearing user message and no assistant reply. `dsh doctor --node --only P8-multimodal-preflight` detects the missing service before this happens.

The Python harness does not have this failure mode because it does not persist an event log; a caller retrying after failure is trivially safe.

## §7.7 Observations (not normative)

Recorded here so future contract revisions can reference concrete provider behaviour:

- **DeepSeek Files API upload prefix** — `dsh-*` filenames are shared across all installs using one API key. Cross-install quota reclaim can silently delete another install's file_ids. Covered by P9-files-quota-scope.
- **No dsh-side slice/tiling** — DeepSeek's vision model handles server-side tiling; the harness sends one flat image. This is architectural on DeepSeek's side and out of scope for a client harness.
- **No streaming prefill for vision** — DeepSeek's chat/completions endpoint assembles the request fully before opening the SSE stream. Adapters SHOULD NOT expose a "start streaming while image uploads" API; it does not correspond to anything the endpoint accepts.

## References

- `packages/core/deepseek_harness/normalize.py::assert_multimodal_shape` — enforcement helper.
- `packages/core/deepseek_harness/cache.py::estimate_image_tokens` — token estimator.
- `packages/core/deepseek_harness/cache.py::_serialize_messages` — canonicalised image URL for prefix estimation.
- [HISTORY.md](../HISTORY.md) — per-official-release status of vision-related probes.
- [DeepSeek Vision docs](https://api-docs.deepseek.com/) — authoritative reference when they publish a per-model token table.
