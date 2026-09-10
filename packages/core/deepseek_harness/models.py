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

# The two server-side canonical ids as of 2026-09-10. `GET /models` returns
# exactly these two, and an unknown id is rejected with an error whose message
# lists exactly these two ("The supported API model names are deepseek-flash,
# deepseek-v4-pro"). Everything below this block is a legacy alias.
DEEPSEEK_FLASH: Final[str] = "deepseek-flash"
DEEPSEEK_V4_PRO: Final[str] = "deepseek-v4-pro"

# Legacy ids, still accepted. On 2026-09-10 each of these was sent to the live
# endpoint and the response's `model` field came back as a canonical id above,
# not the requested string — the server silently re-points them:
#   deepseek-v4-flash, deepseek-v4-flash-vision-exp, deepseek-reasoner,
#   deepseek-chat  ->  deepseek-flash
# `deepseek-v4-pro` is stable (it maps to itself). Keep these constants so a
# caller pinned to an old id still resolves, but do not rely on them naming
# distinct behaviour: as of 2026-09-10 they are all `deepseek-flash`.
DEEPSEEK_V4_FLASH: Final[str] = "deepseek-v4-flash"
DEEPSEEK_REASONER: Final[str] = "deepseek-reasoner"
DEEPSEEK_V4_FLASH_VISION_EXP: Final[str] = "deepseek-v4-flash-vision-exp"


# Ordered tuple used by discovery / doctor output when a caller wants a list.
# Canonical ids first; the aliases follow for callers that pass one through.
KNOWN_MODELS: Final[tuple[str, ...]] = (
    DEEPSEEK_FLASH,
    DEEPSEEK_V4_PRO,
    DEEPSEEK_V4_FLASH,
    DEEPSEEK_REASONER,
    DEEPSEEK_V4_FLASH_VISION_EXP,
)


# Ids observed to accept `image_url` content parts on the live endpoint
# (2026-09-10): `deepseek-flash` allocates ~216 prompt tokens for a 64x64 PNG
# where the same text prompt is ~15, so the image is really decoded. The
# aliases resolve to it and accept images identically. `deepseek-v4-pro`
# accepts the request (HTTP 200) but charges only the text tokens (~90 for a
# two-part prompt), i.e. it silently drops the image part rather than
# rejecting it — do NOT route images to it.
_VISION_CAPABLE: Final[frozenset[str]] = frozenset({
    DEEPSEEK_FLASH,
    DEEPSEEK_V4_FLASH,
    DEEPSEEK_REASONER,
    DEEPSEEK_V4_FLASH_VISION_EXP,
})


def supports_image_input(model_id: str) -> bool:
    """Return True when the given model id accepts image content parts.

    Unknown model ids default to False — the harness makes no assumptions.
    A caller can override the check for a private deployment by providing
    the model id explicitly and calling the vision path directly.
    """
    return model_id in _VISION_CAPABLE
