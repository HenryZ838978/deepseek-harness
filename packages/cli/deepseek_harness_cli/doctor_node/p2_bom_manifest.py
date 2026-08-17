"""P2 — 2798: dsh plugin manifests with a UTF-8 BOM crash `dsh plugin add`.

Root cause: `dsh-app-boot/lib/index.js:453` and `:548` call `JSON.parse`
directly on the file contents. `feff` / `stripBOM` never appears in the
compiled artifact. A single-byte U+FEFF at file start is enough.

This probe walks candidate manifest roots and reports any file starting
with 0xEF 0xBB 0xBF. Offline — no key needed.
"""
from __future__ import annotations

import os
from pathlib import Path

from . import Probe, Verdict


_ROOTS = [
    "~/.dsh",
    "~/.deepseek-harness",
    "~/.config/dsh",
    "./.dsh",
]


def _iter_manifests() -> list[Path]:
    seen: set[Path] = set()
    out: list[Path] = []
    for root in _ROOTS:
        p = Path(os.path.expanduser(root))
        if not p.exists():
            continue
        for f in p.rglob("package.json"):
            rp = f.resolve()
            if rp in seen:
                continue
            seen.add(rp)
            out.append(f)
    return out


def _run(_ctx: dict) -> Verdict:
    manifests = _iter_manifests()
    scanned = len(manifests)
    hits: list[str] = []
    for m in manifests:
        try:
            head = m.read_bytes()[:3]
        except OSError:
            continue
        if head == b"\xef\xbb\xbf":
            hits.append(str(m))

    ev = {"scanned": scanned, "roots": _ROOTS, "hits": hits}

    if scanned == 0:
        return Verdict(
            "skip",
            "no plugin manifest roots present",
            detail=f"looked at: {', '.join(_ROOTS)}",
            evidence=ev,
        )
    if hits:
        return Verdict(
            "fail",
            f"{len(hits)}/{scanned} manifest(s) start with UTF-8 BOM → will crash `dsh plugin add` (2798)",
            detail="Fix: re-save files as UTF-8 without BOM. Upstream fix "
                   "should strip BOM before JSON.parse in dsh-app-boot.",
            evidence=ev,
        )
    return Verdict("pass", f"no BOM in {scanned} manifest(s)", evidence=ev)


PROBE = Probe(
    id="P2-bom",
    title="plugin manifests carry no UTF-8 BOM (#2798)",
    run=_run,
)
