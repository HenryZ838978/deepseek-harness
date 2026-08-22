"""Bidirectional normalisation between OpenAI-shaped and DeepSeek-shaped messages.

Most agent frameworks store assistant messages in a strictly OpenAI shape:

    {"role": "assistant", "content": "...", "tool_calls": [...]}

DeepSeek thinking-mode adds a non-standard sibling field `reasoning_content`
that the model REQUIRES to be echoed back when the same conversation continues
into another assistant turn. This module gives you safe converters in both directions
that preserve the bug-fix-relevant fields and warn loudly when something is dropped.

Multimodal content (added in 0.4.0 for `deepseek-v4-flash-vision-exp`):
`content` may be a `str` (text-only, historical) OR a `list[dict]` of OpenAI
content parts:

    [{"type": "text", "text": "describe:"},
     {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}]

Both shapes pass through this module unchanged; multimodal-only invariants
(image_url required for `type: image_url`, allowed roles per DeepSeek's vision
route) are enforced by `assert_multimodal_shape` when the caller opts in.
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
    - Multimodal content (`content: list[dict]`) is passed through unchanged.
      Call `assert_multimodal_shape` separately if the caller wants shape checks.
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


def assert_multimodal_shape(messages: list[dict]) -> None:
    """Enforce DeepSeek's multimodal message-shape invariants.

    Raises `ValueError` on the first violation with a message-index prefix.

    Rules (validated against `@deepseek-ai/dsh-llm-deepseek` 0.1.1-rc.2
    `serialize.ts::assertSupportedImageRoles`):
      - Only `user` messages may carry image content parts.
      - Each `type: image_url` part must have a non-empty `image_url.url`.
      - Each `type: text` part must have a `text` field (may be empty string).
      - Unknown part types are permitted but ignored downstream — no throw.
    """
    for i, msg in enumerate(messages):
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        has_image = any(isinstance(p, dict) and p.get("type") == "image_url" for p in content)
        if has_image and msg.get("role") != "user":
            raise ValueError(
                f"#{i} {msg.get('role')!r}: image_url content parts are allowed only in user messages "
                f"(DeepSeek chat/completions rejects otherwise)"
            )
        for j, part in enumerate(content):
            if not isinstance(part, dict):
                raise ValueError(f"#{i} part[{j}]: content parts must be dicts, got {type(part).__name__}")
            ptype = part.get("type")
            if ptype == "image_url":
                iu = part.get("image_url")
                if not isinstance(iu, dict) or not iu.get("url"):
                    raise ValueError(f"#{i} part[{j}]: image_url.url is required and non-empty")
            elif ptype == "text":
                if "text" not in part:
                    raise ValueError(f"#{i} part[{j}]: text part missing `text` field")


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
