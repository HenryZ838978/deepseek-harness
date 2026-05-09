"""Salvage tool calls that DeepSeek leaks into `content` instead of `tool_calls`.

Field-truth from social-media + issues (deepseek-ai/DeepSeek-V3#1244,
NousResearch/hermes-agent#15453):

  ~11% of multi-turn tool-use requests on V4-Pro come back with::

      finish_reason = "stop"      # NOT "tool_calls"
      tool_calls    = None
      content       = "<｜DSML｜tool_calls>...</｜DSML｜>"   # raw DSML markers
                    | '{"name": "search", "arguments": {...}}'  # bare JSON
                    | '<tool_call>{"name": "...", "arguments": ...}</tool_call>'

The salvage strategy:

  1. If `finish_reason in ('stop', 'length')` AND `content` matches one of the
     known leaked tool-call shapes → re-parse, synthesise a `tool_calls` list,
     wipe the leaked content, and tag the message so the caller knows we did this.
  2. Be conservative: never salvage if we can't fully parse arguments JSON —
     that path is the strict-mode corruption, handled separately.
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

# DSML markers shipped by DeepSeek tokenizer (the unicode pipe is U+FF5C).
_DSML_OPEN = "<｜DSML｜tool_calls"
_DSML_CLOSE = "</｜DSML｜tool_calls>"

_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL),
    re.compile(r"<\｜DSML\｜tool_calls.*?>(.*?)</\｜DSML\｜tool_calls>", re.DOTALL),
    re.compile(r"```json\s*(\{[^`]*\"name\"[^`]*\})\s*```", re.DOTALL),
]

# Fallback: a raw JSON object with both "name" and "arguments".
_BARE_JSON = re.compile(r"\{\s*\"name\"\s*:\s*\"[^\"]+\"\s*,\s*\"arguments\"\s*:\s*[^}]+\}", re.DOTALL)


def salvage_tool_calls_from_content(
    content: str | None,
    finish_reason: str | None,
) -> tuple[list[dict] | None, str | None, str | None]:
    """Try to recover tool_calls leaked into `content`.

    Returns:
        (tool_calls, residual_content, salvage_reason)
        - tool_calls: list of OpenAI-shaped tool_call dicts, or None if no salvage
        - residual_content: content with the tool-call markup stripped, or None if all consumed
        - salvage_reason: short string describing which pattern matched, or None
    """
    if not content:
        return None, content, None
    if finish_reason not in ("stop", "length", None):
        return None, content, None

    # 1) Try structured patterns first
    for pat in _PATTERNS:
        match = pat.search(content)
        if not match:
            continue
        payload = match.group(1).strip()
        parsed = _try_parse_tool_call_blob(payload)
        if parsed is None:
            continue
        residual = (content[: match.start()] + content[match.end():]).strip() or None
        return parsed, residual, f"pattern:{pat.pattern[:30]}"

    # 2) Fallback: bare JSON object with name+arguments at any position.
    #    Regex can't handle balanced braces, so we do a manual brace-walker
    #    starting from each `{"name"` occurrence.
    for start in _iter_brace_candidates(content):
        end = _match_balanced_brace(content, start)
        if end is None:
            continue
        candidate = content[start:end]
        if "\"arguments\"" not in candidate or "\"name\"" not in candidate:
            continue
        parsed = _try_parse_tool_call_blob(candidate)
        if parsed is not None:
            residual = (content[:start] + content[end:]).strip() or None
            return parsed, residual, "pattern:bare-json"

    return None, content, None


def _iter_brace_candidates(text: str):
    idx = 0
    while True:
        idx = text.find("{", idx)
        if idx == -1:
            return
        yield idx
        idx += 1


def _match_balanced_brace(text: str, start: int) -> int | None:
    """Return index AFTER the matching closing brace, respecting strings + escapes."""
    if start >= len(text) or text[start] != "{":
        return None
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == "\"":
                in_str = False
            continue
        if ch == "\"":
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i + 1
    return None


def _try_parse_tool_call_blob(payload: str) -> list[dict] | None:
    """Accept either a single tool_call JSON or a JSON array of tool_calls."""
    try:
        obj = json.loads(payload)
    except json.JSONDecodeError:
        return None

    if isinstance(obj, dict):
        obj = [obj]
    if not isinstance(obj, list):
        return None

    out: list[dict] = []
    for item in obj:
        if not isinstance(item, dict):
            return None
        name = item.get("name") or item.get("function", {}).get("name")
        args = item.get("arguments") or item.get("function", {}).get("arguments")
        if not name:
            return None
        if isinstance(args, (dict, list)):
            args_str = json.dumps(args, ensure_ascii=False)
        elif isinstance(args, str):
            args_str = args
        else:
            args_str = "{}"
        out.append(
            {
                "id": item.get("id") or f"call_{uuid.uuid4().hex[:12]}",
                "type": "function",
                "function": {"name": name, "arguments": args_str},
            }
        )
    return out or None


def detect_strict_mode_corruption(arguments_str: str) -> bool:
    """Return True if the arguments string exhibits the #1069 'missing closing quote on first key' bug.

    Heuristic: a JSON object whose first key starts with `"` but the closing
    `"` before the colon is missing. We re-tokenise minimally rather than
    relying on json.loads (which just throws).
    """
    s = arguments_str.lstrip()
    if not s.startswith("{"):
        return False
    # find first `:`
    colon = s.find(":")
    if colon == -1:
        return False
    head = s[1:colon]  # text between `{` and `:`
    # count `"` in head; well-formed first-key has exactly 2.
    return head.count("\"") == 1
