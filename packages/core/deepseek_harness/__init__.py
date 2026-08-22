"""deepseek-harness · core — protocol-aware client for DeepSeek V4-Pro / V4-Flash / Vision.

Validated by 16 probes documented in `reports/REPORT_2026-05-09.md`;
multimodal contract added in `spec/07_multimodal.md` (2026-08-22).

Public API::

    from deepseek_harness import DeepSeekHarness, normalize_usage, estimate_cache_hit
    from deepseek_harness import DEEPSEEK_V4_FLASH_VISION_EXP, estimate_image_tokens
"""

from .client import DeepSeekHarness
from .cache import estimate_cache_hit, normalize_usage, estimate_image_tokens
from .reasoning import ReasoningLifecycle
from .tool_calls import salvage_tool_calls_from_content
from .normalize import assert_multimodal_shape
from .models import (
    DEEPSEEK_V4_PRO,
    DEEPSEEK_V4_FLASH,
    DEEPSEEK_REASONER,
    DEEPSEEK_V4_FLASH_VISION_EXP,
    KNOWN_MODELS,
    supports_image_input,
)
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
    "assert_multimodal_shape",
    "estimate_cache_hit",
    "normalize_usage",
    "estimate_image_tokens",
    "DEEPSEEK_V4_PRO",
    "DEEPSEEK_V4_FLASH",
    "DEEPSEEK_REASONER",
    "DEEPSEEK_V4_FLASH_VISION_EXP",
    "KNOWN_MODELS",
    "supports_image_input",
    "HarnessError",
    "DeepSeekKitError",
    "ReasoningContentMissingError",
    "ToolCallLeakageError",
    "StrictModeCorruptionError",
    "StreamShapeError",
]

__version__ = "0.3.0"
