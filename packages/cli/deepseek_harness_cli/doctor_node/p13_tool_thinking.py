"""P13 — tools × thinking: the forced-tool contract, and spurious tool calls
from `deepseek-v4-pro` with thinking off.

Discovery: 2026-11-25, live, against the Anthropic-Messages endpoint the
official harness has used exclusively since 0.1.7 (`/anthropic/v1/messages`).
Raw: `reports/raw/probe_P12_effort_tools_2026-11-25.jsonl` (contract grid)
and `reports/raw/probe_P13_spurious_tool_call_2026-11-25.jsonl` (N=12/cell).

1. Contract. With thinking enabled (the server default for both canonical
   ids), any forcing `tool_choice` — Messages `{"type":"any"}` /
   `{"type":"tool",...}`, Chat `"required"` / a named function — is rejected
   `400 "Thinking mode does not support this tool_choice"`, on both endpoints
   and both models. With `thinking: {"type":"disabled"}` every forcing choice
   is accepted and yields a tool call. The legacy `deepseek-chat` alias
   resolves to `deepseek-flash` with thinking off, so it also accepts forcing
   choices without the flag. Upstream's adapter never sends `tool_choice`
   (`llm-deepseek/src/serialize.ts` maps only `reasoningEffort` → `thinking`
   / `output_config.effort`), so inside dsh this bites plugins and SDK
   callers that build requests themselves, not the core loop.

2. Behaviour. `deepseek-v4-pro` with thinking disabled and one tool
   available calls that tool on Chinese prompts that have nothing to do with
   it: "17 乘以 23 等于多少？只给数字。" → `get_weather({"city":"17乘以23"})`
   in 7/12 trials, "写一句关于秋天的诗。" → `get_weather({"city":"北京"})`
   in 2/12. The same prompts in English: 0/12. Thinking enabled: 0/12.
   `deepseek-flash`, either mode: 0/36. In dsh this is the `effort: off`
   setting on a pro model (serialize.ts:147-155 sends
   `thinking: {type: "disabled"}` for `off`).

Explain + fix, in that order: forcing a tool needs thinking off (or the
`deepseek-chat` alias); thinking off on v4-pro needs either a tool-free
router turn, argument validation on the tool side, or effort ≥ low — any of
which removes the spurious call in our samples.

The probe spends ~2 + 2N small requests (default N=6).
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from . import Probe, Verdict

_TOOL = [{
    "name": "get_weather", "description": "Get current weather for a city.",
    "input_schema": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]},
}]
_ZH_TOOL_FREE = "17 乘以 23 等于多少？只给数字。"
_ZH_TOOL_NEEDED = "北京现在天气怎么样？"


def _messages(base: str, key: str, body: dict, timeout: int = 90) -> tuple[int, dict]:
    req = urllib.request.Request(
        base + "/anthropic/v1/messages", data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json", "x-api-key": key, "anthropic-version": "2023-06-01"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8", "replace"))
        except ValueError:
            return e.code, {}


def _body(model: str, prompt: str, thinking: str, tool_choice: dict | None = None) -> dict:
    b = {"model": model, "max_tokens": 512, "tools": _TOOL, "thinking": {"type": thinking},
         "messages": [{"role": "user", "content": prompt}]}
    if tool_choice:
        b["tool_choice"] = tool_choice
    return b


def _tool_calls(doc: dict) -> list[dict]:
    return [c for c in doc.get("content", []) if c.get("type") == "tool_use"]


def _run(ctx: dict) -> Verdict:
    env = ctx["env"]
    key = env["DEEPSEEK_API_KEY"]
    base = env.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
    for suffix in ("/anthropic", "/v1"):
        if base.endswith(suffix):
            base = base[: -len(suffix)]
    n = int(env.get("PROBE_P13_N", "6"))
    ev: dict = {"endpoint": base + "/anthropic/v1/messages", "n": n}

    # 1. contract: forced tool under default thinking vs thinking disabled.
    forced = {"type": "any"}
    s_on, d_on = _messages(base, key, _body("deepseek-flash", _ZH_TOOL_NEEDED, "enabled", forced))
    s_off, d_off = _messages(base, key, _body("deepseek-flash", _ZH_TOOL_NEEDED, "disabled", forced))
    ev["contract"] = {
        "forced_thinking_enabled": {"http": s_on, "error": (d_on.get("error") or {}).get("message", "")[:160]},
        "forced_thinking_disabled": {"http": s_off, "tool_calls": len(_tool_calls(d_off))},
    }
    contract_as_known = s_on == 400 and s_off == 200 and len(_tool_calls(d_off)) == 1

    # 2. behaviour: v4-pro, thinking off vs on, tool-free Chinese prompt.
    rates = {}
    examples = []
    for thinking in ("disabled", "enabled"):
        hits = 0
        for _ in range(n):
            status, doc = _messages(base, key, _body("deepseek-v4-pro", _ZH_TOOL_FREE, thinking))
            if status != 200:
                return Verdict("warn", f"v4-pro request failed HTTP {status}", evidence={**ev, "error": doc})
            calls = _tool_calls(doc)
            if calls:
                hits += 1
                if len(examples) < 3:
                    examples.append({"thinking": thinking, "input": calls[0].get("input")})
        rates[thinking] = hits / n
    ev["spurious_tool_rate"] = rates
    ev["examples"] = examples

    fix = ("Fix: keep thinking on (dsh effort ≥ low) for v4-pro turns that carry tools, "
           "route tool-free turns without tools, or validate tool arguments "
           "(the spurious calls pass the prompt text as `city`).")
    contract_note = ("Forcing tool_choice requires `thinking: {type: disabled}` "
                     "(or the `deepseek-chat` alias); with thinking on it is HTTP 400.")
    if not contract_as_known:
        contract_note = ("Forced-tool contract CHANGED from the 2026-11-25 baseline "
                         f"(thinking on → HTTP {s_on}, off → HTTP {s_off}); re-check before relying on it.")

    if rates["disabled"] > 0 and rates["disabled"] > rates["enabled"]:
        return Verdict(
            "warn",
            f"v4-pro, thinking off: {rates['disabled']:.0%} spurious tool calls on a tool-free "
            f"Chinese prompt (thinking on: {rates['enabled']:.0%})",
            detail=f"{fix} {contract_note}",
            evidence=ev,
        )
    return Verdict(
        "pass" if contract_as_known else "warn",
        f"no spurious tool calls in {2 * n} v4-pro samples (baseline 2026-11-25: 58% with thinking off)",
        detail=contract_note,
        evidence=ev,
    )


PROBE = Probe(
    id="P13-tool-thinking",
    title="forced tool_choice needs thinking off; v4-pro thinking-off spurious tool calls (2026-11-25)",
    run=_run,
    needs=("DEEPSEEK_API_KEY",),
)
