"""Canonical DeepSeek model identifiers this harness has validated against.

Kept as a flat module of `Final[str]` constants (not an Enum) so callers pass
the raw string to any OpenAI-compatible SDK without importing this file.

The list is deliberately not exhaustive of DeepSeek's catalog: it names only
the model ids we have exercised through the harness contract (`spec/`) and
whose behaviour we track in `HISTORY.md`. Passing an unknown model id to
`DeepSeekHarness.chat` is not an error; it just means the harness makes no
protocol guarantees about it.

Add a new entry only after §01–§07 have been re-verified against the model.
"""
from __future__ import annotations

from typing import Final

# Text-only chat models. §01–§06 apply.
DEEPSEEK_V4_PRO: Final[str] = "deepseek-v4-pro"
DEEPSEEK_V4_FLASH: Final[str] = "deepseek-v4-flash"

# Reasoner (thinking mode). §01 (reasoning_content lifecycle) is critical.
DEEPSEEK_REASONER: Final[str] = "deepseek-reasoner"

# Vision-capable (added 2026-08-22, tracks @deepseek-ai/dsh 0.1.1-rc.2 catalog).
# §07 (multimodal contract) applies. Experimental — DeepSeek has flagged it
# as a preview; the model id itself carries the `-exp` suffix.
DEEPSEEK_V4_FLASH_VISION_EXP: Final[str] = "deepseek-v4-flash-vision-exp"


# Ordered tuple used by discovery / doctor output when a caller wants a list.
KNOWN_MODELS: Final[tuple[str, ...]] = (
    DEEPSEEK_V4_PRO,
    DEEPSEEK_V4_FLASH,
    DEEPSEEK_REASONER,
    DEEPSEEK_V4_FLASH_VISION_EXP,
)


def supports_image_input(model_id: str) -> bool:
    """Return True when the given model id is a vision-capable one in this catalog.

    Unknown model ids default to False — the harness makes no assumptions.
    A caller can override the check for a private deployment by providing
    the model id explicitly and calling the vision path directly.
    """
    return model_id == DEEPSEEK_V4_FLASH_VISION_EXP
