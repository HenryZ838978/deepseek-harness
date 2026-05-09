"""probe_9: reasoning_content runaway / V8 Invalid-string-length scenario.

Real-world trigger (from a ChatWise user screenshot, 2026-05-09):

  > Electron / Node JS engine (V8) caps a single string at ~512 MB.
  > When DeepSeek native API streams a long reasoning_content,
  > ChatWise concatenates it into ONE string buffer and crashes with
  > `RangeError: Invalid string length`.

The community-cited triggers are exactly the DEFAULT shape of the official
DeepSeek example code:
  - thinking enabled
  - no `max_tokens` cap
  - reasoner has no truncation on `reasoning_content`
  - streaming chunks accumulated into one growing string

We mirror that shape EXACTLY (no salvage, no helper from our F2 library —
just `from openai import OpenAI`, just like the official quickstart). The
probe records:

  - cumulative reasoning_content bytes vs wall-clock seconds
  - whether the model loops (same N-gram repeating)
  - finish_reason, total tokens, total cost
  - SAFETY: bail at REASONING_BAIL_BYTES so we don't actually pay for 100MB

Use prompts that historically trigger long thinking:
  T1 paradox:   "Is this statement true: this statement is false?"
  T2 chain:     "Think step-by-step about every step of computing 17!"
  T3 self-doubt:"You wrote 'X'. Verify it word by word. Then verify your verification."
"""

from __future__ import annotations

import os
import sys
import time
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

# Reuse only TrialRecord / writer / banner — NOT the wrapped client.
from _common import (  # type: ignore
    TrialRecord,
    banner,
    env_loaded,
    raw_writer,
    summarise_inplace,
    time_trial,
)


PROBE = "probe_9_reasoning_runaway"

# Bail before we get charged for a real 512MB monster — but go big enough to
# observe whether reasoning is BOUNDED naturally or unbounded.
REASONING_BAIL_BYTES = 1_500_000  # ~1.5 MB → still cheap, well above any healthy reasoning length


PROMPTS = {
    "T1_paradox": (
        "Carefully analyse the following self-referential statement and determine "
        "whether it is true or false. Walk through every angle of analysis you can "
        "think of, be exhaustive: 'This statement is false.' "
        "Do not give up; keep reasoning until you reach a confident verdict."
    ),
    "T2_long_chain": (
        "Compute 17! by long-hand. Write out every single intermediate multiplication "
        "(1*2, then *3, then *4, …, then *17) and double-check each step before moving on. "
        "Do not skip any step."
    ),
    "T3_self_doubt": (
        "You will write a 100-word essay about prime numbers. After writing, verify it "
        "word by word for accuracy. Then verify your verification. Then re-verify the "
        "verification of your verification. Continue this self-checking until you are absolutely sure."
    ),
}


def main() -> int:
    banner(PROBE, len(PROMPTS))
    cfg = env_loaded()

    # Mirror the DeepSeek official quickstart EXACTLY — no kit, no salvage.
    load_dotenv()
    client = OpenAI(
        api_key=os.environ["DEEPSEEK_API_KEY"],
        base_url=cfg["base_url"],
    )

    rows: list[dict] = []
    print(f"[{PROBE}] safety: aborting any trial whose reasoning_content exceeds "
          f"{REASONING_BAIL_BYTES/1_000_000:.1f} MB")

    with raw_writer(PROBE) as (write, out_path):
        for prompt_name, prompt_text in PROMPTS.items():
            rec = TrialRecord(probe=PROBE, trial_idx=0, notes={"prompt": prompt_name})
            t0 = time.perf_counter()
            reasoning_buf: list[str] = []
            content_buf: list[str] = []
            reasoning_bytes = 0
            content_bytes = 0
            n_chunks = 0
            n_reasoning_chunks = 0
            sample_at = [10_000, 100_000, 500_000, 1_000_000]  # bytes
            sample_records: list[dict] = []
            bailed = False
            finish_reason = None
            usage = None

            with time_trial(rec):
                # NO max_tokens, NO thinking flag — exactly like the official quickstart
                # (which means thinking defaults to enabled on v4-pro).
                stream = client.chat.completions.create(
                    model=cfg["model"],
                    messages=[{"role": "user", "content": prompt_text}],
                    stream=True,
                    stream_options={"include_usage": True},
                )
                for chunk in stream:
                    n_chunks += 1
                    choices = getattr(chunk, "choices", None) or []
                    if getattr(chunk, "usage", None) is not None:
                        usage = chunk.usage.model_dump()
                    if not choices:
                        continue
                    delta = getattr(choices[0], "delta", None)
                    if delta is None:
                        continue
                    rc = getattr(delta, "reasoning_content", None)
                    if rc:
                        reasoning_buf.append(rc)
                        reasoning_bytes += len(rc.encode("utf-8"))
                        n_reasoning_chunks += 1
                        # checkpoint sampling
                        while sample_at and reasoning_bytes >= sample_at[0]:
                            threshold = sample_at.pop(0)
                            sample_records.append({
                                "byte_threshold": threshold,
                                "elapsed_s": round(time.perf_counter() - t0, 2),
                                "n_chunks": n_chunks,
                                "preview_tail": "".join(reasoning_buf)[-200:],
                            })
                        if reasoning_bytes >= REASONING_BAIL_BYTES:
                            bailed = True
                            print(f"  [{prompt_name}] BAIL — reasoning hit "
                                  f"{reasoning_bytes/1_000_000:.2f} MB at t={time.perf_counter()-t0:.1f}s")
                            try:
                                stream.close()
                            except Exception:
                                pass
                            break
                    cc = getattr(delta, "content", None)
                    if cc:
                        content_buf.append(cc)
                        content_bytes += len(cc.encode("utf-8"))
                    fr = getattr(choices[0], "finish_reason", None)
                    if fr:
                        finish_reason = fr

                rec.finish_reason = finish_reason
                rec.usage = usage
                rec.notes["bailed_safety"] = bailed
                rec.notes["reasoning_bytes"] = reasoning_bytes
                rec.notes["content_bytes"] = content_bytes
                rec.notes["n_chunks"] = n_chunks
                rec.notes["n_reasoning_chunks"] = n_reasoning_chunks
                rec.notes["sample_records"] = sample_records

                # detect looping: count repeat of any 80-char window
                loop_score, loop_excerpt = _loop_score("".join(reasoning_buf))
                rec.notes["loop_score"] = loop_score
                rec.raw_excerpt = {
                    "reasoning_head": "".join(reasoning_buf)[:300],
                    "reasoning_tail": "".join(reasoning_buf)[-300:],
                    "content": "".join(content_buf)[:300],
                    "loop_excerpt": loop_excerpt,
                }

            print(
                f"  [{prompt_name}] reasoning_bytes={reasoning_bytes:>9}  "
                f"content_bytes={content_bytes:>5}  chunks={n_chunks:>4}  "
                f"finish={finish_reason}  bailed={bailed}  loop_score={loop_score}"
            )
            rows.append(rec.to_jsonable())
            write(rec.to_jsonable())

    summarise_inplace(rows)
    print(f"\n[{PROBE}] sample timeline (per byte threshold):")
    for r in rows:
        for s in r["notes"].get("sample_records", []):
            print(f"  prompt={r['notes']['prompt']:<14} threshold={s['byte_threshold']:>8}B  t={s['elapsed_s']:>5.1f}s  chunks={s['n_chunks']}")
    print(f"\nraw → {out_path}")
    return 0


def _loop_score(text: str, window: int = 80) -> tuple[int, str]:
    """Detect whether the model is looping the same ~80-char fragment.

    Returns (max_repeat_count, longest_loop_excerpt). High value = strong loop.
    """
    if len(text) < window * 3:
        return 0, ""
    counter: Counter = Counter()
    for i in range(0, len(text) - window, window // 2):
        counter[text[i:i + window]] += 1
    if not counter:
        return 0, ""
    top, count = counter.most_common(1)[0]
    return count, top if count >= 3 else ""


if __name__ == "__main__":
    raise SystemExit(main())
