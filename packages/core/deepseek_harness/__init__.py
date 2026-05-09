"""deepseek-harness · core — protocol-aware client for DeepSeek V4-Pro / V4-Flash.

Validated by 16 probes documented in `reports/REPORT_2026-05-09.md`.

Public API::

    from deepseek_harness import DeepSeekHarness, normalize_usage, estimate_cache_hit
"""

from .client import DeepSeekHarness
from .cache import estimate_cache_hit, normalize_usage
from .reasoning import ReasoningLifecycle
from .tool_calls import salvage_tool_calls_from_content
from .exceptions import (
    HarnessError,
    ReasoningContentMissingError,
    ToolCallLeakageError,
    StrictModeCorruptionError,
    StreamShapeError,
)

# Backwards-compatible alias (transitional, kept for one minor release).
DeepSeekClient = DeepSeekHarness
DeepSeekKitError = HarnessError

__all__ = [
    "DeepSeekHarness",
    "DeepSeekClient",
    "ReasoningLifecycle",
    "salvage_tool_calls_from_content",
    "estimate_cache_hit",
    "normalize_usage",
    "HarnessError",
    "DeepSeekKitError",
    "ReasoningContentMissingError",
    "ToolCallLeakageError",
    "StrictModeCorruptionError",
    "StreamShapeError",
]

__version__ = "0.2.0"
