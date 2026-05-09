"""reasoning_content lifecycle manager.

DeepSeek V4 / V3.2 in thinking-mode requires every assistant message that we feed
back into a multi-turn loop to carry its **original** `reasoning_content` field.
If we drop it (which every "OpenAI-only" agent framework does, because it is
non-standard), the next request returns:

    HTTP 400: "The reasoning_content in the thinking mode must be passed back to the API"

References:
    microsoft/agent-framework#5538
    NousResearch/hermes-agent#15353
    cline/cline PR #7888 — `addReasoningContent` + `isNextGenModelProvider` (gold standard)

Rules (from cline #7888 reverse-engineering + our probes):
    1. Persist `reasoning_content` on every assistant message that **also** has
       a tool_call OR is consumed by another tool_call in the SAME user turn.
    2. **Clear** `reasoning_content` from history once a NEW user message arrives —
       the server stops requiring it across turn boundaries.
    3. While streaming, `reasoning_content` may arrive on chunks that do **not** carry
       any text content. Ignore-on-empty is wrong; accumulate the empty-string too.
"""

from __future__ import annotations

from typing import Any, Iterable


class ReasoningLifecycle:
    """Stateful tracker for reasoning_content in an agent loop.

    Usage::

        rl = ReasoningLifecycle()
        for chunk in stream:
            rl.absorb_chunk(chunk)
        assistant_msg = rl.finalize_assistant_message(base_msg)
        history.append(assistant_msg)

        # When user sends new turn:
        rl.on_new_user_turn(history)
    """

    def __init__(self) -> None:
        self._buf: list[str] = []
        self._saw_any_chunk: bool = False

    def absorb_chunk(self, chunk: Any) -> None:
        """Pull reasoning_content delta out of a streaming chunk.

        Tolerates: chunk.choices missing, chunk.choices empty, delta missing,
        delta.reasoning_content None — all of which DeepSeek emits in the wild.
        """
        try:
            choices = getattr(chunk, "choices", None) or chunk.get("choices") if isinstance(chunk, dict) else getattr(chunk, "choices", None)
        except Exception:
            choices = None
        if not choices:
            return
        choice = choices[0]
        delta = getattr(choice, "delta", None)
        if delta is None and isinstance(choice, dict):
            delta = choice.get("delta")
        if delta is None:
            return
        rc = getattr(delta, "reasoning_content", None)
        if rc is None and isinstance(delta, dict):
            rc = delta.get("reasoning_content")
        if rc is None:
            return
        self._saw_any_chunk = True
        self._buf.append(rc)

    def finalize_assistant_message(self, base_msg: dict) -> dict:
        """Attach accumulated reasoning_content to an assistant message dict.

        `base_msg` is the OpenAI-shaped message you would normally store
        (role, content, tool_calls). We add `reasoning_content` if we saw any.
        """
        out = dict(base_msg)
        if self._saw_any_chunk:
            out["reasoning_content"] = "".join(self._buf)
        return out

    def reset(self) -> None:
        self._buf.clear()
        self._saw_any_chunk = False

    @staticmethod
    def on_new_user_turn(history: list[dict]) -> None:
        """Strip reasoning_content from prior assistant messages once the user sends new input.

        DeepSeek does not require it across turn boundaries, and keeping it bloats
        the prefix (which kills cache-hit byte-for-byte equality if the field is
        non-deterministic — and it IS non-deterministic with sampling).
        """
        for msg in history:
            if msg.get("role") == "assistant" and "reasoning_content" in msg:
                msg.pop("reasoning_content", None)

    @staticmethod
    def must_carry(history: Iterable[dict]) -> bool:
        """True iff the LAST assistant message in history has a tool_call,
        i.e. we are mid-loop and the next request MUST echo reasoning_content back.
        """
        last_assistant = None
        for msg in history:
            if msg.get("role") == "assistant":
                last_assistant = msg
        if not last_assistant:
            return False
        return bool(last_assistant.get("tool_calls"))
