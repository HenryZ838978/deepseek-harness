"""P10 — jsonl session repair and the cross-process write lease.

Discovery: 0.1.2-alpha.1 (2026-08-27, tag cd5ef81).
Re-verified unchanged on 0.1.2-alpha.2 (2026-08-30, tag 0a53fb55be),
0.1.2-alpha.4 (2026-09-01, tag 4e84901e) and 0.1.2-rc.1 (2026-09-03, tag
a66e4702).

FIXED in 0.1.5-alpha.1 (2026-09-08, tag 5dda764e). The fix is the cross-process
session write lease — `.agents/notes/implemented/feature/
2026-08-31-cross-process-session-write-lease.md`, whose "Problem" section
states this probe's failure mode almost verbatim ("two processes — two CLI
sessions, or a host beside an SDK runtime — could write-open the same session
and interleave appends into one log file, tearing compressed frames and seq
contiguity"). The lease in `session-persistence-jsonl/src/lease.ts` takes a
non-blocking POSIX `flock(2)` (or a Windows kernel semaphore) on `session.lock`
beside the log, held for the life of the write handle and released by the
kernel on process death. Contention maps to `SessionAlreadyOwnedError`.

The lease closes the repair race because it is held *before* the truncate:

  - `index.ts:370` — `lease = await this.acquireLease(id, ...)` runs inside the
    write-open path, so a second writer to an existing artifact is rejected at
    open, not merely at append.
  - `storage.ts:322` — `persistContiguous` calls `await this.ensureLease()`
    before it commits a pending torn-tail repair (`storage.ts:329`
    `truncateTornTail`). A writer that reaches `repair()` therefore already
    holds the lock; the process-B append that used to be discarded silently
    can no longer happen.

Verified at tag 183f08e9 (0.1.5-rc.1): `grep -rn "flock|lockf|O_EXCL|
withFileLock|tryLockExclusive|SessionAlreadyOwned" --include="*.ts"
packages/session/ | grep -v test` returns 19 hits, against **0** at
0.1.2-rc.1 — the grep an earlier revision of this probe used as its
open-defect proof now proves the opposite.

This probe is offline and reads on-disk state, so it cannot observe the
upstream source; it reports what it *can* see — whether any local session log
currently carries the torn-tail signature that the repair path acts on — and
records which upstream generation fixed the race. Pass on logs whose tail is
intact, warn on a log that is torn, since only a pre-0.1.5 harness would still
truncate it unguarded. Pair it with P5-seqgap, which reads the same corpus for
the append-path symptom.
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
    that does not parse — exactly what scanLog hands to the repair path as its
    truncation offset."""
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
            "state": "fixed",
            "fixed_in": "0.1.5-alpha.1 (2026-09-08, tag 5dda764e)",
            "mechanism": "session-persistence-jsonl/src/lease.ts — kernel "
                         "flock(2) / Win32 semaphore on session.lock, taken at "
                         "write-open (index.ts:370) and before torn-tail repair "
                         "(storage.ts:322)",
            "grep": "packages/session/ lock-primitive hits: 0 at 0.1.2-rc.1, "
                    "19 at 0.1.5-rc.1",
        },
    }

    if not logs:
        return Verdict(
            "skip",
            "no session logs found",
            detail=f"looked at: {', '.join(_ROOTS)}. Nothing for the jsonl "
                   "repair path to truncate on this machine.",
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
            f"{len(ev['torn'])} session log(s) carry a torn tail",
            detail="A harness that predates 0.1.5-alpha.1 would truncate each "
                   "of these to the last committed offset with no re-check "
                   "that the discarded bytes are still the tail it scanned — "
                   "and, with no cross-process lease yet, a second dsh process "
                   "appending in that window would lose its committed event "
                   "silently. From 0.1.5-alpha.1 the write-open path takes a "
                   "kernel lease first, so the race is closed regardless of "
                   "this tail: the truncate can no longer run concurrently "
                   "with another writer. Read this as a 'your harness is old' "
                   "signal rather than an open upstream defect — upgrade the "
                   "Node harness to 0.1.5-alpha.1 or later.",
            evidence=ev,
        )

    return Verdict(
        "pass",
        f"{len(logs)} session log(s), none currently torn",
        detail="No local log is presently in the state the repair path acts "
               "on, and the repair race itself was fixed upstream in "
               "0.1.5-alpha.1 by the cross-process write lease. As of "
               "0.1.2-alpha.3, jsonl is the only first-party session backend, "
               "so the same check now guards the only implementation there is.",
        evidence=ev,
    )


PROBE = Probe(
    id="P10-jsonl-repair-race",
    title="jsonl session repair raced a second writer with no cross-process "
          "lock (0.1.2-alpha.1 → alpha.4; FIXED 0.1.5-alpha.1 write lease)",
    run=_run,
)
