# §1 — `reasoning_content` lifecycle

## 1.1 Symptom (verbatim from probe_2 trial 0, 2026-05-09 official endpoint)

```
HTTP 400 Bad Request
{
  "error": {
    "message": "The `reasoning_content` in the thinking mode must be passed back to the API.",
    "type": "invalid_request_error",
    "param": null,
    "code": "invalid_request_error"
  }
}
```

Triggered when a multi-turn loop's PRIOR assistant message (the one carrying
`tool_calls`) is replayed to DeepSeek **without** its original `reasoning_content`
field.

**Reproduction rate (probe_2, n=3, model=deepseek-v4-pro)**: **3/3 = 100%**.

> Important corollary: this bug fires ONLY when `thinking` is enabled (which is
> the default for `deepseek-v4-pro`). If your client sets
> `extra_body={"thinking":{"type":"disabled"}}` it will never see this 400, but
> it also gives up the model's deep-reasoning behaviour.

## 1.2 Citations

| Source | What it says |
|---|---|
| `microsoft/agent-framework#5538` | reasoning_content must be echoed back in tool-call loops |
| `NousResearch/hermes-agent#15353` | tool-call message missing reasoning_content → 400 |
| `cline/cline` PR #7888 | adds `addReasoningContent` + `isNextGenModelProvider` list including DeepSeek — gold-standard fix |
| `cline/cline#8365`, `#8130` | V3.2/V4 ALSO pack XML tool calls inside `reasoning_content` (cross-cuts §2) |

Probes: `probe_2_reasoning_lifecycle` phase B.

## 1.3 Normative rules

1. The adapter **MUST** preserve the `reasoning_content` field on every assistant
   message it receives from DeepSeek thinking-mode.
2. When the adapter re-sends an assistant message that has `tool_calls != null`
   AND the IMMEDIATELY-NEXT message in the request body has `role == "tool"`,
   the assistant message **MUST** carry the original `reasoning_content`.
3. Across user-turn boundaries (i.e. once a NEW message with `role == "user"`
   arrives), the adapter **SHOULD** strip `reasoning_content` from prior assistant
   messages, because:
   - the server does not require it across turns, AND
   - keeping it bloats the prefix and breaks byte-for-byte cache equality (§4).
4. Streaming chunks **MAY** contain `delta.reasoning_content` even when
   `delta.content` is null. The adapter **MUST NOT** skip such chunks.
5. The terminal SSE chunk **MAY** have `choices == []` and only carry `usage`.
   The adapter **MUST** tolerate this. (Cross-ref §5, cline #1594.)

## 1.4 Reference implementation

`src/deepseek_v4pro_kit/reasoning.py::ReasoningLifecycle` and
`normalize.prepare_for_new_user_turn`.

## 1.5 Negative test

`probe_2`'s phase B is allowed to fail (we WANT the 400). If it stops failing,
we have evidence DeepSeek changed the contract — open an issue and re-spec.
