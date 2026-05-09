# §2 — Tool-call leakage into `content`

## 2.1 Symptom

A request that uses `tools=[...]` and `tool_choice="auto"` SHOULD return:

```json
{
  "finish_reason": "tool_calls",
  "message": {"content": null, "tool_calls": [{...}]}
}
```

V4 Pro intermittently returns instead:

```json
{
  "finish_reason": "stop",
  "message": {"content": "<｜DSML｜tool_calls>...{}...</｜DSML｜tool_calls>", "tool_calls": null}
}
```

…with the tool call payload encoded inside `content` as DSML / `<tool_call>` /
bare JSON, depending on the endpoint (official / vLLM / SGLang / OpenRouter).

## 2.2 Citations

| Source | What it says |
|---|---|
| `deepseek-ai/DeepSeek-V3#1244` | ~11% failure rate in multi-turn tool-use loops |
| `NousResearch/hermes-agent#15453` | raw DSML tags surface in content; varies by endpoint |
| `cline/cline#8365`, `#8130` | XML tool calls land inside `reasoning_content` instead of body |

Probes: `probe_3_tool_call_leakage`.

## 2.3 Normative rules

1. Adapter **MUST NOT** branch solely on `finish_reason` to decide whether the
   model invoked a tool. When `tool_calls` is null AND `content` matches any of:
     - `<｜DSML｜tool_calls...>...</｜DSML｜tool_calls>`
     - `<tool_call>{...}</tool_call>`
     - a bare JSON object with both `name` and `arguments`
     - a fenced ```json ... ``` block containing a name+arguments object
   …the adapter **MUST** secondary-parse the content as a tool call.
2. Adapter **MUST** generate a synthetic `tool_call.id` if the leaked payload
   omits one (e.g. `call_<uuid12>`).
3. Adapter **MUST** strip the leaked tool-call markup from `content` before
   surfacing the message; otherwise the tool result handler will see garbage.
4. Adapter **SHOULD** record salvage events (pattern + original content) in
   logs/telemetry — they are forensics gold for the §4 article and the next
   contract revision.
5. Adapter **SHOULD NOT** retry on leakage; the same prompt may leak in a
   different shape on the retry. Salvage in-place.

## 2.4 Reference implementation

`src/deepseek_v4pro_kit/tool_calls.py::salvage_tool_calls_from_content`.

## 2.5 Boundary

If `finish_reason == "length"`, the leakage MAY be a TRUNCATED tool call (no closing
brace). In that case `salvage_tool_calls_from_content` returns `(None, content, None)`.
The adapter **MUST** treat this case as an unrecoverable error and surface to caller —
do not fabricate arguments.
