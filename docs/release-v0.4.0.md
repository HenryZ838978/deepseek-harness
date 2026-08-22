# deepseek-harness-cli 0.4.0 · deepseek-harness 0.3.0

**Multimodal (vision) contract added.** `@deepseek-ai/dsh` 0.1.1-rc.2 (2026-08-21) shipped `deepseek-v4-flash-vision-exp` in its default catalog; this release adds the corresponding Python-side contract, one week end-to-end. No change to the text-only path.

```bash
pip install -U deepseek-harness deepseek-harness-cli
```

## New in `deepseek-harness` 0.3.0 (core)

- **`spec/07_multimodal.md`** — RFC 2119 contract for vision. Message-shape rules (image_url in user messages only), byte-for-byte prefix cache implications for image payloads, DeepSeek Files API interactions, client-side downscale as out-of-scope, half-turn-commit failure mode covered by P8, cross-install file_id race covered by P9.
- **`normalize.assert_multimodal_shape(messages)`** — enforces the vision-side shape invariants. Rejects image parts on assistant/tool messages, empty `image_url.url`, malformed text parts. Text-only messages pass through untouched.
- **`cache.estimate_image_tokens(w, h, detail=)`** — deterministic image-token estimator with `low` / `high` detail tiers. Constants (85 / 258 / 170 / 512) are pinned in code so cache-hit estimation stays reproducible across process restarts, per §7.2 rationale.
- **`cache.estimate_cache_hit`** — canonicalises image URLs to a 12-hex sha256 placeholder before tokenizing, so a 5 MiB data URL does not dominate the prefix diff. Identical images at identical positions still match byte-for-byte at the server level.
- **`models` module** — canonical model ids: `DEEPSEEK_V4_PRO`, `DEEPSEEK_V4_FLASH`, `DEEPSEEK_REASONER`, `DEEPSEEK_V4_FLASH_VISION_EXP`, plus `KNOWN_MODELS` tuple and `supports_image_input(model_id)`.
- 11 new pytest cases in `tests/test_multimodal.py`; all pass.

## New in `deepseek-harness-cli` 0.4.0

- Minor-version bump follows core. `dsh doctor --node` probe set is unchanged from 0.3.2 (nine probes; P8 and P9 both cover vision paths from the doctor side).
- Now requires `deepseek-harness>=0.3.0`.

## Rationale

DSH does not need to wait for DeepSeek's Node harness to stabilize its vision surface. The contract in `spec/07_multimodal.md` documents observed provider behaviour as of 2026-08-22; if DeepSeek changes the wire, we update the spec and the constants and record it in HISTORY. The Python contract stays deterministic in between.
