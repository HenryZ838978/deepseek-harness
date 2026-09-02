"""P4 — 勇哥⑥: OutputCollector.spillAll has no try/catch; failed spill
open/write escapes the stream 'data' callback and drops the whole harness
to exit 1.

Confirmed 2026-08-17 on rc.6 compiled artifact
`dsh-subprocess-local/lib/index.js` ~393/417: `openSync/writeSync` bare,
sibling `discardSpill` is guarded. Asymmetry is the tell.

Still present on 0.1.2-alpha.4 (2026-09-01, tag 4e84901e), and the asymmetry
is unchanged: `subprocess-local/src/spawn.ts:156-174` (`spillAll`) contains
zero `try`, while `discardSpill` immediately below it contains three.

Do not misread alpha.4's change here as a fix. The spill open was hardened
against a *different* threat — it is now
`openSync(this.spillFile, 'wx', 0o600)` with a `randomBytes(6)` suffix and a
comment naming its purpose: "defeats spill-path prediction and symlink
planting in shared tmp dirs." That is path-security hardening. It does not
add error handling, and `'wx'` (O_EXCL) gives `openSync` one more way to
throw, not fewer. The ENOSPC path this probe describes is untouched:
`push()` at spawn.ts:134 still calls `spillAll(chunk)` bare, inside a
stream 'data' callback.

Static preflight: check whether the spill directory dsh will pick is
writable *right now*. If not, dsh will crash the first time a subprocess
produces enough output to trigger spill.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

from . import Probe, Verdict


def _spill_candidates() -> list[Path]:
    # dsh spills to os.tmpdir() in the compiled artifact; give the user
    # visibility into all locations tempfile might choose.
    seen: set[Path] = set()
    out: list[Path] = []
    for c in (tempfile.gettempdir(),
              os.environ.get("TMPDIR"),
              os.environ.get("TEMP"),
              os.environ.get("TMP"),
              "/tmp"):
        if not c:
            continue
        p = Path(c)
        rp = p.resolve() if p.exists() else p
        if rp in seen:
            continue
        seen.add(rp)
        out.append(p)
    return out


def _writable(p: Path) -> tuple[bool, str]:
    if not p.exists():
        return False, "does not exist"
    if not p.is_dir():
        return False, "not a directory"
    try:
        probe = p / f".dsh-doctor-probe-{os.getpid()}"
        probe.write_bytes(b"x")
        probe.unlink()
    except OSError as e:
        return False, f"{type(e).__name__}: {e}"
    return True, "ok"


def _run(_ctx: dict) -> Verdict:
    cands = _spill_candidates()
    rows = [(str(p), *_writable(p)) for p in cands]
    bad = [(path, why) for path, ok, why in rows if not ok]
    ev = {"candidates": [{"path": p, "writable": ok, "why": why} for p, ok, why in rows]}

    if not rows:
        return Verdict("warn", "no tmp dir candidates identified", evidence=ev)
    if bad:
        return Verdict(
            "fail",
            f"{len(bad)}/{len(rows)} spill candidate(s) unwritable — dsh will exit 1 on subprocess spill",
            detail="; ".join(f"{p}: {why}" for p, why in bad),
            evidence=ev,
        )
    return Verdict(
        "pass",
        f"all {len(rows)} spill candidate(s) writable",
        detail="Note: this only guards against the *current* state. Container "
               "restarts, permission changes, or full disks can flip it. The "
               "underlying defect is in dsh-subprocess-local (no try/catch "
               "around openSync/writeSync in spillAll).",
        evidence=ev,
    )


PROBE = Probe(
    id="P4-spill",
    title="subprocess spill directory writable (spillAll no try/catch)",
    run=_run,
)
