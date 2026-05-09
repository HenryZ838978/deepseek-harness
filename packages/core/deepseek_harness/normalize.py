"""Bidirectional normalisation between OpenAI-shaped and DeepSeek-shaped messages.

Most agent frameworks store assistant messages in a strictly OpenAI shape:

    {"role": "assistant", "content": "...", "tool_calls": [...]}

DeepSeek thinking-mode adds a non-standard sibling field `reasoning_content`
that the model REQUIRES to be echoed back when the same conversation continues
into another assistant turn. This module gives you safe converters in both directions
that preserve the bug-fix-relevant fields and warn loudly when something is dropped.
"""

from __future__ import annotations

from typing import Any

from .reasoning import ReasoningLifecycle


def to_deepseek_history(openai_messages: list[dict]) -> list[dict]:
    """Pass-through that asserts the invariants DeepSeek cares about.

    - If the LAST assistant message has `tool_calls` but no `reasoning_content`
      AND we are mid-loop (next role is `tool`), this WILL 400 on the next call.
      We do not auto-invent reasoning_content (that would be lying to the model);
      instead we mark the message with `_dsk_kit_warning` so the caller can decide.
    """
    out: list[dict] = []
    for i, msg in enumerate(openai_messages):
        m = dict(msg)
        if m.get("role") == "assistant" and m.get("tool_calls"):
            next_role = openai_messages[i + 1].get("role") if i + 1 < len(openai_messages) else None
            if next_role == "tool" and not m.get("reasoning_content"):
                m["_dsk_kit_warning"] = (
                    "missing reasoning_content on tool-call assistant turn — DeepSeek will 400"
                )
        out.append(m)
    return out


def strip_kit_warnings(messages: list[dict]) -> list[dict]:
    """Remove `_dsk_kit_warning` fields before sending; DeepSeek would reject unknown keys silently."""
    return [{k: v for k, v in m.items() if not k.startswith("_dsk_kit_")} for m in messages]


def from_deepseek_response(resp: Any) -> dict:
    """Turn a DeepSeek ChatCompletion into the OpenAI-assistant-message shape, but PRESERVE reasoning_content.

    Output is suitable for `messages.append(...)` in any OpenAI-style agent loop.
    """
    choice = resp.choices[0]
    msg = choice.message
    out: dict[str, Any] = {
        "role": "assistant",
        "content": getattr(msg, "content", None),
    }
    if getattr(msg, "tool_calls", None):
        out["tool_calls"] = [
            {
                "id": tc.id,
                "type": tc.type,
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                },
            }
            for tc in msg.tool_calls
        ]
    rc = getattr(msg, "reasoning_content", None)
    if rc:
        out["reasoning_content"] = rc
    out["_dsk_kit_finish_reason"] = choice.finish_reason
    return out


def prepare_for_new_user_turn(history: list[dict]) -> list[dict]:
    """Wipe reasoning_content on prior assistant messages once a new user turn begins.

    Keeping it across turns is harmful: it bloats the prefix AND its non-determinism
    breaks byte-for-byte cache matching. See `cache.estimate_cache_hit`.
    """
    out = [dict(m) for m in history]
    ReasoningLifecycle.on_new_user_turn(out)
    return out
