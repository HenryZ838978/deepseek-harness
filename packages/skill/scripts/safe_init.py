"""Drop-in safe init for DeepSeek V4-Pro / V4-Flash.

Single file. Zero deps beyond `openai`. Implements all 10 contract rules from
SKILL.md / spec/. Copy this into the user's project root.

Quick start::

    from safe_init import safe_deepseek_call
    msg = safe_deepseek_call(
        messages=[{"role": "user", "content": "hi"}],
        model="deepseek-v4-pro",
    )
    print(msg["content"], msg["_dsk_usage"]["estimated_cost_usd"])
"""
from __future__ import annotations

import os
from typing import Any, Iterator

from openai import OpenAI

# Optional: load .env if python-dotenv is available, otherwise silently skip.
try:
    from dotenv import load_dotenv as _ld  # type: ignore
    _ld()
except ImportError:
    pass

DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
HARD_CONTEXT_CEILING = 1_048_576           # validated by reports/probes/probe_6b
DEFAULT_MAX_TOKENS = 4096
THINKING_ENABLED = {"thinking": {"type": "enabled"}}
THINKING_DISABLED = {"thinking": {"type": "disabled"}}

_oai_client: OpenAI | None = None


def _client() -> OpenAI:
    global _oai_client
    if _oai_client is None:
        _oai_client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)
    return _oai_client


def safe_deepseek_call(
    *,
    messages: list[dict],
    model: str = "deepseek-v4-pro",
    tools: list[dict] | None = None,
    tool_choice: str | dict | None = None,
    enable_thinking: bool = False,
    max_tokens: int | None = None,
    temperature: float | None = None,
    stream: bool = False,
    **extra: Any,
) -> Any:
    """One call that satisfies all 10 contract rules.

    Returns:
      Non-streaming: assistant message dict ready for history append, with
        `reasoning_content` (if any) preserved + `_dsk_usage` and
        `_dsk_finish_reason` for inspection.
      Streaming:    iterator of structured events:
        {"type": "content_delta", "data": str}
        {"type": "reasoning_delta", "data": str}
        {"type": "tool_call_delta", "data": {index, id, name, arguments}}
        {"type": "done", "message": dict, "usage": dict, "finish_reason": str}
    """
    if max_tokens is None:
        max_tokens = DEFAULT_MAX_TOKENS
    extra_body = THINKING_ENABLED if enable_thinking else THINKING_DISABLED
    extra_body = {**extra_body, **(extra.pop("extra_body", None) or {})}

    create_kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "extra_body": extra_body,
        **extra,
    }
    if tools is not None:
        create_kwargs["tools"] = tools
    if tool_choice is not None:
        create_kwargs["tool_choice"] = tool_choice
    if temperature is not None:
        create_kwargs["temperature"] = temperature

    if stream:
        create_kwargs["stream"] = True
        create_kwargs["stream_options"] = {"include_usage": True}
        return _stream_iter(create_kwargs)

    resp = _client().chat.completions.create(**create_kwargs)
    msg = resp.choices[0].message
    out: dict = {"role": "assistant", "content": msg.content}
    if msg.tool_calls:
        out["tool_calls"] = [
            {
                "id": tc.id,
                "type": tc.type,
                "function": {"name": tc.function.name, "arguments": tc.function.arguments},
            }
            for tc in msg.tool_calls
        ]
    rc = getattr(msg, "reasoning_content", None)
    if rc:
        out["reasoning_content"] = rc
    out["_dsk_finish_reason"] = resp.choices[0].finish_reason
    out["_dsk_usage"] = _normalize_usage(getattr(resp, "usage", None))
    return out


def _stream_iter(create_kwargs: dict[str, Any]) -> Iterator[dict]:
    stream = _client().chat.completions.create(**create_kwargs)
    content_buf: list[str] = []          # list buffer (NOT str += chunk) — see Rule C5
    reasoning_buf: list[str] = []
    tool_call_acc: dict[int, dict] = {}  # dict-by-index (NOT list.append) — see Rule C4
    finish_reason: str | None = None
    usage_raw: Any | None = None

    for chunk in stream:
        choices = getattr(chunk, "choices", None) or []
        if not choices:                       # Rule C6
            if getattr(chunk, "usage", None) is not None:
                usage_raw = chunk.usage
            continue
        choice = choices[0]
        delta = getattr(choice, "delta", None)
        if delta is None:
            continue
        if rc := getattr(delta, "reasoning_content", None):
            reasoning_buf.append(rc)
            yield {"type": "reasoning_delta", "data": rc}
        if cc := getattr(delta, "content", None):
            content_buf.append(cc)
            yield {"type": "content_delta", "data": cc}
        for tc in (getattr(delta, "tool_calls", None) or []):
            idx = getattr(tc, "index", 0)
            slot = tool_call_acc.setdefault(idx, {"id": None, "name": None, "arguments": ""})
            if getattr(tc, "id", None):
                slot["id"] = tc.id
            fn = getattr(tc, "function", None)
            if fn is not None:
                if getattr(fn, "name", None):
                    slot["name"] = fn.name
                if getattr(fn, "arguments", None):
                    slot["arguments"] += fn.arguments
            yield {"type": "tool_call_delta", "data": {"index": idx, **slot}}
        if fr := getattr(choice, "finish_reason", None):
            finish_reason = fr

    message: dict = {"role": "assistant", "content": "".join(content_buf) or None}
    if tool_call_acc:
        message["tool_calls"] = [
            {"id": v["id"] or f"call_{i}", "type": "function",
             "function": {"name": v["name"] or "", "arguments": v["arguments"] or "{}"}}
            for i, v in sorted(tool_call_acc.items())
        ]
    if reasoning_buf:
        message["reasoning_content"] = "".join(reasoning_buf)

    yield {
        "type": "done",
        "message": message,
        "finish_reason": finish_reason,
        "usage": _normalize_usage(usage_raw),
    }


def _normalize_usage(usage_raw: Any) -> dict:
    """Bridge DeepSeek-native (`prompt_cache_hit_tokens`) and OpenAI-shape
    (`prompt_tokens_details.cached_tokens`) cache fields per spec §4."""
    if usage_raw is None:
        return {}
    u = usage_raw.model_dump() if hasattr(usage_raw, "model_dump") else dict(usage_raw)
    prompt = int(u.get("prompt_tokens") or 0)
    completion = int(u.get("completion_tokens") or 0)
    hit = u.get("prompt_cache_hit_tokens")
    details = u.get("prompt_tokens_details") or {}
    cached_oa = details.get("cached_tokens") if isinstance(details, dict) else None
    if hit is None and cached_oa is not None:
        hit = int(cached_oa)
    if cached_oa is None and hit is not None:
        cached_oa = int(hit)
    if hit is None:
        hit = 0
    if cached_oa is None:
        cached_oa = 0
    miss = u.get("prompt_cache_miss_tokens") or max(prompt - hit, 0)
    u["prompt_cache_hit_tokens"] = int(hit)
    u["prompt_cache_miss_tokens"] = int(miss)
    u["prompt_tokens_details"] = {"cached_tokens": int(cached_oa)}
    if prompt:
        u["cache_hit_rate"] = round(hit / prompt, 4)
        # V4-Flash pricing (USD per million tokens)
        PRICE_MISS, PRICE_HIT, PRICE_OUT = 0.14, 0.0028, 0.28
        u["estimated_cost_usd"] = round(
            miss / 1_000_000 * PRICE_MISS
            + hit / 1_000_000 * PRICE_HIT
            + completion / 1_000_000 * PRICE_OUT,
            8,
        )
    return u


def prepare_for_new_user_turn(history: list[dict]) -> list[dict]:
    """Strip reasoning_content from PRIOR assistant messages once a new user turn begins (rule C2 §2)."""
    return [
        ({k: v for k, v in m.items() if k != "reasoning_content"} if m.get("role") == "assistant" else dict(m))
        for m in history
    ]


def validate_history(messages: list[dict]) -> dict:
    """Audit a history for the 5 most common violations. Returns {ok, violations}."""
    issues = []
    for i, m in enumerate(messages):
        if (
            m.get("role") == "assistant"
            and m.get("tool_calls")
            and i + 1 < len(messages)
            and messages[i + 1].get("role") == "tool"
            and not m.get("reasoning_content")
        ):
            issues.append({"index": i, "rule": "C2",
                           "message": "tool-call assistant missing reasoning_content; will 400 with thinking on"})
        if m.get("role") not in ("system", "user", "assistant", "tool"):
            issues.append({"index": i, "rule": "schema", "message": f"unknown role '{m.get('role')}'"})
    return {"ok": not issues, "violations": issues}


# ---- self-test on direct invocation ----
if __name__ == "__main__":
    msg = safe_deepseek_call(
        messages=[{"role": "user", "content": "Reply with the single word PONG."}],
        max_tokens=4,
    )
    print("content:", msg["content"], "| usage:", msg["_dsk_usage"])
