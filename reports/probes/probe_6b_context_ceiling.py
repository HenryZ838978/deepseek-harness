"""probe_6b: push context past 128K to find rejection ceiling.

probe_6 found that DeepSeek's v4 tokenizer compresses our repeating-English filler
~1.6× more aggressively than the cl100k_base estimate, so "200K" of our local
filler was actually only ~80K server tokens. This probe uses denser filler
(random words) and walks up tiers until rejection.
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

from _common import (  # type: ignore
    THINKING_OFF,
    TrialRecord,
    banner,
    env_loaded,
    make_client,
    raw_writer,
    summarise_inplace,
    time_trial,
)


PROBE = "probe_6b_context_ceiling"


# probe_6b first run discovered ceiling is 1,048,576 tokens (1M).
# Walk near the ceiling to map: cold latency, max accepted, hard reject behavior.
# Random-letter words hit ~3.6 tokens each on average (validated empirically below).
# Multiply target_server_tokens by 0.28 to get target word count.
TARGET_SERVER_TOKENS = [200_000, 500_000, 800_000, 1_000_000, 1_050_000, 1_048_576]


def random_filler(target_server_tokens: int) -> str:
    rng = random.Random(0xC0FFEE)
    word_count = int(target_server_tokens * 0.28)
    words = []
    for _ in range(word_count):
        wlen = rng.randint(3, 9)
        words.append("".join(rng.choices("abcdefghijklmnopqrstuvwxyz", k=wlen)))
    return " ".join(words)


def main() -> int:
    banner(PROBE, len(TARGET_SERVER_TOKENS))
    client = make_client()
    cfg = env_loaded()

    rows: list[dict] = []
    print("[probe_6b] using random-word filler (no tokenizer compression)")
    print("[probe_6b] walking up tiers until 4xx ceiling")

    with raw_writer(PROBE) as (write, out_path):
        for target in TARGET_SERVER_TOKENS:
            rec = TrialRecord(probe=PROBE, trial_idx=0, notes={"server_target": target})
            with time_trial(rec):
                filler = random_filler(target)
                resp = client.chat.completions.create(
                    model=cfg["model"],
                    messages=[
                        {"role": "system", "content": filler},
                        {"role": "user", "content": "Reply with the literal word OK."},
                    ],
                    max_tokens=8,
                    extra_body=THINKING_OFF,
                )
                rec.finish_reason = resp.choices[0].finish_reason
                usage = getattr(resp, "usage", None)
                rec.usage = usage and usage.model_dump()
                rec.raw_excerpt = {"content": (resp.choices[0].message.content or "")[:80]}
            print(
                f"  target={target:>7} status={rec.status} latency={rec.latency_ms}ms "
                f"server_tokens={rec.usage and rec.usage.get('prompt_tokens')} "
                f"err={rec.error and rec.error.get('type')}"
            )
            if rec.error:
                print(f"    error: {rec.error['message'][:200]}")
                # bail on first hard reject — no point spending more on bigger ones
                rows.append(rec.to_jsonable())
                write(rec.to_jsonable())
                break
            rows.append(rec.to_jsonable())
            write(rec.to_jsonable())

    summarise_inplace(rows)
    print(f"\nraw → {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
