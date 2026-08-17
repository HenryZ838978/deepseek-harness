"""P1 — reasoner + tools ⇒ reasoning_content silence (wire-level).

Discovery: 2026-08-17. `deepseek-reasoner` accepts `tool_choice:"auto"` and
streams tool_calls fine — but reasoning_content is intermittently silenced
on tool-using turns. Also: `tool_choice:"required"` returns HTTP 400 outright.

Impact: any Node-side harness that trusts reasoning_content to reconstruct
thinking-mode history will silently lose the chain-of-thought on some tool
turns. DSH (Python) preserves reasoning_content by contract §1; the official
Node stack has no such guard.

Sampling: runs the prompt N times (default 3) because single-shot observation
is not stable (2026-08-17 two back-to-back runs went 0/12 then 17/31). We
report the silence *rate*; a probe should never decide on n=1.

Needs: DEEPSEEK_API_KEY.
"""
from __future__ import annotations

import json
import urllib.request

from . import Probe, Verdict


_N_TRIALS = 3


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


def _run(ctx: dict) -> Verdict:
    key = ctx["env"]["DEEPSEEK_API_KEY"]
    url = ctx["env"].get("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/") + "/chat/completions"

    tools = [{
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file",
            "parameters": {"type": "object",
                           "properties": {"path": {"type": "string"}},
                           "required": ["path"]},
        },
    }]

    # Sub-test A (single shot): tool_choice:"required" on reasoner should 400.
    code_a, _ = _post_stream(url, key, {
        "model": "deepseek-reasoner", "stream": True,
        "messages": [{"role": "user", "content": "call read_file with /tmp/x"}],
        "tools": tools, "tool_choice": "required",
    })
    required_blocked = code_a == 400

    # Sub-test B (N-shot): tool_choice:"auto", count reasoning-silence rate.
    trials = []
    for _ in range(_N_TRIALS):
        code, lines = _post_stream(url, key, {
            "model": "deepseek-reasoner", "stream": True,
            "messages": [{"role": "user", "content":
                          "Think briefly, then call read_file with /tmp/x."}],
            "tools": tools, "tool_choice": "auto",
        })
        total, reasoning, tc = _count_frames(lines)
        trials.append({"http": code, "total": total, "reasoning": reasoning, "tool_calls": tc})

    silent = [t for t in trials if t["http"] == 200 and t["tool_calls"] > 0 and t["reasoning"] == 0]
    healthy = [t for t in trials if t["http"] == 200 and t["reasoning"] > 0]

    ev = {
        "required_blocked_400": required_blocked,
        "n_trials": _N_TRIALS,
        "trials": trials,
        "silent_trials": len(silent),
        "healthy_trials": len(healthy),
    }

    if silent and not healthy:
        return Verdict(
            "fail",
            f"{len(silent)}/{_N_TRIALS} trials: reasoning_content silenced on tool-using reasoner turn",
            detail="Official Node stack has no reasoning-preserve guard. "
                   "DSH (Python) enforces contract §1. Downstream: thinking-mode "
                   "history reconstruction is wrong whenever silence happens.",
            evidence=ev,
        )
    if silent:
        return Verdict(
            "warn",
            f"{len(silent)}/{_N_TRIALS} trials silent (intermittent) — official Node stack has no guard",
            detail="Silence is not every-turn but present. A production harness "
                   "must either force reasoning off or preserve empty reasoning "
                   "as a distinct state.",
            evidence=ev,
        )
    if healthy:
        return Verdict(
            "pass",
            f"{len(healthy)}/{_N_TRIALS} trials carried reasoning_content",
            evidence=ev,
        )
    return Verdict("warn", "no tool_calls emitted in any trial; inconclusive", evidence=ev)


PROBE = Probe(
    id="P1-reasoner-wire",
    title="reasoner+tools wire silence (reasoning_content)",
    run=_run,
    needs=("DEEPSEEK_API_KEY",),
)
