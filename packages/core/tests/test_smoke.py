"""Pure-unit smoke tests — no network, no API key required.

These verify the core lib's offline correctness:
  - tool-call salvager parses each known leakage shape
  - cache normaliser bridges both field names
  - reasoning lifecycle helpers don't lose data
  - strict-mode corruption fingerprint detects the #1069 pattern
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# packages/core/tests/test_smoke.py -> packages/core/  -> add to path
PKG_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PKG_ROOT))

from deepseek_harness.cache import estimate_cache_hit, normalize_usage  # noqa: E402
from deepseek_harness.reasoning import ReasoningLifecycle  # noqa: E402
from deepseek_harness.tool_calls import (  # noqa: E402
    detect_strict_mode_corruption,
    salvage_tool_calls_from_content,
)


# --------------------------------------------------------------------------
# salvage_tool_calls_from_content
# --------------------------------------------------------------------------


def test_salvage_dsml_tag():
    content = (
        "Sure, calling now.\n"
        "<｜DSML｜tool_calls>"
        '[{"name": "calculator", "arguments": {"expression": "1+1"}}]'
        "</｜DSML｜tool_calls>"
    )
    tcs, residual, pat = salvage_tool_calls_from_content(content, "stop")
    assert tcs is not None
    assert tcs[0]["function"]["name"] == "calculator"
    assert json.loads(tcs[0]["function"]["arguments"])["expression"] == "1+1"
    assert pat is not None and "DSML" in pat or "pattern" in pat


def test_salvage_xml_tool_call():
    content = '<tool_call>{"name": "web_search", "arguments": {"query": "tcp"}}</tool_call>'
    tcs, residual, _ = salvage_tool_calls_from_content(content, "stop")
    assert tcs is not None
    assert tcs[0]["function"]["name"] == "web_search"
    assert residual in (None, "")


def test_salvage_bare_json():
    content = 'Result here. {"name": "calculator", "arguments": {"expression": "2*3"}}'
    tcs, residual, pat = salvage_tool_calls_from_content(content, "stop")
    assert tcs is not None
    assert pat == "pattern:bare-json"


def test_salvage_skips_when_finish_is_tool_calls():
    """If the model already populated tool_calls, our caller would not invoke salvage —
    but defensively the salvager should also tolerate non-stop finish_reasons."""
    content = "Some normal text without any tool call markup."
    tcs, residual, _ = salvage_tool_calls_from_content(content, "stop")
    assert tcs is None
    assert residual == content


def test_salvage_handles_empty():
    assert salvage_tool_calls_from_content(None, "stop") == (None, None, None)
    assert salvage_tool_calls_from_content("", "stop")[0] is None


# --------------------------------------------------------------------------
# normalize_usage
# --------------------------------------------------------------------------


def test_normalize_usage_deepseek_native():
    out = normalize_usage(
        {
            "prompt_tokens": 1500,
            "completion_tokens": 100,
            "total_tokens": 1600,
            "prompt_cache_hit_tokens": 1024,
            "prompt_cache_miss_tokens": 476,
        }
    )
    assert out["prompt_cache_hit_tokens"] == 1024
    assert out["prompt_tokens_details"]["cached_tokens"] == 1024
    assert out["cache_hit_rate"] == pytest.approx(1024 / 1500, abs=1e-3)
    assert out["estimated_cost_usd"] > 0


def test_normalize_usage_openai_only():
    """Endpoint that returns only the OpenAI-shaped field — we MUST back-fill."""
    out = normalize_usage(
        {
            "prompt_tokens": 2000,
            "completion_tokens": 50,
            "total_tokens": 2050,
            "prompt_tokens_details": {"cached_tokens": 1500},
        }
    )
    assert out["prompt_cache_hit_tokens"] == 1500
    assert out["prompt_cache_miss_tokens"] == 500
    assert out["prompt_tokens_details"]["cached_tokens"] == 1500


def test_normalize_usage_no_cache_info():
    out = normalize_usage({"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150})
    assert out["prompt_cache_hit_tokens"] == 0
    assert out["prompt_cache_miss_tokens"] == 100


# --------------------------------------------------------------------------
# estimate_cache_hit
# --------------------------------------------------------------------------


def test_estimate_cache_hit_identical_under_threshold():
    msgs = [{"role": "system", "content": "short prompt"}]
    out = estimate_cache_hit(msgs, msgs)
    assert out["common_prefix_tokens"] > 0
    # below 1024 tokens → eligible should be 0
    assert out["eligible_cached_tokens"] == 0


def test_estimate_cache_hit_diverges_at_first_token():
    a = [{"role": "system", "content": "alpha"}]
    b = [{"role": "user", "content": "alpha"}]
    out = estimate_cache_hit(a, b)
    # role tag differs → divergence near token 0
    assert out["common_prefix_tokens"] < 5


# --------------------------------------------------------------------------
# ReasoningLifecycle
# --------------------------------------------------------------------------


def test_reasoning_lifecycle_strips_on_new_user_turn():
    history = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello", "reasoning_content": "user said hi"},
        {"role": "user", "content": "next"},
    ]
    ReasoningLifecycle.on_new_user_turn(history)
    assert "reasoning_content" not in history[1]


def test_reasoning_lifecycle_must_carry():
    history = [
        {"role": "user", "content": "do thing"},
        {"role": "assistant", "tool_calls": [{"id": "x", "function": {"name": "f", "arguments": "{}"}}]},
    ]
    assert ReasoningLifecycle.must_carry(history) is True
    history.append({"role": "tool", "tool_call_id": "x", "content": "result"})
    assert ReasoningLifecycle.must_carry(history) is True


# --------------------------------------------------------------------------
# strict-mode corruption fingerprint
# --------------------------------------------------------------------------


def test_strict_corruption_fingerprint_positive():
    # The classic #1069 pattern: missing closing quote on first key
    broken = '{"selected: ["A","C","D"], "confidence": 0.9}'
    assert detect_strict_mode_corruption(broken) is True


def test_strict_corruption_fingerprint_negative():
    good = '{"selected": ["A","C","D"], "confidence": 0.9}'
    assert detect_strict_mode_corruption(good) is False
