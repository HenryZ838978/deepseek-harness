"""probe_8: finish_reason boundary semantics (independent — no public report yet).

Three forced cuts:
  C1 length cut       — set max_tokens=8 on a request that needs ~200, see what
                         finish_reason carries and whether tool_calls (if any) are
                         well-formed despite the truncation.
  C2 stop cut         — request a 5-line list, expect "stop"; sanity check that the
                         message is fully formed.
  C3 content_filter   — best-effort: prompt for a banned topic to see whether
                         finish_reason flips and whether content/tool_calls are
                         clobbered. (Not all endpoints expose content_filter.)

For each cut we record: finish_reason, len(content), len(tool_calls), any
non-null reasoning_content, and whether arguments JSON parses.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from _common import (  # type: ignore
    CALCULATOR_TOOL,
    SYSTEM_PROMPT,
    THINKING_OFF,
    TrialRecord,
    banner,
    env_loaded,
    make_client,
    parse_n_arg,
    raw_writer,
    summarise_inplace,
    time_trial,
)


PROBE = "probe_8_finish_reason_semantics"


def main() -> int:
    n = parse_n_arg(default=3)
    banner(PROBE, n * 3)
    client = make_client()
    cfg = env_loaded()

    rows: list[dict] = []

    with raw_writer(PROBE) as (write, out_path):
        for i in range(n):
            for cut in ("C1_length", "C2_stop", "C3_filter_attempt"):
                rec = TrialRecord(probe=PROBE, trial_idx=i, notes={"cut": cut})
                kwargs, messages = _build(cut, i)
                with time_trial(rec):
                    resp = client.chat.completions.create(
                        model=cfg["model"],
                        messages=messages,
                        tools=[CALCULATOR_TOOL] if cut == "C1_length" else None,
                        extra_body=THINKING_OFF,
                        **kwargs,
                    )
                    choice = resp.choices[0]
                    rec.finish_reason = choice.finish_reason
                    rec.usage = getattr(resp, "usage", None) and resp.usage.model_dump()
                    msg = choice.message
                    content = msg.content or ""
                    tool_calls = getattr(msg, "tool_calls", None) or []
                    args_ok = []
                    for tc in tool_calls:
                        try:
                            json.loads(tc.function.arguments)
                            args_ok.append(True)
                        except Exception:
                            args_ok.append(False)
                    rec.notes["content_len"] = len(content)
                    rec.notes["n_tool_calls"] = len(tool_calls)
                    rec.notes["all_args_parse"] = all(args_ok) if args_ok else None
                    rec.notes["has_reasoning"] = bool(getattr(msg, "reasoning_content", None))
                    rec.raw_excerpt = {"content_preview": content[:200]}
                print(
                    f"  trial {i} {cut}: status={rec.status} finish={rec.finish_reason} "
                    f"content_len={rec.notes['content_len']} "
                    f"tool_calls={rec.notes['n_tool_calls']} args_ok={rec.notes['all_args_parse']}"
                )
                rows.append(rec.to_jsonable())
                write(rec.to_jsonable())

    summarise_inplace(rows)
    print(f"\nraw → {out_path}")
    return 0


def _build(cut: str, trial: int):
    if cut == "C1_length":
        msgs = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Compute (97 + {17 + trial}) * 31 - {89 + trial * 2} via the calculator tool, "
                    "then write a 200-word essay about prime numbers."
                ),
            },
        ]
        return {"max_tokens": 8, "temperature": 0}, msgs
    if cut == "C2_stop":
        msgs = [
            {"role": "user", "content": "List 3 fruits, comma-separated. No other text."},
        ]
        return {"max_tokens": 32, "temperature": 0}, msgs
    # C3_filter_attempt — endpoint may or may not flag this; we record what comes back
    msgs = [
        {"role": "user", "content": "Reply with the literal word REFUSED."},
    ]
    return {"max_tokens": 32, "temperature": 0}, msgs


if __name__ == "__main__":
    raise SystemExit(main())
