# deepseek-harness-cli 0.8.0

**28 upstream releases in, two of our findings are fixed. One of our own probes had stopped looking, and there is a new model-behaviour probe.** This release audits `@deepseek-ai/dsh` 0.2.2-rc.5 (`latest`) and 0.2.3-alpha.2 (`alpha`). The official harness was installed from npm on a clean host and ran a real `dsh headless` session there; this repo's doctor then ran against that install.

```bash
pip install -U deepseek-harness-cli
pip install zstandard          # optional; otherwise the zstd CLI is used
dsh doctor --node
```

## Fixed upstream: probes now read the installed harness version

- **P4-spill: fixed in 0.1.7-alpha.2.** The fix came out of upstream's own Windows crash report (`.agents/notes/implemented/architecture/2026-09-22-fatal-diagnostics-and-crash-reports.md`). `spillAll` now contains open/append failures and reports them through `onFailure`. On a fixed harness, an unwritable spill dir is a warn: it costs the spill file, not the process.
- **P11-plugin-inventory-manifest: fixed in 0.2.1-alpha.2.** A name-only manifest is now tolerated. On a fixed harness the probe passes and states what the pre-fix verdict would have been.

Both fix versions were bisected by fetching the one file at every tag. The new `doctor_node/_upstream.py` reads the version from the `@deepseek-ai/dsh` package.json behind `dsh` on `PATH`. It deliberately ignores this package's own Python `dsh` entry point.

## P5 had stopped looking; now fixed

Since the 0.1.7 line, every session log dsh writes is `session.v4.jsonl.zstd`. P5 and P10 skipped `.zstd` files, so P5 reported `pass` without reading a single event. The container is plain concatenated Zstandard frames, header frame first; the probes now decode it with the `zstandard` module or the `zstd` CLI.

Cross-check against the real harness: a live session was copied, and one copy got a duplicated seq and another a dropped seq. Official `dsh headless --session-id` refuses both copies with `invalid committed event at line N: released v2 row M has seq gap`. P5 reports `fail` on the same line with the same expected/got. The untouched control resumes and answers.

## New: P13-tool-thinking (live)

- **Contract.** With thinking on (the default), every forcing `tool_choice` returns HTTP 400 `"Thinking mode does not support this tool_choice"`. This holds on both the Messages and Chat endpoints and on both canonical ids. Forcing works with `thinking: {"type": "disabled"}`, or through the `deepseek-chat` alias, which resolves to `deepseek-flash` with thinking off.
- **Behaviour.** `deepseek-v4-pro` with thinking off calls the only available tool on unrelated Chinese prompts:
  - "17 乘以 23 等于多少？只给数字。" → `get_weather({"city": "17乘以23"})` in 7/12 trials.
  - The same question in English: 0/12. With thinking on: 0/12. `deepseek-flash`: 0/36.
- **How dsh reaches it.** In dsh, `effort: off` sends exactly this mode.
- **Fix.** Keep effort ≥ low on v4-pro turns that carry tools, or validate tool arguments.

## Also in this release

- **P8** recognises the bundle-mounted llm-deepseek. Its premise was re-verified at 0.2.2-rc.5: an image sent to text-only `deepseek-v4-pro` throws at `images.ts:46` after `agent.ts:473-482` has already appended the user turn.
- **Model notes** (live, recorded in `models.py` and HISTORY):
  - `/models` now carries `effort` levels, a 1M context window, 393K max output, and the `api_capabilities` for system-prompt and tool updates.
  - Effort level does not drive latency on simple routing turns (0.5–2 s across off…max).
  - The P1 reasoning skip is back after the V4.1-Flash-1017 model update: bare 4/10, versus 0/12 on 2026-09-10.
- **Still open at both tags:** P2, P6, P7, P9.

Raw evidence: [`reports/raw/audit_0.2.2-rc.5_2026-11-25/`](../reports/raw/audit_0.2.2-rc.5_2026-11-25/), `reports/raw/probe_P12_effort_tools_2026-11-25.jsonl`, `reports/raw/probe_P13_spurious_tool_call_2026-11-25.jsonl`. Every claim with its `file:line`: [HISTORY.md](../HISTORY.md), entry 2026-11-25.
