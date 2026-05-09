"""probe_1: stream a basic completion and dump every chunk shape.

Goal: build the canonical chunk-shape catalog so F2 client doesn't reinvent the
wheel each release. Specifically check:
  - first chunk: does it carry role / content?
  - middle chunks: is delta.content sometimes None? does delta have any extra fields?
  - final chunk: is `choices` empty? where does usage live?
  - is there ever a chunk whose only payload is `reasoning_content`?

Reference upstream pain: cline/cline#1594 (final-chunk delta access throws).
"""

from __future__ import annotations

import sys
from collections import Counter

from _common import (  # type: ignore
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


PROBE = "probe_1_streaming_basic"


def main() -> int:
    n = parse_n_arg(default=3)
    banner(PROBE, n)
    client = make_client()
    cfg = env_loaded()

    rows: list[dict] = []
    chunk_shape_counter: Counter = Counter()

    with raw_writer(PROBE) as (write, out_path):
        for i in range(n):
            rec = TrialRecord(probe=PROBE, trial_idx=i)
            chunks_observed: list[dict] = []
            with time_trial(rec):
                stream = client.chat.completions.create(
                    model=cfg["model"],
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": "Tell me a one-sentence haiku about TCP."},
                    ],
                    stream=True,
                    stream_options={"include_usage": True},
                    extra_body=THINKING_OFF,
                    max_tokens=128,
                )
                for chunk in stream:
                    snap = _snapshot_chunk(chunk)
                    chunks_observed.append(snap)
                    chunk_shape_counter[snap["shape"]] += 1
                    if snap.get("usage"):
                        rec.usage = snap["usage"]
                    if snap.get("finish_reason"):
                        rec.finish_reason = snap["finish_reason"]
                rec.notes["n_chunks"] = len(chunks_observed)
                rec.notes["empty_choices_final"] = chunks_observed and not chunks_observed[-1]["has_choices"]
                rec.raw_excerpt = {
                    "first_3": chunks_observed[:3],
                    "last_3": chunks_observed[-3:],
                }
            print(f"  trial {i}: {rec.status}  chunks={rec.notes.get('n_chunks')}  finish={rec.finish_reason}")
            if rec.error:
                print(f"    error: {rec.error}", file=sys.stderr)
            row = rec.to_jsonable()
            rows.append(row)
            write(row)

    print(f"\n[probe_1] chunk-shape distribution across {sum(chunk_shape_counter.values())} chunks:")
    for shape, count in chunk_shape_counter.most_common():
        print(f"  {shape}: {count}")
    summarise_inplace(rows)
    print(f"\nraw → {out_path}")
    return 0


def _snapshot_chunk(chunk) -> dict:
    """Compress a chunk into a row that's small enough to keep in raw dump."""
    choices = getattr(chunk, "choices", None) or []
    has_choices = bool(choices)
    delta = None
    finish_reason = None
    if has_choices:
        c0 = choices[0]
        finish_reason = getattr(c0, "finish_reason", None)
        delta = getattr(c0, "delta", None)
    has_reasoning = bool(getattr(delta, "reasoning_content", None)) if delta else False
    has_content = bool(getattr(delta, "content", None)) if delta else False
    has_tool = bool(getattr(delta, "tool_calls", None)) if delta else False
    usage = getattr(chunk, "usage", None)
    shape_parts = []
    if not has_choices:
        shape_parts.append("no_choices")
    if has_choices and delta is None:
        shape_parts.append("no_delta")
    if has_content:
        shape_parts.append("content")
    if has_reasoning:
        shape_parts.append("reasoning")
    if has_tool:
        shape_parts.append("tool_call")
    if finish_reason:
        shape_parts.append(f"finish={finish_reason}")
    if usage is not None:
        shape_parts.append("usage")
    return {
        "shape": "+".join(shape_parts) or "empty",
        "has_choices": has_choices,
        "has_delta": delta is not None,
        "has_content": has_content,
        "has_reasoning": has_reasoning,
        "has_tool": has_tool,
        "finish_reason": finish_reason,
        "usage": _u(usage),
    }


def _u(u):
    if u is None:
        return None
    if hasattr(u, "model_dump"):
        return u.model_dump()
    return getattr(u, "__dict__", str(u))


if __name__ == "__main__":
    raise SystemExit(main())
