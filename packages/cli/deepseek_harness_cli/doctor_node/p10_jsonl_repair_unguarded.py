"""P10 — jsonl session repair truncates without the concurrency check its
sqlite sibling has.

Discovery: 0.1.2-alpha.1 (2026-08-27, tag cd5ef81).

0.1.2-alpha.1 ships "warn when automatically repairing a truncated
conversation-log tail and identify the affected conversation". The warning is
real (`session-persistence-jsonl/src/index.ts:459`, `logger.warn`). What was
not added is any guard around the destructive step it announces.

Both persistence backends implement the same `commitRepair(meta, tornMarker,
closers)` interface. They do not implement it with the same care:

  packages/session/session-persistence-sqlite/src/store.ts:214-236
    - opens `begin-immediate` (SQLite write transaction, cross-process)
    - re-reads the current rows and re-scans them
    - `if (current.tornFrom !== tornMarker) throw "repair is stale: physical
      tail no longer starts at seq N"`
    - `else if (current.tornFrom !== undefined) throw "repair omitted current
      torn tail at seq N"`

  packages/session/session-persistence-jsonl/src/index.ts:451-459
    - `await this.repair(meta, tornMarker.truncateTo)`   ← unconditional
    - appends recovered events + closers
    - `logger.warn(...)` after the fact

The jsonl path never re-validates that the tail it is about to discard is
still the tail it scanned. `repair()` (index.ts:~712) is a bare
`truncate(path, offset)` + fsync. `rollbackAppend()` (index.ts:~700) is the
same shape. And `packages/session/` contains **zero** occurrences of `flock`,
`O_EXCL`, `lockf`, or `withFileLock` — verified by grep at this tag, while
`packages/credentials/credentials-local/src/index.ts:684` uses `withFileLock`
from the monorepo's own `@deepseek-ai/dsh-atomic-write`.

Failure mode. Process A opens a session, scans, decides bytes [N..EOF] are a
crash tail. Before A calls `repair()`, process B appends a complete event at
offset N. A truncates to N. B's committed event is gone — B's in-memory seq
counter is now ahead of the file, and its next append lands at a seq the file
cannot account for. That is the P5 seq-gap corpus, reached through the repair
path instead of the append path, and the "affected conversation" named in the
new warning is the victim's, not the truncator's.

jsonl is not the exotic backend: `packages/bundle/base/package.json` depends
on `@deepseek-ai/dsh-session-persistence-jsonl`. sqlite — the implementation
that has the check — is the opt-in one.

This probe is offline. It cannot observe a race that has not happened, so it
reports exposure rather than damage: how many session logs exist, how many
live under a root that a second process could plausibly share, and whether
any already carry the torn-tail signature that `commitRepair` would act on.
Pair it with P5-seqgap, which reads the same corpus for the append-path
symptom.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from . import Probe, Verdict


_ROOTS = [
    "~/.dsh/sessions",
    "~/.deepseek-harness/sessions",
    "~/.config/dsh/sessions",
    "./.dsh/sessions",
]


def _find_logs() -> list[Path]:
    seen: set[Path] = set()
    out: list[Path] = []
    for root in _ROOTS:
        base = Path(os.path.expanduser(root))
        if not base.exists():
            continue
        for pattern in ("**/*.jsonl", "**/*.jsonl.zstd"):
            for p in base.glob(pattern):
                rp = p.resolve()
                if rp in seen:
                    continue
                seen.add(rp)
                out.append(p)
    return out


def _has_torn_tail(buf: bytes) -> bool:
    """A torn tail is trailing bytes after the last newline, or a final line
    that does not parse — exactly what scanLog hands to commitRepair as
    `tornMarker`."""
    if not buf:
        return False
    if not buf.endswith(b"\n"):
        return True
    last_nl = buf.rfind(b"\n", 0, len(buf) - 1)
    tail = buf[last_nl + 1:-1] if last_nl != -1 else buf[:-1]
    if not tail.strip():
        return False
    try:
        json.loads(tail.decode("utf-8", errors="replace"))
    except Exception:
        return True
    return False


def _run(_ctx: dict) -> Verdict:
    logs = _find_logs()
    ev = {
        "roots": _ROOTS,
        "scanned": len(logs),
        "torn": [],
        "zstd_skipped": 0,
        "upstream_ref": {
            "unguarded": "session-persistence-jsonl/src/index.ts:451-459",
            "guarded_sibling": "session-persistence-sqlite/src/store.ts:214-236",
            "lock_primitives_in_session_pkg": 0,
        },
    }

    if not logs:
        return Verdict(
            "skip",
            "no session logs found",
            detail=f"looked at: {', '.join(_ROOTS)}. Nothing for commitRepair "
                   "to truncate on this machine.",
            evidence=ev,
        )

    for p in logs:
        if str(p).endswith(".zstd"):
            ev["zstd_skipped"] += 1  # needs the private-format decoder
            continue
        try:
            buf = p.read_bytes()
        except OSError:
            continue
        if _has_torn_tail(buf):
            ev["torn"].append({"path": str(p), "bytes": len(buf)})

    if ev["torn"]:
        return Verdict(
            "warn",
            f"{len(ev['torn'])} session log(s) carry a torn tail that "
            "commitRepair will truncate unguarded",
            detail="On next open, the jsonl backend truncates each of these to "
                   "the last committed offset and logs a warning — with no "
                   "re-check that the discarded bytes are still the tail it "
                   "scanned (the sqlite backend does re-check, and throws "
                   "'repair is stale'). If a second dsh process appends to one "
                   "of these logs in that window, the appended event is "
                   "discarded silently. Mitigation: open each session from one "
                   "process at a time, or copy these logs aside before "
                   "reopening. Upstream: no lock primitive anywhere in "
                   "packages/session/ as of 0.1.2-alpha.1.",
            evidence=ev,
        )

    return Verdict(
        "pass",
        f"{len(logs)} session log(s), none currently torn",
        detail="No log is presently in the state that triggers the unguarded "
               "truncate. The exposure is structural rather than latent: "
               "commitRepair still has no staleness check and packages/session/ "
               "still has no cross-process lock, so this reflects current "
               "on-disk state, not a fixed defect.",
        evidence=ev,
    )


PROBE = Probe(
    id="P10-jsonl-repair-unguarded",
    title="jsonl session repair truncates without the staleness check its "
          "sqlite sibling has (0.1.2-alpha.1)",
    run=_run,
)
