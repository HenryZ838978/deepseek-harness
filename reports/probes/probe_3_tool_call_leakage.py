"""probe_3: tool_call leakage rate.

Run the SAME tool-use prompt N times, count how often the model returns:
  finish_reason="stop" + content carries a tool-call payload (DSML / JSON /
  <tool_call> wrapper) instead of populating `tool_calls`.

Reference: deepseek-ai/DeepSeek-V3#1244 (~11% reported in the wild).

Default n=100 (overridable). Each leaked sample is dumped in full so we can
quote it verbatim in the F1 spec.
"""

from __future__ import annotations

import sys

from _common import (  # type: ignore
    CALCULATOR_TOOL,
    SEARCH_TOOL,
    SYSTEM_PROMPT,
    THINKING_OFF,
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

# Import via package path (probes/ is added to sys.path by python invocation)
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent / "src"))
from deepseek_harness.tool_calls import salvage_tool_calls_from_content  # noqa: E402


PROBE = "probe_3_tool_call_leakage"


def main() -> int:
    n = parse_n_arg(default=100)
    banner(PROBE, n)
    client = make_client()
    cfg = env_loaded()

    rows: list[dict] = []
    leaked = 0

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
                    temperature=0.0,  # determinism reduces noise but won't kill the bug
                    extra_body=THINKING_OFF,
                    max_tokens=256,
                )
                choice = resp.choices[0]
                msg = choice.message
                rec.finish_reason = choice.finish_reason
                rec.usage = getattr(resp, "usage", None) and resp.usage.model_dump()

                content = msg.content
                tool_calls = getattr(msg, "tool_calls", None)

                if not tool_calls:
                    salvaged, residual, pattern = salvage_tool_calls_from_content(
                        content, choice.finish_reason
                    )
                    if salvaged:
                        leaked += 1
                        rec.salvage = {
                            "pattern": pattern,
                            "original_content": content,
                            "salvaged_tool_calls": salvaged,
                            "residual_content": residual,
                        }
                        rec.notes["leakage"] = True
                    else:
                        rec.notes["leakage"] = False
                        rec.notes["no_tool_call_no_leak"] = True
                else:
                    rec.notes["leakage"] = False

                rec.raw_excerpt = {
                    "content_preview": (content or "")[:300],
                    "tool_calls_count": len(tool_calls or []),
                }

            if i % 10 == 0 or rec.salvage:
                marker = "  LEAK!" if rec.salvage else ""
                print(
                    f"  trial {i}: status={rec.status} finish={rec.finish_reason}"
                    f" tool_calls={rec.raw_excerpt['tool_calls_count']}{marker}"
                )
            rows.append(rec.to_jsonable())
            write(rec.to_jsonable())

    print(f"\n[probe_3] tool-call leakage rate: {leaked}/{n} = {leaked/n:.1%}")
    if leaked:
        print(f"[probe_3] {leaked} leaked sample(s) saved to {out_path} for F1 spec quoting.")
    summarise_inplace(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
