"""dsh doctor --node — witness probes for the official Node harness.

Each probe returns a Verdict. The registry runs them in order and prints a
four-state table (PASS/WARN/FAIL/SKIP). JSON output via --json for CI.

Design: probes are pure functions of (env, argv), no shared state. Adding
a probe = add a file under this package and register it in REGISTRY below.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Literal

State = Literal["pass", "warn", "fail", "skip"]


@dataclass
class Verdict:
    state: State
    summary: str
    detail: str = ""
    evidence: dict = field(default_factory=dict)


@dataclass
class Probe:
    id: str
    title: str
    run: Callable[[dict], Verdict]
    needs: tuple[str, ...] = ()  # env var names required; else SKIP


def _load_registry() -> list[Probe]:
    from .p1_reasoner_wire import PROBE as P1
    from .p2_bom_manifest import PROBE as P2
    from .p3_serve_health import PROBE as P3
    from .p4_spill_dir import PROBE as P4
    return [P1, P2, P3, P4]


REGISTRY = _load_registry
