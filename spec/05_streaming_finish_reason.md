# §5 — Streaming chunk shapes + `finish_reason` semantics

## 5.1 Streaming shape catalogue (probe_1 + probe_7, validated 2026-05-09)

DeepSeek streaming SSE chunks observed:

| Shape | probe_1 frequency (n=3, 61 chunks) | Notes |
|---|---|---|
| `delta.content` only | 55 | trivial |
| **completely empty** (no choices, no delta, no usage) | **3** | one per response — the `cline #1594` trigger |
| `finish_reason="stop"` + `usage` populated | 3 | terminal chunk, `choices == []` |
| `delta.reasoning_content` only | many in thinking-mode | content is None! adapter MUST accumulate this (cross-ref §1) |
| `delta.tool_calls` chunk | 1+ per tool | function.name typically arrives in the first chunk per `index`, function.arguments split across many chunks |

## 5.2 Normative rules

1. Adapter **MUST NOT** index `chunk.choices[0]` without checking `choices` truthiness first.
2. Adapter **MUST** accumulate `tool_calls` deltas keyed by `tc.index`, not by `tc.id`
   (id may arrive only in the first chunk for that index).
3. Adapter **MUST** join `function.arguments` pieces in arrival order WITHOUT
   inserting whitespace. The model can split mid-token in the JSON string.
4. Adapter **MUST** accept that `tool_call` deltas across distinct `tc.index`
   values arrive **interleaved**. probe_7 observed 100% interleaving (3/3 trials)
   when `parallel_tool_calls=true`. A `list.append` aggregator that assumes
   "all chunks for index 0 arrive before any chunk for index 1" will mis-route
   payload. Use `dict[int, slot]` keyed on `tc.index`.
5. Adapter **MUST** tolerate "completely empty" chunks (no `choices`, no `usage`,
   no `delta`). probe_1 saw ~3 such chunks per response on V4-Pro streaming.

## 5.3 `finish_reason` semantics (from probe_8)

| value | observed behaviour |
|---|---|
| `stop` | normal end. Cross-ref §2: content MAY still hide a tool call. |
| `tool_calls` | message.tool_calls populated, content typically null. |
| `length` | `max_tokens` reached. Tool-call arguments may be truncated → JSON parse fails. Adapter MUST NOT salvage in this case (see §2 rule). |
| `content_filter` | rare on official endpoint; downstream content / tool_calls clobbered to null. |

## 5.4 Reference implementation

`src/deepseek_v4pro_kit/client.py::DeepSeekClient.stream_chat`.
