# DeepSeek V4 — quick reference card

> Compact reference for AI agents reading this skill. Full details: `reports/REPORT_2026-05-09.md`.

## Models

| name | thinking default | context | input cache hit | input cache miss | output |
|---|---|---|---|---|---|
| `deepseek-v4-pro` | enabled | 1,048,576 | (50× discount) | (~$0.14/M ref V4-Flash) | (~$0.28/M) |
| `deepseek-v4-flash` | enabled | 1,048,576 | $0.0028/M | $0.14/M | $0.28/M |
| `deepseek-chat` (legacy alias) | disabled | same as flash | same | same | same |
| `deepseek-reasoner` (legacy alias) | enabled | same as flash | same | same | same |

The legacy aliases `deepseek-chat` / `deepseek-reasoner` will be deprecated 2026-07-24.

## Endpoints

| URL | purpose | warning |
|---|---|---|
| `https://api.deepseek.com` | OpenAI-compatible (recommended) | — |
| `https://api.deepseek.com/anthropic` | Anthropic-format wire | — |
| `https://api.deepseek.com/beta` | strict mode + prefix-completion (beta) | silently remaps `v4-pro` → `reasoner` |

## The 16 documented quirks (probe IDs)

| # | quirk | spec ref | proof |
|---|---|---|---|
| 1 | thinking ON by default on V4-Pro/Flash | C1 / spec §1 | smoke |
| 2 | streaming has ~3 empty chunks per response | C6 / spec §5 | probe_1 |
| 3 | reasoning_content lifecycle 400 | C2 / spec §1 | probe_2 (3/3) |
| 4 | parallel tool deltas interleave | C4 / spec §5 | probe_7 (3/3) |
| 5 | length-cut on thinking-on tools loses content | spec §5 | probe_8 |
| 6 | tool_call leakage to content (V3 era) | spec §2 | probe_3 (0/50, fixed) |
| 7 | strict-mode JSON corruption (V3 era) | spec §3 | probe_4 (0/32, fixed) |
| 8 | /beta endpoint remaps v4-pro → reasoner | C9 / spec §3 | probe_4 |
| 9 | dual cache field names (DS-native vs OpenAI) | C8 / spec §4 | probe_5 |
| 10 | mid-prefix flip preserves first 512 tokens | spec §4 | probe_5 |
| 11 | cache eviction observable in S1#3 | spec §4 | probe_5 |
| 12 | hard context ceiling = 1,048,576 | C7 / spec §6 | probe_6b |
| 13 | reasoning runaway → V8 string limit risk | C3+C5 | probe_9 |
| 14 | SSE chunk granularity 1-3 chars → O(n²) | C5 | probe_9 |
| 15 | 5-turn agentic loop OK if rules followed | all | probe_10 (15/15) |
| 16 | V4-Flash protocol = V4-Pro 1:1 | all | probe_11 |

## Reproduction commands

```bash
# Critical 400 reproduction (3 trials):
python reports/probes/probe_2_reasoning_lifecycle.py --n 3

# Multi-turn loop sanity (15 trials):
python reports/probes/probe_10_multiturn_agentic_loop.py

# V4-Flash full sweep (cross-model contract identity):
bash reports/probes/probe_11_v4flash_sweep.sh
```
