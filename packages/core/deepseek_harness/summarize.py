"""`python -m deepseek_harness.summarize <raw_dir> <out_dir>` —
roll up findings/raw/probe_*/<utc>.jsonl into one markdown summary per probe.

Each probe writes one row per trial as JSONL. We aggregate counts, error rates,
cache-hit deltas, latency percentiles, and emit a probe-level markdown.
"""

from __future__ import annotations

import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: python -m deepseek_harness.summarize <raw_dir> <out_dir>", file=sys.stderr)
        return 2
    raw_dir = Path(sys.argv[1])
    out_dir = Path(sys.argv[2])
    out_dir.mkdir(parents=True, exist_ok=True)

    if not raw_dir.exists():
        print(f"no raw_dir: {raw_dir}", file=sys.stderr)
        return 0

    for probe_dir in sorted(p for p in raw_dir.iterdir() if p.is_dir()):
        rows = []
        for jsonl in sorted(probe_dir.glob("*.jsonl")):
            with jsonl.open() as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rows.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        if not rows:
            continue
        out_path = out_dir / f"{probe_dir.name}.md"
        out_path.write_text(_summarise(probe_dir.name, rows))
        print(f"wrote {out_path}  ({len(rows)} rows)")
    return 0


def _summarise(probe: str, rows: list[dict]) -> str:
    lines: list[str] = [f"# {probe} summary", "", f"trials: **{len(rows)}**", ""]

    statuses = Counter(r.get("status", "?") for r in rows)
    lines.append("## status")
    for k, v in statuses.most_common():
        lines.append(f"- `{k}`: {v} ({v/len(rows):.1%})")
    lines.append("")

    finish_reasons = Counter(r.get("finish_reason", "?") for r in rows if r.get("finish_reason"))
    if finish_reasons:
        lines.append("## finish_reason")
        for k, v in finish_reasons.most_common():
            lines.append(f"- `{k}`: {v} ({v/len(rows):.1%})")
        lines.append("")

    salvages = [r for r in rows if r.get("salvage")]
    if salvages:
        lines.append(f"## tool-call salvages: **{len(salvages)} / {len(rows)}** ({len(salvages)/len(rows):.1%})")
        pat = Counter(r["salvage"].get("pattern", "?") for r in salvages)
        for p, c in pat.most_common():
            lines.append(f"- `{p}`: {c}")
        lines.append("")

    latencies = [r["latency_ms"] for r in rows if isinstance(r.get("latency_ms"), (int, float))]
    if latencies:
        lines.append("## latency_ms")
        lines.append(
            f"- p50={statistics.median(latencies):.0f}  "
            f"p90={_pct(latencies, 0.9):.0f}  "
            f"p99={_pct(latencies, 0.99):.0f}  "
            f"max={max(latencies):.0f}"
        )
        lines.append("")

    cache_rates = [r["usage"]["cache_hit_rate"] for r in rows if isinstance(r.get("usage"), dict) and "cache_hit_rate" in r.get("usage", {})]
    if cache_rates:
        lines.append("## cache_hit_rate")
        lines.append(
            f"- mean={statistics.mean(cache_rates):.2%}  "
            f"median={statistics.median(cache_rates):.2%}  "
            f"min={min(cache_rates):.2%}  "
            f"max={max(cache_rates):.2%}"
        )
        lines.append("")

    errors = defaultdict(list)
    for r in rows:
        if r.get("error"):
            errors[r["error"].get("type", "?")].append(r["error"].get("message", "?"))
    if errors:
        lines.append("## errors by type")
        for t, msgs in errors.items():
            lines.append(f"- `{t}` × {len(msgs)}")
            uniq = list(dict.fromkeys(msgs))[:3]
            for m in uniq:
                lines.append(f"  - {m[:200]}")
        lines.append("")

    return "\n".join(lines) + "\n"


def _pct(values: list[float], q: float) -> float:
    s = sorted(values)
    idx = max(0, min(len(s) - 1, int(q * (len(s) - 1))))
    return s[idx]


if __name__ == "__main__":
    raise SystemExit(main())
