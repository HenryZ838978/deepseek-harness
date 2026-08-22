# P1 reasoner skip — 200 trials, 2026-08-17

Raw evidence for the `P1-reasoner-skip` doctor probe in `packages/cli/deepseek_harness_cli/doctor_node/p1_reasoner_wire.py`.

## Design

- Model: `deepseek-reasoner`
- Cells: 5 prompt families × 4 temperatures = 20 cells
- Trials per cell: 10 → **200 total**
- Endpoint: `https://api.deepseek.com/chat/completions`, streaming, `tool_choice: auto`

The 5 prompt families:
- `single_tool` — short: "Think briefly, then call read_file with /tmp/x."
- `multi_tool` — three tools in sequence
- `reasoning_hint` — starts with "Reason step by step. Then call..."
- `cot_forced` — explicit "First, in your reasoning, plan the tool sequence..."
- `no_reason_ask` — "Immediately call read_file with /tmp/x."

Temperatures: `None` (default), `0.0`, `0.7`, `1.3`.

## Files

- `20260817T120741Z.jsonl` — 200 trial records, one per line. Fields: `ts`, `model`, `prompt`, `temp`, `trial`, `http`, `elapsed_s`, `total` (SSE frames), `reasoning` (frames with `reasoning_content`), `tool_calls` (frames with `tool_calls`), `content` (frames with `content`).
- `summary.json` — per-cell aggregate: `n`, `silent` (tc>0 && reasoning=0), `silence_rate`, `healthy` (reasoning>0), `elapsed_avg_s`.

## Headline findings (verify against summary.json)

Silence rate is **prompt-shape-dominated, not temperature-dominated**:

| prompt family                 | silence rate range across temps |
|-------------------------------|---------------------------------|
| `no_reason_ask`               | 40–100%                         |
| `single_tool`                 | 60–80%                          |
| `multi_tool`                  | 0–20%                           |
| `reasoning_hint` / `cot_forced` | **0% every cell**             |

**Interpretation:** `reasoning_content` absence on tool turns is a **model decision**, not a wire bug. Adding "reason step by step" flips reasoning back on deterministically. This finding drove the P1 probe design (A/B contrast between bare and hinted prompts).

## Reproduce

```bash
# Server-side (or any machine with the key):
DEEPSEEK_API_KEY=sk-... N_PER_CELL=10 python3 <scripts>/j1_sample.py
```

Sample script preserved at `overnight/j1/sample.py` on the original probe host. Any subset re-run should reproduce the prompt-family vs temperature pattern within Monte-Carlo variance.
