"""Drop-in OpenAI-compat client for DeepSeek V4-Pro / V4-Flash with all known protocol salvages enabled.

Replace::

    from openai import OpenAI
    client = OpenAI(api_key=..., base_url="https://api.deepseek.com")

with::

    from deepseek_harness import DeepSeekHarness
    client = DeepSeekHarness(api_key=..., base_url="https://api.deepseek.com")

The surface is `client.chat.completions.create(...)` — same as OpenAI — but every
response goes through:

  - `from_deepseek_response`  (preserves reasoning_content on the message dict)
  - `salvage_tool_calls_from_content`  (rescues 11% leaked tool calls)
  - `normalize_usage`  (back-fills both cache-hit field shapes + cost estimate)

Streaming uses `stream_chat()` which absorbs reasoning chunks via `ReasoningLifecycle`
and tolerates the empty-final-chunk shape (cline #1594).
"""

from __future__ import annotations

import os
from typing import Any, Iterator

from openai import OpenAI

from .cache import normalize_usage
from .exceptions import StreamShapeError, ToolCallLeakageError
from .normalize import from_deepseek_response, strip_kit_warnings, to_deepseek_history
from .reasoning import ReasoningLifecycle
from .tool_calls import salvage_tool_calls_from_content


class DeepSeekHarness:
    """Thin wrapper around `openai.OpenAI` with DeepSeek V4-specific safety guards.

    Implements the 10 contract rules documented in `spec/` and validated by the
    16 probes in `reports/`. See `__init__.py` for the public re-export.
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        *,
        salvage_tool_calls: bool = True,
        normalize_cache_fields: bool = True,
        warn_on_missing_reasoning: bool = True,
        disable_thinking_by_default: bool = False,
        raw_dump_path: str | None = None,
    ) -> None:
        """Construct a DeepSeek-aware OpenAI-compatible client.

        Args:
            disable_thinking_by_default: If True, every request gets
              `extra_body={"thinking":{"type":"disabled"}}` UNLESS the caller
              explicitly passes their own `extra_body`. Recommended for cost-
              sensitive deployments because `deepseek-v4-pro` defaults to
              thinking-enabled (probe_0 finding 2026-05-09: ~30 reasoning
              tokens are billed even on trivial prompts).
        """
        self._oai = OpenAI(
            api_key=api_key or os.getenv("DEEPSEEK_API_KEY"),
            base_url=base_url or os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        )
        self._salvage = salvage_tool_calls
        self._normalize_cache = normalize_cache_fields
        self._warn = warn_on_missing_reasoning
        self._disable_thinking = disable_thinking_by_default
        self._raw_dump = raw_dump_path

    def _maybe_inject_thinking_off(self, kwargs: dict) -> dict:
        if self._disable_thinking and "extra_body" not in kwargs:
            kwargs = dict(kwargs)
            kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
        return kwargs

    # ------------------------------------------------------------------
    # Non-streaming
    # ------------------------------------------------------------------
    def chat(
        self,
        *,
        model: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        tool_choice: str | dict | None = None,
        **kwargs: Any,
    ) -> dict:
        """Returns a dict with keys:
            message:      OpenAI-shaped assistant message (incl. reasoning_content if any)
            usage:        normalised usage (both cache-field shapes filled in)
            finish_reason: passthrough
            salvage:      None if no tool-call salvage happened, else {pattern, original_content}
            raw:          the raw SDK response (for debugging)
        """
        normalized_in = strip_kit_warnings(to_deepseek_history(messages))
        kwargs = self._maybe_inject_thinking_off(kwargs)
        resp = self._oai.chat.completions.create(
            model=model,
            messages=normalized_in,
            tools=tools,
            tool_choice=tool_choice,
            **kwargs,
        )

        msg = from_deepseek_response(resp)
        finish_reason = msg.pop("_dsk_kit_finish_reason", None)
        salvage = None

        if self._salvage and not msg.get("tool_calls"):
            tool_calls, residual, reason = salvage_tool_calls_from_content(
                msg.get("content"), finish_reason
            )
            if tool_calls is not None:
                salvage = {
                    "pattern": reason,
                    "original_content": msg.get("content"),
                }
                msg["tool_calls"] = tool_calls
                msg["content"] = residual

        usage = normalize_usage(getattr(resp, "usage", None)) if self._normalize_cache else None

        return {
            "message": msg,
            "usage": usage,
            "finish_reason": finish_reason,
            "salvage": salvage,
            "raw": resp,
        }

    # ------------------------------------------------------------------
    # Streaming
    # ------------------------------------------------------------------
    def stream_chat(
        self,
        *,
        model: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        tool_choice: str | dict | None = None,
        **kwargs: Any,
    ) -> Iterator[dict]:
        """Yields **structured events** (not raw chunks) so callers don't have to re-implement
        the cline #1594 / hermes #15353 mitigations.

        Event types:
          {"type": "content_delta",   "data": str}
          {"type": "reasoning_delta", "data": str}
          {"type": "tool_call_delta", "data": {"index": int, "id": str|None, "name": str|None, "arguments": str}}
          {"type": "done", "message": {...}, "usage": {...}, "finish_reason": str, "salvage": dict|None}
        """
        normalized_in = strip_kit_warnings(to_deepseek_history(messages))
        kwargs = self._maybe_inject_thinking_off(kwargs)
        stream = self._oai.chat.completions.create(
            model=model,
            messages=normalized_in,
            tools=tools,
            tool_choice=tool_choice,
            stream=True,
            stream_options={"include_usage": True},
            **kwargs,
        )

        rl = ReasoningLifecycle()
        content_buf: list[str] = []
        tool_call_acc: dict[int, dict] = {}
        finish_reason: str | None = None
        usage_raw: Any | None = None

        for chunk in stream:
            choices = getattr(chunk, "choices", None) or []
            # DeepSeek emits a final chunk with empty choices but populated usage —
            # cline #1594 was the upstream bug from indexing into [0] blindly.
            if not choices:
                if getattr(chunk, "usage", None) is not None:
                    usage_raw = chunk.usage
                continue

            choice = choices[0]
            delta = getattr(choice, "delta", None)
            if delta is None:
                # malformed chunk — neither delta nor finish_reason; skip rather than throw
                continue

            # reasoning_content goes through the lifecycle helper (also yields out for visibility)
            rc = getattr(delta, "reasoning_content", None)
            if rc:
                rl.absorb_chunk(chunk)
                yield {"type": "reasoning_delta", "data": rc}

            content_piece = getattr(delta, "content", None)
            if content_piece:
                content_buf.append(content_piece)
                yield {"type": "content_delta", "data": content_piece}

            for tc in getattr(delta, "tool_calls", None) or []:
                idx = getattr(tc, "index", 0)
                slot = tool_call_acc.setdefault(
                    idx, {"id": None, "name": None, "arguments": ""}
                )
                if getattr(tc, "id", None):
                    slot["id"] = tc.id
                fn = getattr(tc, "function", None)
                if fn is not None:
                    if getattr(fn, "name", None):
                        slot["name"] = fn.name
                    if getattr(fn, "arguments", None):
                        slot["arguments"] += fn.arguments
                yield {
                    "type": "tool_call_delta",
                    "data": {
                        "index": idx,
                        "id": slot["id"],
                        "name": slot["name"],
                        "arguments": slot["arguments"],
                    },
                }

            if getattr(choice, "finish_reason", None):
                finish_reason = choice.finish_reason

        content_str = "".join(content_buf) or None
        message: dict[str, Any] = {"role": "assistant", "content": content_str}
        if tool_call_acc:
            message["tool_calls"] = [
                {
                    "id": v["id"] or f"call_{i}",
                    "type": "function",
                    "function": {"name": v["name"] or "", "arguments": v["arguments"] or "{}"},
                }
                for i, v in sorted(tool_call_acc.items())
            ]
        message = rl.finalize_assistant_message(message)

        salvage = None
        if self._salvage and not message.get("tool_calls"):
            tool_calls, residual, reason = salvage_tool_calls_from_content(
                message.get("content"), finish_reason
            )
            if tool_calls is not None:
                salvage = {"pattern": reason, "original_content": message.get("content")}
                message["tool_calls"] = tool_calls
                message["content"] = residual

        usage = normalize_usage(usage_raw) if (self._normalize_cache and usage_raw) else None

        yield {
            "type": "done",
            "message": message,
            "usage": usage,
            "finish_reason": finish_reason,
            "salvage": salvage,
        }
