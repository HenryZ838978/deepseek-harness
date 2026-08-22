"""Multimodal contract tests for 0.3.0 (spec/07)."""
from __future__ import annotations

import pytest

from deepseek_harness import (
    assert_multimodal_shape,
    estimate_cache_hit,
    estimate_image_tokens,
    KNOWN_MODELS,
    DEEPSEEK_V4_FLASH_VISION_EXP,
    supports_image_input,
)


def test_catalog_includes_vision():
    assert DEEPSEEK_V4_FLASH_VISION_EXP in KNOWN_MODELS
    assert supports_image_input(DEEPSEEK_V4_FLASH_VISION_EXP)
    assert not supports_image_input("deepseek-v4-flash")
    assert not supports_image_input("some-random-model")


def test_assert_multimodal_shape_passes_pure_text():
    assert_multimodal_shape([{"role": "user", "content": "hello"}])


def test_assert_multimodal_shape_accepts_valid_image_in_user_message():
    assert_multimodal_shape([{
        "role": "user",
        "content": [
            {"type": "text", "text": "describe:"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAA"}},
        ],
    }])


def test_assert_multimodal_shape_rejects_image_in_assistant_message():
    with pytest.raises(ValueError, match="allowed only in user messages"):
        assert_multimodal_shape([{
            "role": "assistant",
            "content": [{"type": "image_url", "image_url": {"url": "data:image/png;base64,AAA"}}],
        }])


def test_assert_multimodal_shape_rejects_image_in_tool_message():
    with pytest.raises(ValueError, match="allowed only in user messages"):
        assert_multimodal_shape([{
            "role": "tool",
            "tool_call_id": "x",
            "content": [{"type": "image_url", "image_url": {"url": "data:image/png;base64,AAA"}}],
        }])


def test_assert_multimodal_shape_rejects_empty_image_url():
    with pytest.raises(ValueError, match="image_url.url is required and non-empty"):
        assert_multimodal_shape([{
            "role": "user",
            "content": [{"type": "image_url", "image_url": {"url": ""}}],
        }])


def test_assert_multimodal_shape_rejects_text_part_without_text_field():
    with pytest.raises(ValueError, match="text part missing"):
        assert_multimodal_shape([{
            "role": "user",
            "content": [{"type": "text"}],
        }])


def test_estimate_image_tokens_low_detail_is_flat():
    # Measured baseline on 2026-08-22 against deepseek-v4-flash-vision-exp
    assert estimate_image_tokens(detail="low") == 186
    assert estimate_image_tokens(100, 100, detail="low") == 186
    assert estimate_image_tokens(200, 200, detail="low") == 186
    assert estimate_image_tokens(512, 512, detail="low") == 186


def test_estimate_image_tokens_scales_beyond_baseline():
    # 5-point size sweep against api.deepseek.com, 2026-08-22.
    # Piecewise anchors match measured server billing within a small margin.
    assert estimate_image_tokens(513, 513) == 270
    assert estimate_image_tokens(1000, 1000) == 270
    assert estimate_image_tokens(1024, 1024) == 270
    assert estimate_image_tokens(1500, 1500) == 418
    assert estimate_image_tokens(2048, 2048) == 418
    # Beyond the last anchor, plateau
    assert estimate_image_tokens(3000, 3000) == 418
    assert estimate_image_tokens(5000, 5000) == 418
    # Non-square uses the longer edge
    assert estimate_image_tokens(2000, 300) == 418


def test_normalize_usage_passes_reasoning_tokens_through():
    from deepseek_harness import normalize_usage
    # Vision + reasoner surface: reasoning_tokens under completion_tokens_details
    usage = {
        "prompt_tokens": 199, "completion_tokens": 64, "total_tokens": 263,
        "prompt_tokens_details": {"cached_tokens": 0},
        "completion_tokens_details": {"reasoning_tokens": 40},
        "prompt_cache_hit_tokens": 0, "prompt_cache_miss_tokens": 199,
    }
    out = normalize_usage(usage)
    assert out["completion_tokens_details"] == {"reasoning_tokens": 40}
    # legacy fields still normal
    assert out["prompt_tokens"] == 199
    assert out["prompt_cache_hit_tokens"] == 0


def test_normalize_usage_omits_reasoning_when_absent():
    from deepseek_harness import normalize_usage
    usage = {"prompt_tokens": 10, "completion_tokens": 5}
    out = normalize_usage(usage)
    assert "completion_tokens_details" not in out


def test_estimate_cache_hit_treats_identical_images_as_shared_prefix():
    # Same image at same position → prefix estimator sees them as identical
    long_data_url = "data:image/png;base64," + "A" * 5000
    msgs = [{
        "role": "user",
        "content": [
            {"type": "text", "text": "describe:"},
            {"type": "image_url", "image_url": {"url": long_data_url}},
        ],
    }]
    # send exact same messages twice
    out = estimate_cache_hit(msgs, msgs, minimum_prefix_tokens=0)
    # Common prefix should cover the whole request, not be dominated by
    # base64 bytes (the placeholder canonicalises the URL)
    assert out["common_prefix_tokens"] == out["new_total_tokens"]


def test_estimate_cache_hit_different_images_break_prefix():
    url_a = "data:image/png;base64," + "A" * 100
    url_b = "data:image/png;base64," + "B" * 100
    msg_a = [{"role": "user", "content": [
        {"type": "text", "text": "describe:"},
        {"type": "image_url", "image_url": {"url": url_a}},
    ]}]
    msg_b = [{"role": "user", "content": [
        {"type": "text", "text": "describe:"},
        {"type": "image_url", "image_url": {"url": url_b}},
    ]}]
    out = estimate_cache_hit(msg_a, msg_b, minimum_prefix_tokens=0)
    # Common prefix should stop before the image (text part is identical
    # but image differs)
    assert out["common_prefix_tokens"] < out["new_total_tokens"]
