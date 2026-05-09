"""probe_7: tool_call deltas in streaming mode (independent — no public report yet).

Force the model to call TWO tools in parallel, stream the response, and record
exactly how the tool_call deltas are split:
  - per `index`?
  - is each function `name` always in the FIRST chunk of its index, or can it stream too?
  - how are arguments JSON keys split? (one per chunk? per-arg? mid-string?)
  - if both tools fire, does index 0 finish before index 1 starts streaming, or interleave?

This drives F2 client's stream-aggregation logic and lands as F1 §5.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

from _common import (  # type: ignore
    CALCULATOR_TOOL,
    SEARCH_TOOL,
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


PROBE = "probe_7_tool_streaming_chunks"


def main() -> int:
    n = parse_n_arg(default=5)
    banner(PROBE, n)
    client = make_client()
    cfg = env_loaded()

    rows: list[dict] = []

    with raw_writer(PROBE) as (write, out_path):
        for i in range(n):
            rec = TrialRecord(probe=PROBE, trial_idx=i)
            chunk_log: list[dict] = []
            interleave_observed = False
            seen_indexes: list[int] = []
            last_seen_idx = None
            with time_trial(rec):
                stream = client.chat.completions.create(
                    model=cfg["model"],
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {
                            "role": "user",
                            "content": (
                                "I need TWO things in parallel — call BOTH tools in this turn: "
                                "1) calculator on (12 + 34) * 56, "
                                "2) web_search for 'TCP slow start'. Call both tools."
                            ),
                        },
                    ],
                    tools=[CALCULATOR_TOOL, SEARCH_TOOL],
                    tool_choice="auto",
                    parallel_tool_calls=True,
                    stream=True,
                    stream_options={"include_usage": True},
                    extra_body=THINKING_OFF,
                    max_tokens=512,
                )
                for chunk in stream:
                    choices = getattr(chunk, "choices", None) or []
                    if not choices:
                        continue
                    delta = getattr(choices[0], "delta", None)
                    if delta is None:
                        continue
                    tcs = getattr(delta, "tool_calls", None) or []
                    for tc in tcs:
                        idx = getattr(tc, "index", 0)
                        seen_indexes.append(idx)
                        if last_seen_idx is not None and idx != last_seen_idx:
                            # interleave check: did we ever observe idx flipping back-and-forth?
                            if last_seen_idx in seen_indexes[:-1]:
                                interleave_observed = True
                        last_seen_idx = idx
                        fn = getattr(tc, "function", None)
                        chunk_log.append({
                            "index": idx,
                            "id": getattr(tc, "id", None),
                            "name": getattr(fn, "name", None) if fn else None,
                            "arguments_piece": getattr(fn, "arguments", None) if fn else None,
                        })
                rec.notes["interleave_observed"] = interleave_observed
                rec.notes["distinct_indexes"] = sorted(set(seen_indexes))
                rec.notes["n_tool_chunks"] = len(chunk_log)
                # name-arrival: first chunk per index
                first_per_idx = {}
                for c in chunk_log:
                    if c["index"] not in first_per_idx:
                        first_per_idx[c["index"]] = c
                rec.notes["name_in_first_chunk"] = {
                    str(k): bool(v.get("name")) for k, v in first_per_idx.items()
                }
                # argument key boundary check — concat per index, then look for whitespace patterns
                concat_per_idx: dict[int, str] = defaultdict(str)
                for c in chunk_log:
                    if c["arguments_piece"]:
                        concat_per_idx[c["index"]] += c["arguments_piece"]
                rec.raw_excerpt = {"args_per_index": {str(k): v for k, v in concat_per_idx.items()}}
            print(
                f"  trial {i}: chunks={rec.notes['n_tool_chunks']} "
                f"indexes={rec.notes['distinct_indexes']} "
                f"interleave={rec.notes['interleave_observed']}"
            )
            rows.append(rec.to_jsonable())
            write(rec.to_jsonable())

    summarise_inplace(rows)
    print(f"raw → {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
