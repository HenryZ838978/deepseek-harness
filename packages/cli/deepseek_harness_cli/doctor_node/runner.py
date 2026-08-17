"""Runner: execute the registry, print the four-state table or JSON."""
from __future__ import annotations

import json
import os
import sys
from typing import Any

from . import REGISTRY, Verdict


_GLYPH = {"pass": "✓", "warn": "!", "fail": "✗", "skip": "·"}
_COLOR = {"pass": "green", "warn": "yellow", "fail": "red", "skip": "dim"}


def run(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(prog="dsh doctor --node")
    p.add_argument("--json", action="store_true", help="Machine-readable output.")
    p.add_argument("--only", help="Comma-separated probe ids to run.")
    p.add_argument("--url", default="http://127.0.0.1:3080", help="Target dsh web url for serve-health probe.")
    args = p.parse_args(argv or [])

    ctx: dict[str, Any] = {
        "env": dict(os.environ),
        "dsh_url": args.url,
    }

    probes = REGISTRY()
    if args.only:
        wanted = set(args.only.split(","))
        probes = [pb for pb in probes if pb.id in wanted]

    results: list[tuple[str, str, Verdict]] = []
    for pb in probes:
        missing = [n for n in pb.needs if not ctx["env"].get(n)]
        if missing:
            v = Verdict("skip", f"needs env: {','.join(missing)}")
        else:
            try:
                v = pb.run(ctx)
            except Exception as e:  # probe crashes must not kill the runner
                v = Verdict("fail", f"probe crashed: {type(e).__name__}: {e}")
        results.append((pb.id, pb.title, v))

    if args.json:
        print(json.dumps(
            [{"id": i, "title": t, "state": v.state, "summary": v.summary,
              "detail": v.detail, "evidence": v.evidence} for i, t, v in results],
            indent=2, ensure_ascii=False,
        ))
    else:
        _print_table(results)

    return 0 if all(v.state != "fail" for _, _, v in results) else 1


def _print_table(results: list) -> None:
    try:
        from rich.console import Console
        from rich.table import Table
        c = Console()
        t = Table(title="dsh doctor --node (witness probes for official Node harness)")
        t.add_column("", width=2)
        t.add_column("probe", style="bold cyan")
        t.add_column("title")
        t.add_column("verdict")
        for pid, title, v in results:
            t.add_row(
                f"[{_COLOR[v.state]}]{_GLYPH[v.state]}[/]",
                pid,
                title,
                f"[{_COLOR[v.state]}]{v.state.upper()}[/] {v.summary}",
            )
        c.print(t)
        for pid, _, v in results:
            if v.detail:
                c.print(f"[dim]  · {pid}: {v.detail}[/]")
    except ImportError:
        for pid, title, v in results:
            print(f"{_GLYPH[v.state]} {pid:<10} {v.state.upper():<5} {title} — {v.summary}")
            if v.detail:
                print(f"    · {v.detail}")
