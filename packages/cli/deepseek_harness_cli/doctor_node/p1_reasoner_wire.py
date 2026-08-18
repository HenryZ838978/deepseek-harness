"""P1 — reasoner-skip detector: how often does `deepseek-reasoner` skip
its reasoning stream on your tool prompt, and can you steer it?

Discovery timeline:
  - Evening 2026-08-17: single-shot observation of "reasoning_content silenced
    on tool turn" flipped between runs. Framed as "wire silence" and blamed
    on the harness's lack of a preserve-guard.
  - Overnight 2026-08-17→18: 200 trials, 5 prompt families × 4 temps,
    settle the picture:
      · silence rate correlates with PROMPT FAMILY, not temperature
      · "no_reason_ask" / "single_tool"        →  40–100% silent
      · "multi_tool" (complex)                  →   0–20% silent
      · "reasoning_hint" / "cot_forced"         →   0% silent every time
    Conclusion: `reasoning_content` absence is NOT a wire bug. The reasoner
    *decides* to skip its reasoning stream on prompts it deems trivial.
    A prompt that hints at CoT ("reason step by step") flips it back on.

Impact for dsh users:
  - The official Node harness surfaces nothing about this. A user whose
    thinking-mode history looks incomplete is likely the victim of their own
    prompt shape, not a wire defect.
  - This probe runs a small A/B — same tool, once with a bare user turn,
    once with a CoT hint — and reports whether flipping the hint changed
    the reasoning yield. That's a diagnostic no wire-level observation can
    produce.

Sub-test kept: `tool_choice:"required"` still returns HTTP 400 against
reasoner ("Thinking mode does not support this tool_choice"). Reported as
an evidence bit, not a top-line verdict, because the API just enforces it.

Needs: DEEPSEEK_API_KEY.
"""
from __future__ import annotations

import json
import urllib.request

from . import Probe, Verdict


_N_TRIALS = 5

_BARE_PROMPT = "Immediately call read_file with /tmp/x."
_HINT_PROMPT = ("Reason step by step. Then call read_file with /tmp/x.")

_TOOLS = [{
    "type": "function",
    "function": {
        "name": "read_file",
        "description": "Read a file",
        "parameters": {"type": "object",
                       "properties": {"path": {"type": "string"}},
                       "required": ["path"]},
    },
}]


def _post_stream(url: str, key: str, body: dict, timeout: int = 60) -> tuple[int, list[bytes]]:
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={
            "content-type": "application/json",
            "authorization": f"Bearer {key}",
            "accept": "text/event-stream",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().splitlines()
    except urllib.error.HTTPError as e:  # noqa: F821
        return e.code, e.read().splitlines()


def _count_frames(lines: list[bytes]) -> tuple[int, int, int]:
    total = reasoning = tc = 0
    for ln in lines:
        if not ln.startswith(b"data: "):
            continue
        body = ln[6:].decode(errors="replace")
        if body.strip() == "[DONE]":
            continue
        try:
            obj = json.loads(body)
        except Exception:
            continue
        total += 1
        delta = (obj.get("choices") or [{}])[0].get("delta") or {}
        if delta.get("reasoning_content"):
            reasoning += 1
        if delta.get("tool_calls"):
            tc += 1
    return total, reasoning, tc


def _sample(url: str, key: str, prompt: str) -> list[dict]:
    trials = []
    for _ in range(_N_TRIALS):
        code, lines = _post_stream(url, key, {
            "model": "deepseek-reasoner", "stream": True,
            "messages": [{"role": "user", "content": prompt}],
            "tools": _TOOLS, "tool_choice": "auto",
        })
        total, reasoning, tc = _count_frames(lines)
        trials.append({"http": code, "total": total,
                       "reasoning": reasoning, "tool_calls": tc})
    return trials


def _skip_rate(trials: list[dict]) -> float | None:
    ok = [t for t in trials if t["http"] == 200 and t["tool_calls"] > 0]
    if not ok:
        return None
    silent = sum(1 for t in ok if t["reasoning"] == 0)
    return silent / len(ok)


def _run(ctx: dict) -> Verdict:
    key = ctx["env"]["DEEPSEEK_API_KEY"]
    url = ctx["env"].get("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/") + "/chat/completions"

    # Evidence bit: reasoner rejects tool_choice:"required" — record but don't verdict on it.
    code_req, _ = _post_stream(url, key, {
        "model": "deepseek-reasoner", "stream": True,
        "messages": [{"role": "user", "content": "call read_file with /tmp/x"}],
        "tools": _TOOLS, "tool_choice": "required",
    })

    bare_trials = _sample(url, key, _BARE_PROMPT)
    hint_trials = _sample(url, key, _HINT_PROMPT)
    bare_rate = _skip_rate(bare_trials)
    hint_rate = _skip_rate(hint_trials)

    ev = {
        "required_blocked_400": code_req == 400,
        "n_per_arm": _N_TRIALS,
        "bare_prompt": _BARE_PROMPT,
        "hint_prompt": _HINT_PROMPT,
        "bare_trials": bare_trials,
        "hint_trials": hint_trials,
        "bare_skip_rate": bare_rate,
        "hint_skip_rate": hint_rate,
    }

    if bare_rate is None or hint_rate is None:
        return Verdict("warn", "one arm produced no tool_calls at all; inconclusive", evidence=ev)

    delta = bare_rate - hint_rate

    if bare_rate >= 0.4 and hint_rate <= 0.1 and delta >= 0.3:
        return Verdict(
            "warn",
            f"reasoner skips its reasoning stream on your prompt shape "
            f"(bare {bare_rate:.0%}, +CoT hint {hint_rate:.0%}, Δ={delta:+.0%})",
            detail="This is a MODEL decision, not a harness bug. The Node "
                   "stack surfaces nothing about it. Fix your prompt "
                   "(add \"reason step by step\") or accept reasoning-less "
                   "turns. Empty reasoning_content is a distinct state — "
                   "don't reconstruct thinking-mode history without checking.",
            evidence=ev,
        )
    if bare_rate >= 0.4:
        return Verdict(
            "warn",
            f"reasoner skips reasoning stream {bare_rate:.0%} of the time on bare prompt; "
            f"CoT hint did not fully restore it ({hint_rate:.0%})",
            detail="The skip is prompt-shape-sensitive but not fully steerable "
                   "by a hint. Sample size is small; try `dsh doctor --node "
                   "--only P1-reasoner-skip` again for stability.",
            evidence=ev,
        )
    if bare_rate == 0 and hint_rate == 0:
        return Verdict(
            "pass",
            "reasoner emitted reasoning_content on both bare and CoT-hinted prompts",
            evidence=ev,
        )
    return Verdict(
        "pass",
        f"skip rates within noise (bare {bare_rate:.0%}, hint {hint_rate:.0%})",
        evidence=ev,
    )


PROBE = Probe(
    id="P1-reasoner-skip",
    title="reasoner skips reasoning stream on trivial prompts (steerable via CoT hint)",
    run=_run,
    needs=("DEEPSEEK_API_KEY",),
)
