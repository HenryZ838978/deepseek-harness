# DeepSeek V4-Pro / V4-Flash Protocol Compliance: A Probe-Based Audit

**Henry Zhang** · _ModelBest / MiniCPM_ · 2026-05-09
**Repository:** [github.com/HenryZ838978/deepseek-harness](https://github.com/HenryZ838978/deepseek-harness)
**Reproducibility:** every claim in §4 is bound to a `reports/probes/probe_*.py` file and a JSONL fixture in `reports/raw/`.

---

## Abstract

DeepSeek V4-Pro and V4-Flash are exposed via an OpenAI-compatible HTTP surface. Despite the surface compatibility, the wire protocol carries 16 documented quirks ranging from undocumented multi-turn requirements (`reasoning_content` lifecycle 400) to client-side denial-of-service vectors (V8 `Invalid string length` triggered by reasoning runaway). We design 12 probes that together exercise the protocol contract end-to-end, run 270 trials at a total cost of \$2.5, and produce a public dataset of raw JSONL fixtures plus an RFC2119-style specification (`spec/`). We further ship four wrapper-protocol packages — Python library (`deepseek-harness`), command-line tool (`dsh`), Model Context Protocol server (`@deepseek-harness/mcp`), and Anthropic Skill (`SKILL.md`) — that share a single source of truth and enforce the contract by default. An acid test demonstrates that the same prompt that 400s on a vanilla `openai` client succeeds 3/3 through the harness.

**Keywords:** DeepSeek, LLM protocol audit, prefix cache, reasoning_content, MCP, Anthropic Skill.

---

## 1 · Introduction

DeepSeek's V4 series prices input cache hits at **\$0.0028 per million tokens** versus **\$0.14/M** for a miss — a factor-of-fifty discount conditioned on **byte-for-byte prefix match starting from token 0**. Combined with a 1,048,576-token context window, V4-Flash offers an outlier cost-quality frontier on agentic workloads. However, public reports (e.g. `microsoft/agent-framework#5538`, `cline/cline#1594`, `deepseek-ai/DeepSeek-V3#1244`, `deepseek-ai/DeepSeek-V3#1069`) document protocol-level bugs that cause traditional OpenAI-compatible clients to fail — sometimes silently (cache miss without notification) and sometimes loudly (HTTP 400, V8 `RangeError: Invalid string length`).

This report contributes:

1. A taxonomy of 16 distinct protocol quirks observed on V4-Pro and V4-Flash (§4).
2. A reproducible probe suite (§3) producing falsifiable JSONL fixtures.
3. An RFC2119-style specification (`spec/`) and four drop-in wrappers (§5) that close the contract gaps.
4. Two non-trivial empirical refinements over published community claims:
    - The historic `tool_call` leakage (`#1244`, reported at ~11%) is **not reproducible** on V4 (0/50 trials).
    - The strict-mode JSON corruption (`#1069`, closed as `not-planned`) is also **not reproducible** on V4 (0/32 trials).
5. Two novel quantitative findings:
    - Hard context ceiling is exactly **1,048,576 tokens (= 2²⁰)**.
    - Prefix cache buckets at a granularity of **256 tokens**, not the documented "byte-for-byte" interpretation.

---

## 2 · Setup

| Item | Value |
|---|---|
| Endpoint | `https://api.deepseek.com` (OpenAI-compatible chat completions) |
| Models | `deepseek-v4-pro`, `deepseek-v4-flash` |
| SDK | `openai==1.x` (Python), `openai==4.x` (Node.js) |
| Tokenizer (local approximation) | `tiktoken` `cl100k_base` |
| Test window | 2026-05-09, single API key |
| Total cost | ≈ USD \$2.5 across 270 trials |

All probes load credentials from `.env`, write raw responses to `reports/raw/<probe>/<UTC-iso>.jsonl`, and produce a one-line summary on stdout. The probe corpus is itself the test:

```bash
bash reports/probes/probe_11_v4flash_sweep.sh   # ~5 minutes; full V4-Flash sweep
```

### 2.1 Probe inventory

| ID | name | trials | scope |
|---|---|---|---|
| 1 | `streaming_basic` | 3 | catalog SSE chunk shapes |
| 2 | `reasoning_lifecycle` | 9 (3 trials × 3 phases) | reproduce the 400 deterministically |
| 3 | `tool_call_leakage` | 30 | quantify intermittent leakage to `content` |
| 3b | `tool_call_leakage_thinking` | 20 | same with `thinking=enabled` |
| 4 | `strict_mode_corruption` | 16 (V4-Pro) + 16 (V4-Flash) | trigger `#1069` |
| 5 | `cache_prefix_sensitivity` | 24 (S1+S2+S3) | map cache invalidation rules |
| 6 | `context_limits` | 6 (3 tiers × 2) | latency vs prompt size |
| 6b | `context_ceiling` | 6 | walk to the hard ceiling |
| 7 | `tool_streaming_chunks` | 3 | parallel tool delta order |
| 8 | `finish_reason_semantics` | 9 | length / stop / filter cuts |
| 9 | `reasoning_runaway` | 3 | bound on `reasoning_content` length |
| 10 | `multiturn_agentic_loop` | 15 | mirror DeepSeek's official examples for 5 turns |
| 11 | `v4flash_sweep` | omnibus | re-run probes 1, 2, 3, 3b, 5, 7, 10 on V4-Flash |

---

## 3 · Methodology

### 3.1 Mirroring official examples

Probes 9 and 10 reproduce the official DeepSeek code samples from
[`api-docs.deepseek.com/zh-cn/guides/multi_round_chat`](https://api-docs.deepseek.com/zh-cn/guides/multi_round_chat)
and [`/zh-cn/guides/function_calling`](https://api-docs.deepseek.com/zh-cn/guides/function_calling)
verbatim. This guarantees that any failures are attributable to the official-example × DeepSeek pair rather than to client-side novelty.

### 3.2 Falsifiability conventions

Each probe writes a `TrialRecord` per request with: started_at, latency_ms, status, finish_reason, full `usage` block, structured `notes`, and a `raw_excerpt`. Running `python -m deepseek_harness.summarize reports/raw reports/summary` materialises one markdown file per probe with status counts, latency percentiles, and cache-hit distributions. The audit trail is therefore reproducible from any subset of `raw/*.jsonl`.

### 3.3 Cost discipline

Probe 6b deliberately walks toward the 1 M-token ceiling; we cap at one trial per tier and observe the BadRequestError rather than retry into the ceiling. Probe 9 caps `reasoning_content` accumulation at 1.5 MB to avoid reasoning-runaway charges. Probe 11 reuses cached prefixes across the V4-Flash sweep.

---

## 4 · Findings

We group the 16 findings by the contract rule they violate. Each cell links to the canonical probe and to the deepest social-media or upstream issue confirming it.

### 4.1 Group A — `reasoning_content` lifecycle (Finding 3)

The most consequential bug. With `thinking=enabled` (the V4-Pro default), every assistant message that carries `tool_calls` AND is followed by a `tool` message in the next turn **must** preserve its original `reasoning_content` field. Stripping it yields, with 100% reproducibility:

```
HTTP 400 Bad Request
{"error":{"message":"The `reasoning_content` in the thinking mode must be passed back to the API.","type":"invalid_request_error","param":null,"code":"invalid_request_error"}}
```

| trial | phase A (faithful echo) | phase B (stripped) |
|---|---|---|
| 0 | 200 | 400 |
| 1 | 200 | 400 |
| 2 | 200 | 400 |

(`reports/raw/probe_2_reasoning_lifecycle/`, V4-Pro and V4-Flash both exhibit identical behaviour.)

**Mitigation (§5):** the harness wraps the OpenAI client and always preserves `reasoning_content` on the assistant message dict; on a NEW user-turn boundary it strips the field to keep the prefix-cache key deterministic.

### 4.2 Group B — Streaming surface (Findings 2, 4, 5, 14)

**Finding 2** (cline #1594). DeepSeek emits ~3 chunks per response with `choices == []` and no `usage`. A naive `chunk.choices[0]` access throws.

**Finding 4** (no public issue). Parallel `tool_call` deltas are **interleaved** across `tc.index` values — chunk #5 may belong to index 0 while chunk #6 belongs to index 1. Aggregation must use `dict[int]`, not `list.append`. probe_7 confirmed 100% interleaving in 3/3 V4-Pro and V4-Flash trials.

**Finding 5** (no public issue). With `thinking=enabled` and a tight `max_tokens`, the cut can land before any `content` or `tool_calls` token has been emitted, leaving an assistant message with `content=""`, `tool_calls=null`, `finish_reason="length"`. Agent loops that switch on non-empty content as the heuristic for "model produced something useful" will misroute.

**Finding 14** (no public issue). DeepSeek streams `reasoning_content` at a granularity of 1–3 characters per chunk. probe_9 measured a 26 KB / 84 s response producing 7,941 chunks. Any client doing `state.text += chunk` faces O(n²) memory pressure. This is the upstream cause of the ChatWise `RangeError: Invalid string length` reports, not unbounded reasoning per se.

### 4.3 Group C — Cache (Findings 9, 10, 11)

**Finding 9** (`pi-mono#3880`). DeepSeek populates `usage.prompt_cache_hit_tokens` (DeepSeek-native), while the OpenAI standard expects `usage.prompt_tokens_details.cached_tokens`. Vanilla OpenAI parsers see 0 hit even when DeepSeek charged the cached price. (V4 returns BOTH fields, so the bug is mostly a downstream-parser issue rather than a wire-protocol issue.)

**Finding 10** (no public issue). Mid-prefix flips do not nuke the entire cache. probe_5 S2 measured: a single character flipped near the middle of a 1336-token system prompt → cache hits drop from 95.8% to 38.3% (`512/1336`). The first 2 × 256 = 512 tokens still hit. The cache invalidation is **forward-only from the diff point**, not "all-or-nothing".

**Finding 11** (no public issue). Cache eviction is observable in the wild. probe_5 S1#3 returned 0% hit on an otherwise identical prefix sequence (S1#0–#2 and #4–#7 all 95.8%). Cause unknown; agent code must not assume cache hits are stable across requests.

### 4.4 Group D — Context window (Finding 12)

The hard context ceiling is exactly **2²⁰ = 1,048,576 tokens**, enforced as `len(messages_tokens) + max_tokens ≤ 1,048,576`. The 400 message includes a precise byte count:

```
This model's maximum context length is 1048576 tokens. However, you requested 1060836 tokens (1060828 in the messages, 8 in the completion). Please reduce the ...
```

Latency scales approximately linearly with input size (see `reports/REPORT_2026-05-09.md` §6 for the full table; cold path ≈ 1.5 ms / 1K input tokens up to 15.6 s at 1 M).

### 4.5 Group E — V3-era bugs that V4 silently fixed (Findings 6, 7)

**Finding 6.** `deepseek-ai/DeepSeek-V3#1244` reported ~11% tool-call leakage to `content` on V3 multi-turn flows. probe_3 + 3b ran 50 trials (30 with thinking-off, 20 with thinking-on) on V4-Pro and V4-Flash and observed **0** leakages.

**Finding 7.** `deepseek-ai/DeepSeek-V3#1069` reported strict-mode JSON corruption (missing closing quote on the first key) when combining `/beta` + `function.strict=true` + `additionalProperties=false`. The issue was closed as `not-planned`. probe_4 ran 32 trials across both endpoints and both V4 models and observed **0** corruptions.

We document both as "fixed in V4 series, status unannounced". The harness retains the salvage paths defensively; they may be needed against vLLM / SGLang / OpenRouter relays that still serve V3-tokenizer behaviour.

### 4.6 Group F — Endpoint & defaults (Findings 1, 8)

**Finding 1.** `deepseek-v4-pro` and `deepseek-v4-flash` default to `thinking=enabled`. Trivial prompts incur 30–300 `reasoning_tokens` on every call. We measured `reasoning_tokens: 31` on a "reply with PONG" prompt without explicit thinking-disable.

**Finding 8.** The `/beta` endpoint silently remaps `deepseek-v4-pro` to legacy `deepseek-reasoner`. The remapped model rejects specific `tool_choice = {"type":"function","function":{"name":"X"}}` with `400 deepseek-reasoner does not support this tool_choice`. Practical implication: do not route to `/beta` when tool calls are involved.

### 4.7 Group G — Healthy multi-turn (Finding 15)

Despite the volume of community complaints about multi-turn flows, probe_10 ran **15/15 turns successfully** across three scenarios (chat-only, single-tool loop, multi-tool with `thinking=enabled`) on **both** V4-Pro and V4-Flash, with cache hit rate progressing 0% → 95.8% over 5 turns. The dominant root-cause of community failures appears to be client-side `reasoning_content` stripping (Finding 3) rather than a server-side multi-turn bug.

### 4.8 Group H — Cross-model identity (Finding 16)

probe_11 re-ran probes 1, 2, 3, 3b, 5, 7, 10 against V4-Flash. Behaviour is **bit-for-bit identical to V4-Pro** on every protocol observable, with the only differences being latency (Flash is ~2× faster) and cost. No protocol guard is V4-Pro-specific; the same harness adapts to V4-Flash without changes.

---

## 5 · Implementation: a 4-form harness

We ship four wrapper packages, all derived from a single `spec/` source:

| package | distribution | install | primary user |
|---|---|---|---|
| `deepseek-harness` | PyPI | `pip install deepseek-harness` | Python agent / framework devs |
| `deepseek-harness-cli` | PyPI | `pip install deepseek-harness-cli` | command-line / debugging |
| `@deepseek-harness/mcp` | npm | `npx -y @deepseek-harness/mcp` | Claude Desktop, Cursor, Cline, ChatWise, Cherry Studio |
| `packages/skill/SKILL.md` | git drop-in | `cp -r packages/skill/ ~/.claude/skills/deepseek-harness/` | Claude Code, any SKILL.md-aware agent |

Each form enforces the same 10 contract rules (`spec/00_overview.md`):

| # | rule | derived-from |
|---|---|---|
| C1 | `thinking` disabled by default | Finding 1 |
| C2 | preserve `reasoning_content` in tool-loop messages | Finding 3 |
| C3 | always set `max_tokens` (default 4096) | Findings 6 + 13 |
| C4 | aggregate parallel `tool_calls` by `tc.index` | Finding 4 |
| C5 | use list buffer + `"".join`, not `state += chunk` | Finding 14 |
| C6 | tolerate empty stream chunks | Finding 2 |
| C7 | enforce `prompt_tokens + max_tokens ≤ 1,048,576` | Finding 12 |
| C8 | warn before invalidating prefix-cache | Findings 10/11 |
| C9 | do not route to `/beta` when tools are passed | Finding 8 |
| C10 | `strict: true` is empirically OK on V4 | Finding 7 |

### 5.1 Acid test

The acid test ships in two forms:

```python
# (a) Reproduce the bare-bones failure:
python reports/probes/probe_2_reasoning_lifecycle.py --n 3
# Expected: 3/3 phase-B BadRequestError with the verbatim 400 message above.

# (b) Same scenario through the harness:
PYTHONPATH=packages/core:packages/cli python -m deepseek_harness_cli doctor
# Expected: green table with cost ≈ $0.000002 USD.
```

If (a) stops failing in a future DeepSeek release, the spec needs updating — please open an issue with the new behaviour.

---

## 6 · Limitations

1. All probes run against the official `https://api.deepseek.com` endpoint. Behaviour on `vLLM`, `SGLang`, or `OpenRouter` relays may differ; this is a known gap. Findings 6/7 are particularly suspect on V3-tokenizer relays — the salvage paths in `core/tool_calls.py` are retained defensively.
2. Trial counts are modest (3–100 per probe). Statistical claims like "0/50 leakage" should be read as "did not occur in 50 consecutive trials on a single API key on 2026-05-09", not as a rigorous proof of absence.
3. Cache-eviction observations (Finding 11) are anecdotal — we saw S1#3 return to 0% hit but cannot characterise the eviction trigger without server-side logs.
4. We have not tested the Anthropic-format endpoint (`https://api.deepseek.com/anthropic`), nor FIM completion, nor JSON-mode output. These are deferred to a future report.

---

## 7 · Reproducibility statement

The repository at `github.com/HenryZ838978/deepseek-harness` is self-contained.

```bash
git clone https://github.com/HenryZ838978/deepseek-harness
cd deepseek-harness
cp .env.example .env       # then fill DEEPSEEK_API_KEY
pip install -e packages/core packages/cli
dsh doctor
bash reports/probes/probe_11_v4flash_sweep.sh    # full sweep, ~$2 in API charges
```

`reports/raw/*.jsonl` files in this repo are the original probe outputs from 2026-05-09; rerunning the sweep produces a new directory tree under `reports/raw/<UTC-iso>/`, allowing trivial diff-based regression analysis on future DeepSeek releases.

Machine-readable ground truth: [`docs/trust_ledger.yaml`](trust_ledger.yaml).

---

## 8 · Acknowledgements

This work is informed by community reports filed against `microsoft/agent-framework`, `cline/cline`, `NousResearch/hermes-agent`, and `deepseek-ai/DeepSeek-V3`. The probe design borrows the "audit-friendly YAML" pattern from the GEO-style READMEs at `github.com/HenryZ838978/HenryZ838978`. ChatWise users surfaced Finding 13 in the wild and provided the screenshot evidence that motivated probe_9.

---

## License

MIT. See [`LICENSE`](../LICENSE).
