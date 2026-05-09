"""probe_6: context-window boundaries (independent — no public bug reports yet).

Sends three deterministic prompts at ~64K / ~128K / ~200K tokens and records:
  - whether the call returned 200 / 400 / 422 (truncation rejection)
  - latency (cold vs warm — we run each tier twice)
  - prompt_tokens reported by server (does it match our local tiktoken estimate?)
  - finish_reason on a moderate max_tokens — does it cut at our request or earlier?
  - whether DeepSeek silently truncates the prefix vs hard-rejects

This is unique data — no community issue covers it yet. Goes straight into F1 §6.
"""

from __future__ import annotations

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


PROBE = "probe_6_context_limits"

# Tier sizes in tokens. We start small + add 200K only if smaller tiers succeed.
TIERS = [
    ("16k", 16 * 1024),
    ("64k", 64 * 1024 - 2000),
    ("128k", 128 * 1024 - 2000),
]


def main() -> int:
    banner(PROBE, len(TIERS) * 2)
    client = make_client()
    cfg = env_loaded()

    rows: list[dict] = []

    with raw_writer(PROBE) as (write, out_path):
        for tier_name, target_tokens in TIERS:
            for repeat in range(2):  # cold + warm
                rec = TrialRecord(probe=PROBE, trial_idx=0, notes={"tier": tier_name, "repeat": repeat})
                # ~4 chars per token rough fill; use boring ASCII so the tokenizer is uniform
                filler = ("background context block. " * (target_tokens))[: target_tokens * 4]
                with time_trial(rec):
                    resp = client.chat.completions.create(
                        model=cfg["model"],
                        messages=[
                            {"role": "system", "content": filler},
                            {"role": "user", "content": "Reply with exactly the word OK."},
                        ],
                        max_tokens=8,
                        extra_body=THINKING_OFF,
                    )
                    rec.finish_reason = resp.choices[0].finish_reason
                    usage = getattr(resp, "usage", None)
                    rec.usage = usage and usage.model_dump()
                    rec.raw_excerpt = {
                        "content": (resp.choices[0].message.content or "")[:80],
                        "approx_request_tokens": target_tokens,
                    }
                print(
                    f"  tier={tier_name} repeat={repeat} status={rec.status} "
                    f"latency={rec.latency_ms}ms finish={rec.finish_reason} "
                    f"server_prompt_tokens={rec.usage and rec.usage.get('prompt_tokens')} "
                    f"approx_local={target_tokens}"
                )
                rows.append(rec.to_jsonable())
                write(rec.to_jsonable())

    summarise_inplace(rows)
    print(f"\nraw → {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
