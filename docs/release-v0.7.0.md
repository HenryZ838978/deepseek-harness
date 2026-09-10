# deepseek-harness-cli 0.7.0

**V4.1 Flash landed, and it moved three contracts at once.** `@deepseek-ai/dsh` 0.1.5-rc.1 (2026-09-10) shipped the day after DeepSeek's V4.1 Flash; the server side changed under it. This release records the live-measured behaviour and re-judges one probe.

```bash
pip install -U deepseek-harness-cli deepseek-harness
dsh doctor --node
```

## What the live endpoint does now (measured 2026-09-10)

`GET /models` returns exactly two ids — `deepseek-flash` and `deepseek-v4-pro`. Sending `deepseek-v4-flash`, `deepseek-v4-flash-vision-exp`, `deepseek-reasoner`, or `deepseek-chat` returns **HTTP 200 with the response `model` field set to `deepseek-flash`** — the server silently re-points every legacy id. An unknown id is rejected with an error that lists exactly the two canonical names.

Three probes are affected and each was re-verified against the live endpoint, not just the source tag:

- **P1-reasoner-skip.** The skip this probe exists to detect is gone on V4.1 Flash: `deepseek-reasoner` (now an alias to `deepseek-flash`) emitted `reasoning_content` on 12/12 bare and 12/12 hinted samples, where the 2026-08-17 baseline was 60% bare / 0% hinted. The probe keeps its A/B shape as a regression detector; the warn branches no longer fire on current models. The `tool_choice:"required"` sub-test got *broader* — all three ids now return 400 because V4.1 Flash runs in thinking mode too.
- **P10 re-judged: FIXED.** Upstream 0.1.5-alpha.1 added a cross-process session write lease (`session-persistence-jsonl/src/lease.ts`), taken at write-open *before* the torn-tail repair. Its design note states P10's exact failure mode and closes it. `packages/session/` went from **0** lock primitives at 0.1.2-rc.1 to **19** at 0.1.5-rc.1 — the grep that was P10's open-defect proof now proves the opposite. The probe is retitled `P10-jsonl-repair-race` and reports a torn tail as a "your harness is old" signal instead of an open defect, so it does not misreport on a fixed server (the same reason P3 was re-judged at 0.5.0).
- **P8-multimodal-preflight.** The default catalog gained `deepseek-flash` with `inputModalities: ['text', 'image']`, so an image-capable row is now present without the user ever naming a vision model. The `flash` hint was added so a profile pinning it is still caught.

## What moved in the Python contract

- **Model catalog.** `DEEPSEEK_FLASH = "deepseek-flash"` added as the canonical fast model; the old ids stay as documented aliases that all resolve to it. `supports_image_input` now returns True for `deepseek-flash` and its aliases, and False for `deepseek-v4-pro` — which accepts an image request (HTTP 200) but drops the image part and bills text-only tokens, a silent failure.
- **Vision token constants recalibrated.** A dense sweep against `deepseek-flash` measured a curve that the 2026-08-22 anchors no longer fit: baseline 186 → 184, but the plateau more than doubled, 418 → 994. `estimate_image_tokens` and `spec/07 §7.2` carry the new table; the 64×64-PNG case rose from ~184 to 994 at the top end.

Raw streamed responses: [reports/raw/probe_P12_v41_flash_live_2026-09-10.jsonl](reports/raw/probe_P12_v41_flash_live_2026-09-10.jsonl). Full chain, with the exact `file:line` for every claim, in [HISTORY.md](../HISTORY.md) under the 2026-09-10 entry.

## Upstream state at this release

`@deepseek-ai/dsh` dist-tags: `latest` = `next` = `0.1.5-rc.1`, `alpha` = `0.1.5-alpha.2`. The tag line skipped `0.1.4` — neither git tags nor the npm registry carry it. `0.1.5-rc.1` is `0.1.5-alpha.2` plus 34 non-version files, of which the only code change is `ui-sidebar-files/definition.ts → .tsx`; the substantive work landed in `0.1.3-alpha.2 → 0.1.5-alpha.1` (877 changed code files, the write lease among them).

Eight of the ten defect-line probes (P2, P4–P9, P11) remain open; P3 and now P10 are fixed upstream. All verified at tag `183f08e9`.
