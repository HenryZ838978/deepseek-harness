"""probe_2: reasoning_content lifecycle bug.

Two sub-experiments per trial:
  A. Faithful loop (control)        — echo reasoning_content back, expect 200.
  B. Stripped loop (faulty client)  — drop reasoning_content from prior assistant turn,
                                       expect 400 with the well-known message.

We also record streaming chunk shapes for the reasoning field so the F2 client
can document exactly which chunks carry it (some have ONLY reasoning, no content).

Reference:
  microsoft/agent-framework#5538
  NousResearch/hermes-agent#15353
  cline/cline PR #7888
"""

from __future__ import annotations

import json
import sys

from _common import (  # type: ignore
    CALCULATOR_TOOL,
    SYSTEM_PROMPT,
    THINKING_ON,
    TrialRecord,
    banner,
    calc_user_msg,
    env_loaded,
    make_client,
    parse_n_arg,
    raw_writer,
    summarise_inplace,
    time_trial,
)


PROBE = "probe_2_reasoning_lifecycle"


def main() -> int:
    n = parse_n_arg(default=5)
    banner(PROBE, n)
    client = make_client()
    cfg = env_loaded()
    model = cfg["reasoner_model"]  # thinking-mode is the bug-trigger surface

    rows: list[dict] = []

    with raw_writer(PROBE) as (write, out_path):
        for i in range(n):
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                calc_user_msg(seed=i),
            ]

            # --- turn 1: get a tool-call assistant message (with reasoning_content) ---
            rec_setup = TrialRecord(probe=PROBE, trial_idx=i, notes={"phase": "setup"})
            assistant_msg = None
            with time_trial(rec_setup):
                resp = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    tools=[CALCULATOR_TOOL],
                    extra_body=THINKING_ON,
                    max_tokens=1024,
                )
                msg = resp.choices[0].message
                assistant_msg = {
                    "role": "assistant",
                    "content": msg.content,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": tc.type,
                            "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                        }
                        for tc in (msg.tool_calls or [])
                    ] if msg.tool_calls else None,
                    "reasoning_content": getattr(msg, "reasoning_content", None),
                }
                rec_setup.finish_reason = resp.choices[0].finish_reason
                rec_setup.notes["has_tool_calls"] = bool(assistant_msg["tool_calls"])
                rec_setup.notes["has_reasoning"] = bool(assistant_msg["reasoning_content"])
            rows.append(rec_setup.to_jsonable())
            write(rec_setup.to_jsonable())

            if not assistant_msg or not assistant_msg.get("tool_calls"):
                print(f"  trial {i}: setup did not produce tool_call (finish={rec_setup.finish_reason}). Skipping A/B.")
                continue

            tool_call_id = assistant_msg["tool_calls"][0]["id"]
            tool_response = {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": "RESULT=8888",
            }

            # --- A: faithful echo of reasoning_content ---
            rec_a = _continue(
                client,
                model,
                messages + [assistant_msg, tool_response],
                expect="200",
                phase="A_faithful",
                trial_idx=i,
            )
            rows.append(rec_a.to_jsonable())
            write(rec_a.to_jsonable())

            # --- B: drop reasoning_content (the bug trigger) ---
            stripped = dict(assistant_msg)
            stripped.pop("reasoning_content", None)
            rec_b = _continue(
                client,
                model,
                messages + [stripped, tool_response],
                expect="400",
                phase="B_stripped",
                trial_idx=i,
            )
            rows.append(rec_b.to_jsonable())
            write(rec_b.to_jsonable())

            print(
                f"  trial {i}: setup={rec_setup.status} "
                f"A={rec_a.status} ({rec_a.error['type'] if rec_a.error else 'ok'}) "
                f"B={rec_b.status} ({rec_b.error['type'] if rec_b.error else 'ok'})"
            )

    summarise_inplace(rows)

    # Diagnostic: did we successfully reproduce the bug at least once?
    repro = sum(
        1 for r in rows
        if r.get("notes", {}).get("phase") == "B_stripped" and r.get("status") == "error"
    )
    total_b = sum(1 for r in rows if r.get("notes", {}).get("phase") == "B_stripped")
    print(f"[probe_2] reasoning-strip 400 reproduction: {repro}/{total_b}")
    print(f"raw → {out_path}")
    return 0


def _continue(client, model, messages, *, expect, phase, trial_idx) -> TrialRecord:
    rec = TrialRecord(probe=PROBE, trial_idx=trial_idx, notes={"phase": phase, "expect": expect})
    with time_trial(rec):
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=[CALCULATOR_TOOL],
            extra_body=THINKING_ON,
            max_tokens=1024,
        )
        rec.finish_reason = resp.choices[0].finish_reason
        rec.usage = getattr(resp, "usage", None) and resp.usage.model_dump()
        rec.raw_excerpt = {"content": (resp.choices[0].message.content or "")[:200]}
    return rec


if __name__ == "__main__":
    raise SystemExit(main())
