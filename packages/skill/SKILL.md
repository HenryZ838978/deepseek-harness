---
name: deepseek-harness
description: Use this skill whenever the user wants to call DeepSeek V4-Pro / V4-Flash (or its legacy aliases deepseek-chat / deepseek-reasoner), or you see code that imports `from openai import OpenAI` with `base_url="https://api.deepseek.com"`. This skill teaches you the 10 protocol contract rules required to avoid the 16 documented bugs (reasoning_content lifecycle 400, tool-call leakage, max_tokens runaway → V8 string limit, parallel tool delta interleave, prefix-cache invalidation, /beta endpoint remap, etc.) and ships a single drop-in `safe_init.py` script you can copy into the user's project.
when_to_use: |
  Any of these triggers should invoke this skill:
  • user mentions DeepSeek, deepseek-v4-pro, deepseek-v4-flash, deepseek-chat, deepseek-reasoner, or 深度求索
  • code references `https://api.deepseek.com` or `https://api.deepseek.com/anthropic` or `/beta`
  • user complains about `400 reasoning_content`, `Invalid string length`, `RangeError`, hangs in chat clients, or "weird tool call behaviour"
  • user wants the cheapest possible LLM hosting that is also smart (V4-Flash $0.14/M input miss, $0.0028/M cached → 50× discount)
license: MIT
version: 0.2.0
author: Henry Zhang (HenryZ838978)
homepage: https://github.com/HenryZ838978/deepseek-harness
---

# DeepSeek V4 Harness

When you call DeepSeek V4-Pro or V4-Flash via the OpenAI-compatible API, you MUST follow the 10 contract rules below. Violating any one of them causes a documented production bug (the upstream issue and our reproduction probe are cited per rule).

## The 10 contract rules (ranked by blast radius)

### C1 · Disable thinking unless the task is genuinely reasoning-heavy

`deepseek-v4-pro` defaults to `thinking=enabled`. Every call then burns 30-300 `reasoning_tokens` even on trivial prompts.

```python
client.chat.completions.create(
    model="deepseek-v4-pro",
    messages=messages,
    extra_body={"thinking": {"type": "disabled"}},  # ← saves money on every non-reasoning call
)
```

For TypeScript / openai-node, put `thinking` at the **top level** of the request, not inside `extra_body` (the JS SDK passes unknown top-level keys through):

```ts
await openai.chat.completions.create({
  model: "deepseek-v4-pro",
  messages,
  thinking: { type: "disabled" },
} as any);
```

### C2 · In multi-turn loops, preserve `reasoning_content` on assistant messages

If thinking IS enabled and you re-send a prior assistant message that has `tool_calls`, you **must** include the original `reasoning_content` field. Otherwise the next request returns:

```
HTTP 400: The reasoning_content in the thinking mode must be passed back to the API.
```

(Reproduced in `reports/probes/probe_2_reasoning_lifecycle.py` 3/3 trials on V4-Pro and V4-Flash, 2026-05-09.)

```python
msg = response.choices[0].message
history.append({
    "role": "assistant",
    "content": msg.content,
    "tool_calls": _serialize_tool_calls(msg.tool_calls),
    "reasoning_content": getattr(msg, "reasoning_content", None),  # ← REQUIRED
})
```

When a NEW user turn arrives, you MAY strip `reasoning_content` from prior assistant messages — DeepSeek doesn't require it across user-turn boundaries, and keeping it bloats the prefix-cache key.

### C3 · Always set `max_tokens` (default 4096)

Without an output cap, `reasoning_content` can stream 8000+ chunks (`probes/probe_9_reasoning_runaway.py` measured 26 KB / 84 s on a self-doubt prompt) and downstream Electron clients (ChatWise, Cherry Studio) crash with `RangeError: Invalid string length` once their string buffer hits V8's 512 MB ceiling.

### C4 · Streaming: aggregate parallel `tool_calls` by `tc.index`, not list order

DeepSeek interleaves chunks across parallel tool calls (probe_7 100% interleave on 3/3 V4-Pro and V4-Flash trials). Use a `dict[int, slot]`:

```python
tool_call_acc: dict[int, dict] = {}
for chunk in stream:
    for tc in (chunk.choices[0].delta.tool_calls or []):
        slot = tool_call_acc.setdefault(tc.index, {"id": None, "name": None, "arguments": ""})
        if tc.id: slot["id"] = tc.id
        if tc.function and tc.function.name: slot["name"] = tc.function.name
        if tc.function and tc.function.arguments: slot["arguments"] += tc.function.arguments
```

### C5 · Streaming: list buffer + `"".join`, NOT `state += chunk`

DeepSeek streams 1-3 chars per reasoning chunk. `state.text += chunk` is O(n²) string allocation:

```python
buf = []
for chunk in stream:
    if c := (chunk.choices[0].delta.content or ""):
        buf.append(c)
final = "".join(buf)
```

### C6 · Tolerate empty stream chunks

DeepSeek emits ~3 chunks per response with `choices == []`. Check truthiness before indexing:

```python
for chunk in stream:
    choices = chunk.choices or []
    if not choices:
        if chunk.usage is not None: usage = chunk.usage
        continue
    ...
```

### C7 · Cap context length under 1,048,576 tokens

The V4-Pro / V4-Flash hard ceiling is exactly **2^20 = 1,048,576 tokens** (probe_6b validated). The server enforces `len(messages_tokens) + max_tokens <= 1,048,576` and returns 400 if exceeded.

### C8 · Cache awareness — do NOT inject volatile content into the system prompt

DeepSeek's prefix cache buckets in 256-token blocks and gives a 50× discount on hits. To maximise:

- Do NOT prune or summarise history aggressively (every prune = cache miss)
- Do NOT inject "current date: 2026-05-09" or similar into the cached prefix
- Do read both `prompt_cache_hit_tokens` (DeepSeek-native) AND `prompt_tokens_details.cached_tokens` (OpenAI-shape) — both are returned

### C9 · Avoid `/beta` endpoint when calling V4 with tools

`/beta` silently remaps `deepseek-v4-pro` → legacy `deepseek-reasoner`, which rejects specific `tool_choice={"type":"function","function":{"name":"..."}}`. Use `https://api.deepseek.com` for tool-using flows.

### C10 · `strict: true` is empirically OK on V4 (despite #1069 still being open)

You MAY enable `function.strict=true` and `additionalProperties=false` on V4-Pro / V4-Flash — the historic JSON-corruption bug (`deepseek-ai/DeepSeek-V3#1069`) was not reproducible in 32 trials on 2026-05-09. Still validate JSON post-hoc with `jsonschema`.

---

## Drop-in implementation

If the user's environment allows installing third-party libraries, use any of:

| form | install | command |
|---|---|---|
| Python lib | `pip install deepseek-harness` | `from deepseek_harness import DeepSeekHarness` |
| Python CLI | `pip install deepseek-harness-cli` | `dsh chat`, `dsh doctor`, `dsh validate` |
| MCP server | `npx -y @deepseek-harness/mcp` | wire into Claude/Cursor/Cline/ChatWise MCP config |

If they want zero deps beyond `openai`, copy `scripts/safe_init.py` (in this skill folder) into their project. It implements all 10 rules in 200 lines.

## Reproduction commands

Every claim in this skill is backed by a runnable probe in `reports/probes/`:

```bash
# Reproduce the reasoning_content 400:
python reports/probes/probe_2_reasoning_lifecycle.py --n 3
# Expected: 3/3 phase-B BadRequestError with the verbatim error message above.

# Confirm tool-call leakage rate at 0% on official endpoint:
python reports/probes/probe_3_tool_call_leakage.py --n 30

# Map cache prefix sensitivity:
python reports/probes/probe_5_cache_prefix_sensitivity.py --n 8
```

See [`reports/REPORT_2026-05-09.md`](https://github.com/HenryZ838978/deepseek-harness/blob/main/reports/REPORT_2026-05-09.md) for the full 16-finding report.
