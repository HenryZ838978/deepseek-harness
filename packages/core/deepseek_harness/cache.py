"""Cache-hit field bridging + a local prefix-cache estimator.

Two concrete pains:

1. Field naming mismatch (pi-mono#3880):
   - DeepSeek puts cache-hit token count in `usage.prompt_cache_hit_tokens`
   - OpenAI puts it in   `usage.prompt_tokens_details.cached_tokens`
   - Vanilla OpenAI parsers see 0% cache hit even when DeepSeek is happily charging
     you the cached price. `normalize_usage()` below back-fills both fields.

2. The DeepSeek cache only triggers on **byte-for-byte prefix match starting from
   token 0**, with a practical minimum prefix of ~1024 tokens. `estimate_cache_hit()`
   is a local pre-flight estimator: feed it the messages you are about to send +
   the prefix you saw "stick" in the previous request, and it tells you the longest
   common prefix in tokens.

References:
    deepseek-ai/DeepSeek-V3#1261 (V3.2→V4 cache hit rate regression 92%→35%)
    pi-mono#3880 (field mismatch fix)
    DeepSeek docs: https://api-docs.deepseek.com/guides/kv_cache
"""

from __future__ import annotations

from typing import Any

try:
    import tiktoken
except ImportError:  # pragma: no cover
    tiktoken = None


# DeepSeek V4-Flash quoted prices, USD per million tokens.
PRICE_PER_M_INPUT_MISS = 0.14
PRICE_PER_M_INPUT_HIT = 0.0028
PRICE_PER_M_OUTPUT = 0.28


def normalize_usage(usage: dict | Any) -> dict:
    """Return a dict that has BOTH field shapes filled in.

    Accepts the raw `usage` dict from a DeepSeek response (or an OpenAI usage object).
    Output always includes:
        - prompt_cache_hit_tokens (int)
        - prompt_cache_miss_tokens (int)
        - prompt_tokens_details.cached_tokens (int)   # OpenAI shape
        - completion_tokens, prompt_tokens, total_tokens (passthrough)
        - estimated_cost_usd (float, V4-Flash pricing)
    """
    if usage is None:
        return {}
    u = _to_dict(usage)

    prompt_total = int(u.get("prompt_tokens") or 0)
    completion = int(u.get("completion_tokens") or 0)

    # DeepSeek native field
    hit = u.get("prompt_cache_hit_tokens")
    miss = u.get("prompt_cache_miss_tokens")

    # OpenAI shape
    details = u.get("prompt_tokens_details") or {}
    if isinstance(details, dict):
        cached_oa = details.get("cached_tokens")
    else:
        cached_oa = getattr(details, "cached_tokens", None)

    if hit is None and cached_oa is not None:
        hit = int(cached_oa)
        miss = max(prompt_total - hit, 0)
    elif hit is not None and cached_oa is None:
        cached_oa = int(hit)
    elif hit is None and cached_oa is None:
        hit, miss, cached_oa = 0, prompt_total, 0

    cost = (
        (miss / 1_000_000) * PRICE_PER_M_INPUT_MISS
        + (hit / 1_000_000) * PRICE_PER_M_INPUT_HIT
        + (completion / 1_000_000) * PRICE_PER_M_OUTPUT
    )

    return {
        "prompt_tokens": prompt_total,
        "completion_tokens": completion,
        "total_tokens": int(u.get("total_tokens") or (prompt_total + completion)),
        "prompt_cache_hit_tokens": int(hit),
        "prompt_cache_miss_tokens": int(miss),
        "prompt_tokens_details": {"cached_tokens": int(cached_oa)},
        "estimated_cost_usd": round(cost, 8),
        "cache_hit_rate": round(hit / prompt_total, 4) if prompt_total else 0.0,
    }


def _to_dict(obj: Any) -> dict:
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    if hasattr(obj, "__dict__"):
        return {k: v for k, v in obj.__dict__.items() if not k.startswith("_")}
    return {}


# ---------------------------------------------------------------------------
# Pre-flight estimator
# ---------------------------------------------------------------------------


def _encode(text: str) -> list[int]:
    if tiktoken is None:
        # crude byte-pair fallback so the kit still imports without tiktoken
        return list(text.encode("utf-8"))
    enc = tiktoken.get_encoding("cl100k_base")
    return enc.encode(text)


def estimate_cache_hit(
    new_messages: list[dict],
    previous_prefix_messages: list[dict] | None = None,
    *,
    minimum_prefix_tokens: int = 1024,
    cache_block_size: int = 256,
) -> dict:
    """Estimate how much of `new_messages` will be a cache hit on DeepSeek.

    DeepSeek's cache rule (validated by probe_5 on 2026-05-09):
      - prefix-from-0 match
      - bucketed by ~256-token blocks (cached tokens are always multiples of 256)
      - minimum prefix length to BEGIN caching ≈ 1024 tokens
      - tail edits preserve head cache; mid-prefix edits invalidate from the edit
        point onwards (NOT the entire prefix)

    We serialise both message lists deterministically (role + content + tool_calls
    + reasoning_content), tokenise with cl100k_base (close enough; DeepSeek
    tokenizer is ~3.6 chars/token for English ASCII vs cl100k's 4), and find the
    longest common token prefix, rounded DOWN to the nearest cache_block_size
    boundary. The estimator does NOT replace the server's truth — it is a
    pre-flight sanity check, e.g. "is my client about to invalidate the
    99-cent prefix by re-ordering tool messages?".
    """
    new_text = _serialize_messages(new_messages)
    prev_text = _serialize_messages(previous_prefix_messages or [])

    new_tokens = _encode(new_text)
    prev_tokens = _encode(prev_text)

    common = 0
    for a, b in zip(new_tokens, prev_tokens):
        if a != b:
            break
        common += 1

    if common < minimum_prefix_tokens:
        eligible = 0
    else:
        # Server rounds cached tokens DOWN to the nearest cache_block_size (256).
        eligible = (common // cache_block_size) * cache_block_size

    return {
        "common_prefix_tokens": common,
        "eligible_cached_tokens": eligible,
        "new_total_tokens": len(new_tokens),
        "estimated_hit_rate": round(eligible / len(new_tokens), 4) if new_tokens else 0.0,
        "minimum_prefix_threshold": minimum_prefix_tokens,
        "cache_block_size": cache_block_size,
        "explanation": (
            f"common < {minimum_prefix_tokens} → server will NOT cache this request"
            if common < minimum_prefix_tokens
            else f"ok — {eligible} tokens (rounded to {cache_block_size}-block) will be discounted at $0.0028/M"
        ),
    }


def _serialize_messages(messages: list[dict]) -> str:
    """Deterministic flattening used by both prefix estimator and cache-debug helpers.

    Layout mirrors OpenAI chat-completions JSON ordering: role → content → tool_calls
    → tool_call_id → reasoning_content. ANY field reorder by your agent code will
    bust the prefix.
    """
    parts: list[str] = []
    for msg in messages:
        parts.append(f"<role>{msg.get('role', '')}</role>")
        content = msg.get("content")
        if isinstance(content, list):
            for c in content:
                parts.append(f"<part>{c}</part>")
        elif content:
            parts.append(f"<content>{content}</content>")
        for tc in msg.get("tool_calls") or []:
            parts.append(f"<tc>{tc.get('id','')}|{tc.get('function',{}).get('name','')}|{tc.get('function',{}).get('arguments','')}</tc>")
        if msg.get("tool_call_id"):
            parts.append(f"<tcid>{msg['tool_call_id']}</tcid>")
        if msg.get("reasoning_content"):
            parts.append(f"<rc>{msg['reasoning_content']}</rc>")
    return "\n".join(parts)
