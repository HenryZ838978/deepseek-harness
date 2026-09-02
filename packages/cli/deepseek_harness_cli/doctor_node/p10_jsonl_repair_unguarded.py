"""P10 — jsonl session repair truncates without a concurrency check, and is
now the only first-party implementation of the interface.

Discovery: 0.1.2-alpha.1 (2026-08-27, tag cd5ef81).
Re-verified unchanged on 0.1.2-alpha.2 (2026-08-30, tag 0a53fb55be) — source
and the published npm artifact both, see the note on jsonl's own docstring
below.
Re-verified unchanged on 0.1.2-alpha.4 (2026-09-01, tag 4e84901e), where the
comparison this probe was named after stopped existing — see "The sibling is
gone" below.

0.1.2-alpha.1 ships "warn when automatically repairing a truncated
conversation-log tail and identify the affected conversation". The warning is
real (`session-persistence-jsonl/src/index.ts:459`, `logger.warn`). What was
not added is any guard around the destructive step it announces.

Through alpha.2, two backends implemented the same `commitRepair` interface,
and they did not implement it with the same care:

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
    - its own docstring: "Two fsync'd steps — the seam does not require this
      to be atomic." The non-atomicity is deliberate and documented; what the
      sqlite sibling added on top of it was the staleness re-check, and that
      is what jsonl lacks.

The sibling is gone. 0.1.2-alpha.3 (2026-08-31) removed the sqlite session
backend outright — `.agents/notes/implemented/simplification/
2026-08-30-jsonl-only-session-persistence.md` states the decision plainly:
"`@deepseek-ai/dsh-session-persistence-jsonl` is the sole first-party
implementation of `ctx.sessionPersistence`", and the sqlite "package, its
schema resources, backend-specific tests, configuration surface, and Windows
differential lane are absent." The note is candid about the cost — it
"removes the stronger database/WAL storage option" — and the removal is
defensible on its own terms (one authoritative format, one durability path,
a simpler migration story).

The effect on this defect, however, is that the guarded implementation is the
one that was deleted. Verified on alpha.4:

  - `grep -rn "async commitRepair" --include="*.ts" packages/ | grep -v tests`
    returns exactly one production hit:
    `session-persistence-jsonl/src/index.ts:469` — still six lines, still no
    staleness check, signature now `(storage, tornMarker, closers)`.
  - `packages/session/` contains no `*sqlite*` directory. The surviving
    `packages/storage/storage-sqlite` is a generic domain-KV provider and
    `packages/session-query/session-query-sqlite` is a disposable FTS index;
    neither implements `commitRepair` (grep: zero hits in either).
  - npm dist-tags for `@deepseek-ai/dsh-session-persistence-sqlite` still
    point `alpha` at `0.1.2-alpha.2`: the package stopped being published.

So this probe keeps its subject and loses its control group. What used to be
"the default backend is the careless one of two" is now "the careless one is
the only one." The staleness check is not merely unimplemented here — as of
alpha.3 it is not implemented anywhere in the tree.

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

jsonl is not the exotic backend: `packages/bundle/base/package.json:73`
depends on `@deepseek-ai/dsh-session-persistence-jsonl`. Since alpha.3 it is
not merely the default — it is the only first-party option there is.

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
            "unguarded": "session-persistence-jsonl/src/index.ts:469 (alpha.4)",
            "guarded_sibling": "removed in 0.1.2-alpha.3 — see "
                               "notes/implemented/simplification/"
                               "2026-08-30-jsonl-only-session-persistence.md",
            "production_commitrepair_impls": 1,
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
                   "scanned. If a second dsh process appends to one of these "
                   "logs in that window, the appended event is discarded "
                   "silently. Mitigation: open each session from one process "
                   "at a time, or copy these logs aside before reopening. "
                   "Upstream: no lock primitive anywhere in packages/session/ "
                   "as of 0.1.2-alpha.4, and since alpha.3 removed the sqlite "
                   "backend, jsonl is the only first-party implementation — "
                   "the staleness check that backend had is now absent from "
                   "the tree entirely.",
            evidence=ev,
        )

    return Verdict(
        "pass",
        f"{len(logs)} session log(s), none currently torn",
        detail="No log is presently in the state that triggers the unguarded "
               "truncate. The exposure is structural rather than latent: "
               "commitRepair still has no staleness check and packages/session/ "
               "still has no cross-process lock, so this reflects current "
               "on-disk state, not a fixed defect. As of 0.1.2-alpha.3 the one "
               "backend that did carry the check was removed, so no first-party "
               "implementation has it.",
        evidence=ev,
    )


PROBE = Probe(
    id="P10-jsonl-repair-unguarded",
    title="jsonl session repair truncates without a staleness check, and is "
          "the only backend left (0.1.2-alpha.1 → alpha.4)",
    run=_run,
)
