"""probe_3b: same as probe_3 but with thinking ENABLED.

Hypothesis: V4-Pro tool-call leakage (deepseek-ai/DeepSeek-V3#1244) only manifests
when thinking is on, because the leak path goes through reasoning_content rather
than the message body proper.
"""

from __future__ import annotations

import sys
from pathlib import Path

from _common import (  # type: ignore
    CALCULATOR_TOOL,
    SEARCH_TOOL,
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

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from deepseek_harness.tool_calls import salvage_tool_calls_from_content  # noqa: E402


PROBE = "probe_3b_tool_call_leakage_thinking"


def main() -> int:
    n = parse_n_arg(default=20)
    banner(PROBE, n)
    client = make_client()
    cfg = env_loaded()

    rows: list[dict] = []
    leaked = 0
    reasoning_leaks = 0  # tool call shows up inside reasoning_content

    with raw_writer(PROBE) as (write, out_path):
        for i in range(n):
            rec = TrialRecord(probe=PROBE, trial_idx=i)
            with time_trial(rec):
                resp = client.chat.completions.create(
                    model=cfg["model"],
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        calc_user_msg(seed=i),
                    ],
                    tools=[CALCULATOR_TOOL, SEARCH_TOOL],
                    tool_choice="auto",
                    temperature=0.0,
                    extra_body=THINKING_ON,
                    max_tokens=2048,
                )
                choice = resp.choices[0]
                msg = choice.message
                rec.finish_reason = choice.finish_reason
                rec.usage = getattr(resp, "usage", None) and resp.usage.model_dump()

                content = msg.content
                tool_calls = getattr(msg, "tool_calls", None)
                reasoning = getattr(msg, "reasoning_content", None) or ""

                # main leak check
                if not tool_calls:
                    salvaged, residual, pattern = salvage_tool_calls_from_content(
                        content, choice.finish_reason
                    )
                    if salvaged:
                        leaked += 1
                        rec.salvage = {
                            "pattern": pattern,
                            "where": "content",
                            "original_content": content,
                            "salvaged_tool_calls": salvaged,
                        }

                # leak inside reasoning_content (cline #8365 path)
                if reasoning:
                    rsalvaged, _, rpat = salvage_tool_calls_from_content(reasoning, "stop")
                    if rsalvaged:
                        reasoning_leaks += 1
                        rec.notes["reasoning_leak"] = True
                        rec.notes["reasoning_leak_pattern"] = rpat

                rec.raw_excerpt = {
                    "content_preview": (content or "")[:200],
                    "reasoning_preview": reasoning[:200],
                    "tool_calls_count": len(tool_calls or []),
                }

            tag = ""
            if rec.salvage:
                tag = " LEAK_CONTENT"
            if rec.notes.get("reasoning_leak"):
                tag += " LEAK_REASONING"
            print(
                f"  trial {i}: status={rec.status} finish={rec.finish_reason}"
                f" tc={rec.raw_excerpt['tool_calls_count']}{tag}"
            )
            rows.append(rec.to_jsonable())
            write(rec.to_jsonable())

    print(f"\n[probe_3b] content-field leakage: {leaked}/{n} = {leaked/n:.1%}")
    print(f"[probe_3b] reasoning-field leakage: {reasoning_leaks}/{n} = {reasoning_leaks/n:.1%}")
    summarise_inplace(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
