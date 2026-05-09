# F1 — DeepSeek V4 Pro Protocol Spec (overview)

This document is the contract that any "DeepSeek V4 Pro adapter" should satisfy.
Every clause carries:

  - one or more **community citations** (issue / PR links), AND
  - a **probe ID** from this repo (e.g. `probe_3:trial 17`) that reproduces it.

Sections:

| § | Topic | File |
|---|---|---|
| 1 | reasoning_content lifecycle (the #1 source of 400s) | `01_reasoning_content.md` |
| 2 | tool_call leakage into `content` (~11% non-determinism) | `02_tool_calls.md` |
| 3 | strict-mode JSON corruption (close-as-not-planned) | `03_strict_mode.md` |
| 4 | prefix-cache rules + field-name mismatch | `04_cache_hit.md` |
| 5 | streaming chunk shapes + finish_reason semantics | `05_streaming_finish_reason.md` |
| 6 | context-window boundaries (independent finding) | `06_context_limits.md` |

Each clause uses the keywords MUST / SHOULD / MAY in the RFC 2119 sense.

## Compliance levels

| Level | Description |
|---|---|
| **L1** | Application can send a single user prompt and parse a non-streaming response without crashing. (Trivial — most stock OpenAI clients pass.) |
| **L2** | Application can complete a multi-turn tool-use loop without 400s. (Requires §1: reasoning_content lifecycle.) |
| **L3** | Application is robust to the ~11% tool-call leakage. (Requires §2 salvage.) |
| **L4** | Application correctly reports cache-hit usage and warns before invalidating prefix. (Requires §4.) |
| **L5** | Application is streaming-correct, parallel-tool-correct, finish_reason-correct. (Requires §5.) |

The reference Python implementation `deepseek_v4pro_kit.DeepSeekClient` targets **L5**.
