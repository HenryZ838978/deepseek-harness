"""probe_5: prefix-cache hit / miss sensitivity.

Three sub-experiments per run:

  S1  Repeat the SAME 1500-token prefix N times.
        → expect cache_hit_tokens to climb from 0 to ~prompt_tokens after the
          first request hits the persisted-cache trigger.

  S2  Repeat with one BYTE flipped in the MIDDLE of the system prompt.
        → expect a hard cache miss (DeepSeek's matcher only does prefix-from-0).

  S3  Repeat with one BYTE flipped at the VERY END of the prefix.
        → expect partial hit (everything before the flip).

We also normalise both `prompt_cache_hit_tokens` and `prompt_tokens_details.cached_tokens`
into a single dict so the cache hit is visible regardless of which field name the
SDK populates (pi-mono#3880).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from _common import (  # type: ignore
    THINKING_OFF,
    TrialRecord,
    banner,
    env_loaded,
    long_prefix_messages,
    make_client,
    parse_n_arg,
    raw_writer,
    summarise_inplace,
    time_trial,
)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from deepseek_harness.cache import normalize_usage  # noqa: E402


PROBE = "probe_5_cache_prefix_sensitivity"


def main() -> int:
    n = parse_n_arg(default=12)
    banner(PROBE, n)
    client = make_client()
    cfg = env_loaded()

    base_messages = long_prefix_messages(token_target=1500)

    rows: list[dict] = []
    with raw_writer(PROBE) as (write, out_path):
        # ----- S1 identical prefix -----
        print("\n[probe_5/S1] identical prefix (expect cache hit to climb)")
        for i in range(n):
            rec = _hit(client, cfg["model"], base_messages, scenario="S1_identical", trial=i)
            rows.append(rec.to_jsonable())
            write(rec.to_jsonable())
            print(f"  S1#{i}: hit={rec.usage.get('prompt_cache_hit_tokens') if rec.usage else '?'}/"
                  f"{rec.usage.get('prompt_tokens') if rec.usage else '?'} "
                  f"rate={rec.usage.get('cache_hit_rate') if rec.usage else '?'}")

        # ----- S2 mid-prefix mutation -----
        print("\n[probe_5/S2] flip a middle char each call (expect ~0% hit)")
        for i in range(n):
            mutated = _mutate(base_messages, position="middle", trial=i)
            rec = _hit(client, cfg["model"], mutated, scenario="S2_mid_flip", trial=i)
            rows.append(rec.to_jsonable())
            write(rec.to_jsonable())
            print(f"  S2#{i}: hit={rec.usage.get('prompt_cache_hit_tokens') if rec.usage else '?'} "
                  f"rate={rec.usage.get('cache_hit_rate') if rec.usage else '?'}")

        # ----- S3 tail mutation -----
        print("\n[probe_5/S3] flip the LAST char of system prefix (expect partial hit)")
        for i in range(n):
            mutated = _mutate(base_messages, position="tail", trial=i)
            rec = _hit(client, cfg["model"], mutated, scenario="S3_tail_flip", trial=i)
            rows.append(rec.to_jsonable())
            write(rec.to_jsonable())
            print(f"  S3#{i}: hit={rec.usage.get('prompt_cache_hit_tokens') if rec.usage else '?'} "
                  f"rate={rec.usage.get('cache_hit_rate') if rec.usage else '?'}")

    summarise_inplace(rows)
    print(f"raw → {out_path}")
    return 0


def _hit(client, model, messages, *, scenario, trial) -> TrialRecord:
    rec = TrialRecord(probe=PROBE, trial_idx=trial, notes={"scenario": scenario})
    with time_trial(rec):
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=4,
            temperature=0,
            extra_body=THINKING_OFF,
        )
        rec.finish_reason = resp.choices[0].finish_reason
        usage = getattr(resp, "usage", None)
        rec.usage = normalize_usage(usage) if usage else None
    return rec


def _mutate(messages: list[dict], *, position: str, trial: int) -> list[dict]:
    out = [dict(m) for m in messages]
    sysmsg = out[0]
    text = sysmsg["content"]
    if position == "middle":
        idx = len(text) // 2 + (trial % 7)
    else:  # tail
        idx = max(0, len(text) - 1 - (trial % 5))
    flipped = text[:idx] + chr(((ord(text[idx]) - 32 + 1) % 95) + 32) + text[idx + 1:]
    sysmsg["content"] = flipped
    return out


if __name__ == "__main__":
    raise SystemExit(main())
