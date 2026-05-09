"""probe_4: trigger DeepSeek-V3#1069 (strict-mode JSON corruption).

Conditions per the upstream issue:
  - base_url ends with `/beta`
  - request kwarg `strict=True` on the function definition
  - schema has `additionalProperties: False`

Symptom: assistant `tool_calls[0].function.arguments` is missing the closing `"`
on the FIRST property key:
    {"selected: ["A","C","D"]}      ← broken
    {"selected": ["A","C","D"]}     ← expected

We try N times, count corruptions, and dump every corrupted sample whole.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from _common import (  # type: ignore
    TrialRecord,
    banner,
    env_loaded,
    make_client_beta,
    parse_n_arg,
    raw_writer,
    summarise_inplace,
    time_trial,
)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from deepseek_harness.tool_calls import detect_strict_mode_corruption  # noqa: E402


PROBE = "probe_4_strict_mode_corruption"


CHOICES_TOOL = {
    "type": "function",
    "function": {
        "name": "submit_choices",
        "description": "Submit the chosen answer letters.",
        "strict": True,
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "selected": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["A", "B", "C", "D"]},
                    "description": "Selected answers",
                },
                "confidence": {
                    "type": "number",
                    "description": "Confidence in [0,1]",
                },
            },
            "required": ["selected", "confidence"],
        },
    },
}


def main() -> int:
    n = parse_n_arg(default=20)
    banner(PROBE, n)
    cfg = env_loaded()

    # Try BOTH endpoints — /beta is the documented #1069 trigger, but it
    # remaps v4-pro to legacy `deepseek-reasoner` which rejects specific
    # tool_choice. So we run two batches: /beta with auto tool_choice, AND
    # the standard endpoint with strict=true to see whether the bug surfaces
    # in the modern path.
    from _common import make_client  # local to keep import order tidy

    rows: list[dict] = []
    corruptions = 0

    cases = [
        ("standard_strict_true", make_client(), cfg["model"], "auto"),
        ("beta_strict_true", make_client_beta(), cfg["model"], "auto"),
    ]

    for case_name, client, model, tc_mode in cases:
        print(f"\n[probe_4/{case_name}] base hit (model={model}, tool_choice={tc_mode})")
        with raw_writer(f"{PROBE}_{case_name}") as (write, out_path):
            for i in range(n):
                rec = TrialRecord(probe=PROBE, trial_idx=i, notes={"case": case_name})
                with time_trial(rec):
                    resp = client.chat.completions.create(
                        model=model,
                        messages=[
                            {
                                "role": "system",
                                "content": "Use the submit_choices tool to choose A, C, D with confidence 0.9.",
                            },
                            {"role": "user", "content": "Choose now."},
                        ],
                        tools=[CHOICES_TOOL],
                        tool_choice=tc_mode,
                        max_tokens=128,
                        extra_body={"thinking": {"type": "disabled"}},
                    )
                    choice = resp.choices[0]
                    rec.finish_reason = choice.finish_reason
                    rec.usage = getattr(resp, "usage", None) and resp.usage.model_dump()

                    tool_calls = getattr(choice.message, "tool_calls", None) or []
                    args_str = tool_calls[0].function.arguments if tool_calls else None
                    rec.raw_excerpt = {"arguments_raw": args_str}

                    if args_str is None:
                        rec.notes["no_tool_call"] = True
                    else:
                        try:
                            json.loads(args_str)
                            rec.notes["json_ok"] = True
                        except json.JSONDecodeError as e:
                            corruptions += 1
                            rec.notes["json_ok"] = False
                            rec.notes["jsonerror"] = str(e)
                            rec.notes["corrupt_pattern_match_1069"] = detect_strict_mode_corruption(args_str)
                            rec.salvage = {
                                "pattern": "strict_mode_jsondecodeerror",
                                "original_content": args_str,
                            }
                print(
                    f"  trial {i}: status={rec.status} json_ok={rec.notes.get('json_ok')} "
                    f"finish={rec.finish_reason} err={rec.error and rec.error.get('type')}"
                )
                rows.append(rec.to_jsonable())
                write(rec.to_jsonable())

    print(f"\n[probe_4] strict-mode corruption total across cases: {corruptions}")
    summarise_inplace(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
