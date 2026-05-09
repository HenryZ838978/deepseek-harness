"""Typed errors so callers can branch on the specific quirk that fired."""


class HarnessError(Exception):
    """Base for every protocol-quirk we detect."""


class ReasoningContentMissingError(HarnessError):
    """Server returned 400 because the previous turn's reasoning_content was not echoed back.

    Reference: microsoft/agent-framework#5538, NousResearch/hermes-agent#15353.
    Probe: reports/probes/probe_2_reasoning_lifecycle.py (3/3 reproduction on V4-Pro).
    """


class ToolCallLeakageError(HarnessError):
    """finish_reason='stop' but content carried a DSML / JSON tool call payload.

    Reference: deepseek-ai/DeepSeek-V3#1244, NousResearch/hermes-agent#15453.
    Probe: reports/probes/probe_3_tool_call_leakage.py (0/50 on V4 official endpoint).
    """


class StrictModeCorruptionError(HarnessError):
    """beta/strict path produced unparseable JSON (missing quote on first key).

    Reference: deepseek-ai/DeepSeek-V3#1069 (closed as not-planned).
    Probe: reports/probes/probe_4_strict_mode_corruption.py (0/32 on V4 series).
    """


class StreamShapeError(HarnessError):
    """Final SSE chunk lacked `choices`, or `delta` was undefined where indexed.

    Reference: cline/cline#1594.
    """
