"""probe_10: multi-turn agentic loop, mirroring DeepSeek's official examples EXACTLY.

This is the scenario the community complains about most. We replicate
DeepSeek's official samples *byte-for-byte* (the "send_messages" pattern from
api-docs.deepseek.com /zh-cn/guides/function_calling and /zh-cn/guides/multi_round_chat),
then drive the loop for many turns and see what falls over.

Three sub-experiments:

  S1 chat_only multi-round (5 turns)        — official multi-round-chat example
                                              + measure history bloat & cache hit
  S2 function_calling 1-tool loop (5 turns)  — official function-calling example
                                              + reuse the same tool many times in one
                                              session, see if reasoning_content lifecycle
                                              stays correct AND if any 11% leakage shows
                                              under sustained pressure
  S3 multi-tool loop with thinking (5 turns) — same as S2 but with multiple tools
                                              and thinking ENABLED (the bug surface)

What we record per turn:
  - serialized history bytes (as the OpenAI SDK would JSON-encode it)
  - cache_hit_tokens / total prompt_tokens
  - latency
  - finish_reason
  - whether the model ever leaked a tool_call into content
  - whether any 400 fired (reasoning_content lifecycle)
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

# Mirror official imports — no F2 library, no salvage helpers in the call path.
from _common import (  # type: ignore
    TrialRecord,
    banner,
    env_loaded,
    raw_writer,
    summarise_inplace,
    time_trial,
)


PROBE = "probe_10_multiturn_agentic_loop"

WEATHER_TOOL = {
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Get weather of a location, the user should supply a location first.",
        "parameters": {
            "type": "object",
            "properties": {
                "location": {
                    "type": "string",
                    "description": "The city and state, e.g. San Francisco, CA",
                }
            },
            "required": ["location"],
        },
    },
}

CALC_TOOL = {
    "type": "function",
    "function": {
        "name": "calculator",
        "description": "Evaluate a basic arithmetic expression and return the numeric result.",
        "parameters": {
            "type": "object",
            "properties": {"expression": {"type": "string"}},
            "required": ["expression"],
        },
    },
}

# Mock tool implementations so we can drive the loop programmatically.
def fake_weather(location: str) -> str:
    return json.dumps({"location": location, "temperature_c": 24, "condition": "clear"})

def fake_calc(expression: str) -> str:
    try:
        # safe eval of digits + basic ops only
        allowed = set("0123456789+-*/.() ")
        if any(ch not in allowed for ch in expression):
            return "ERROR: invalid characters"
        return str(eval(expression, {"__builtins__": {}}, {}))
    except Exception as e:
        return f"ERROR: {e}"


def main() -> int:
    n_turns = 5
    banner(PROBE, n_turns * 3)
    cfg = env_loaded()

    load_dotenv()
    client = OpenAI(api_key=os.environ["DEEPSEEK_API_KEY"], base_url=cfg["base_url"])
    model = cfg["model"]

    rows: list[dict] = []

    with raw_writer(PROBE) as (write, out_path):
        # ---- S1: official multi-round chat example ----
        print("\n[probe_10/S1] official multi-round chat (no tools, no thinking flag)")
        history: list[dict] = []
        questions = [
            "What's the highest mountain in the world?",
            "What is the second highest?",
            "And the third?",
            "What is the average elevation across these three?",
            "Which one is the easiest for amateurs to climb?",
        ]
        for turn, q in enumerate(questions):
            history.append({"role": "user", "content": q})
            rec = TrialRecord(probe=PROBE, trial_idx=turn, notes={"scenario": "S1_chat_only", "turn": turn})
            with time_trial(rec):
                # Mirror official: extra_body to disable thinking — keep the call cheap & deterministic
                resp = client.chat.completions.create(
                    model=model,
                    messages=history,
                    extra_body={"thinking": {"type": "disabled"}},
                    max_tokens=256,
                )
                msg = resp.choices[0].message
                rec.finish_reason = resp.choices[0].finish_reason
                rec.usage = resp.usage.model_dump()
                history.append({"role": "assistant", "content": msg.content})
                rec.notes["history_bytes"] = len(json.dumps(history, ensure_ascii=False).encode("utf-8"))
                rec.notes["history_messages"] = len(history)
                rec.raw_excerpt = {"q": q, "a": (msg.content or "")[:160]}
            print(f"  S1 turn {turn}: hit={rec.usage.get('prompt_cache_hit_tokens')}/{rec.usage.get('prompt_tokens')} "
                  f"history_bytes={rec.notes['history_bytes']:>7} latency={rec.latency_ms}ms")
            rows.append(rec.to_jsonable())
            write(rec.to_jsonable())

        # ---- S2: official function_calling example, looped 5 turns, ONE tool ----
        print("\n[probe_10/S2] official function_calling, single tool, 5 turns (no thinking)")
        s2_history: list[dict] = []
        s2_questions = [
            "How's the weather in Hangzhou, Zhejiang?",
            "And in Shanghai?",
            "What about Beijing?",
            "Compare those three.",
            "Which city has the most pleasant weather right now?",
        ]
        s2_leaks = 0
        for turn, q in enumerate(s2_questions):
            s2_history.append({"role": "user", "content": q})
            rec = TrialRecord(probe=PROBE, trial_idx=turn, notes={"scenario": "S2_func_loop", "turn": turn})
            with time_trial(rec):
                turn_steps = _drive_tool_loop(
                    client=client,
                    model=model,
                    history=s2_history,
                    tools=[WEATHER_TOOL],
                    extra_body={"thinking": {"type": "disabled"}},
                    tool_runners={"get_weather": lambda **kw: fake_weather(**kw)},
                    rec=rec,
                    max_inner_iters=4,
                )
                rec.notes.update(turn_steps)
                rec.notes["history_bytes"] = len(json.dumps(s2_history, ensure_ascii=False, default=_msgenc).encode("utf-8"))
                rec.notes["history_messages"] = len(s2_history)
                if turn_steps.get("any_leak"):
                    s2_leaks += 1
            print(f"  S2 turn {turn}: inner_iters={rec.notes['inner_iters']} leaks={rec.notes['any_leak']} "
                  f"history_bytes={rec.notes['history_bytes']:>7} latency={rec.latency_ms}ms err={rec.error and rec.error['type']}")
            rows.append(rec.to_jsonable())
            write(rec.to_jsonable())
        print(f"[probe_10/S2] total tool-call leaks across 5 turns: {s2_leaks}")

        # ---- S3: multi-tool loop with thinking ENABLED (the bug surface) ----
        print("\n[probe_10/S3] multi-tool loop with thinking ENABLED (reasoning_content lifecycle)")
        s3_history: list[dict] = []
        s3_questions = [
            "Compute (12+34)*5 with the calculator tool.",
            "Now compute 7! using the calculator.",
            "What's the weather in Hangzhou?",
            "Compute the difference between 7! and (12+34)*5.",
            "Summarise everything we computed and observed today.",
        ]
        s3_400s = 0
        s3_leaks = 0
        for turn, q in enumerate(s3_questions):
            s3_history.append({"role": "user", "content": q})
            rec = TrialRecord(probe=PROBE, trial_idx=turn, notes={"scenario": "S3_multitool_thinking", "turn": turn})
            with time_trial(rec):
                turn_steps = _drive_tool_loop(
                    client=client,
                    model=model,
                    history=s3_history,
                    tools=[WEATHER_TOOL, CALC_TOOL],
                    extra_body={"thinking": {"type": "enabled"}},
                    tool_runners={
                        "get_weather": lambda **kw: fake_weather(**kw),
                        "calculator": lambda **kw: fake_calc(**kw),
                    },
                    rec=rec,
                    max_inner_iters=4,
                )
                rec.notes.update(turn_steps)
                rec.notes["history_bytes"] = len(json.dumps(s3_history, ensure_ascii=False, default=_msgenc).encode("utf-8"))
                rec.notes["history_messages"] = len(s3_history)
                if turn_steps.get("any_leak"):
                    s3_leaks += 1
                if rec.error and "reasoning_content" in (rec.error.get("message") or ""):
                    s3_400s += 1
            print(f"  S3 turn {turn}: inner_iters={rec.notes['inner_iters']} leaks={rec.notes['any_leak']} "
                  f"history_bytes={rec.notes['history_bytes']:>7} latency={rec.latency_ms}ms "
                  f"err={rec.error and rec.error['type']}")
            rows.append(rec.to_jsonable())
            write(rec.to_jsonable())
        print(f"[probe_10/S3] reasoning_content 400s: {s3_400s}/5  · tool-call leaks: {s3_leaks}/5")

    summarise_inplace(rows)
    print(f"\nraw → {out_path}")
    return 0


def _drive_tool_loop(*, client, model, history, tools, extra_body, tool_runners, rec, max_inner_iters):
    """Inner loop: send → if tool_calls, run them, append, send again. Up to max_inner_iters."""
    inner = 0
    any_leak = False
    last_finish = None
    last_usage = None
    leak_samples: list[str] = []
    while inner < max_inner_iters:
        inner += 1
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=history,
                tools=tools,
                extra_body=extra_body,
                max_tokens=1024,
            )
        except Exception as e:
            rec.status = "error"
            rec.error = {"type": type(e).__name__, "message": str(e)}
            return {
                "inner_iters": inner,
                "any_leak": any_leak,
                "leak_samples": leak_samples,
                "early_abort_reason": rec.error["message"][:200],
            }
        msg = resp.choices[0].message
        last_finish = resp.choices[0].finish_reason
        last_usage = resp.usage.model_dump()

        # Build OpenAI-shaped assistant message — preserve reasoning_content if present
        asst: dict = {"role": "assistant", "content": msg.content}
        if getattr(msg, "tool_calls", None):
            asst["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": tc.type,
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in msg.tool_calls
            ]
        rc = getattr(msg, "reasoning_content", None)
        if rc:
            asst["reasoning_content"] = rc
        history.append(asst)

        # Detect leakage: finish_reason='stop' + content has tool-call markup
        if not asst.get("tool_calls"):
            content = (msg.content or "")
            if any(tag in content for tag in ("<tool_call>", "<｜DSML｜tool_calls", '"name":')):
                any_leak = True
                leak_samples.append(content[:300])
            break  # natural stop

        # Run all tool calls and append tool messages
        for tc in asst["tool_calls"]:
            name = tc["function"]["name"]
            try:
                args = json.loads(tc["function"]["arguments"])
            except Exception:
                args = {}
            runner = tool_runners.get(name)
            result = runner(**args) if runner else f"ERROR: no runner for {name}"
            history.append({"role": "tool", "tool_call_id": tc["id"], "content": str(result)})

    rec.finish_reason = last_finish
    rec.usage = last_usage
    return {
        "inner_iters": inner,
        "any_leak": any_leak,
        "leak_samples": leak_samples,
    }


def _msgenc(o):
    return repr(o)


if __name__ == "__main__":
    raise SystemExit(main())
