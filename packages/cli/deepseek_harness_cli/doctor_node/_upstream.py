"""Which official harness generation is installed here.

Probes whose defect was fixed upstream keep running (an old harness still has
the bug), but must not report the bug against a harness that already carries
the fix. This module answers "what version is installed" and "is it at least
the fixing release", using the dsh release-tag ordering:

    0.2.1-alpha.2 < 0.2.1-rc.1 < 0.2.1   (alpha < rc < final, numeric suffix)

Detection order: `DSH_VERSION` env override (tests, CI), then the
`@deepseek-ai/dsh` package.json behind any `dsh` on PATH. There is no
`dsh --version` fallback on purpose: this package's own Python entry point is
also called `dsh`, and its version (0.x of deepseek-harness-cli) would
compare as "newer than every fix".
Returns None when no official harness is found; callers then fall back to
their pre-fix behaviour and say so.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

_PRE = {"alpha": 0, "beta": 1, "rc": 2}
_VERSION_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)(?:-(alpha|beta|rc)\.(\d+))?")


def parse(version: str) -> tuple[int, int, int, int, int] | None:
    m = _VERSION_RE.search(version or "")
    if not m:
        return None
    major, minor, patch, pre, num = m.groups()
    # A final release sorts after every prerelease of the same triple.
    rank = _PRE[pre] if pre else 9
    return int(major), int(minor), int(patch), rank, int(num or 0)


def at_least(installed: str | None, fixed_in: str) -> bool | None:
    a, b = parse(installed or ""), parse(fixed_in)
    if a is None or b is None:
        return None
    return a >= b


def installed_version(env: dict | None = None) -> str | None:
    env = env if env is not None else dict(os.environ)
    if env.get("DSH_VERSION"):
        return env["DSH_VERSION"]
    path = env.get("PATH") or os.environ.get("PATH", "")
    for d in path.split(os.pathsep):
        exe = Path(d) / "dsh"
        if not exe.exists():
            continue
        for parent in exe.resolve().parents:
            manifest = parent / "package.json"
            if not manifest.is_file():
                continue
            try:
                doc = json.loads(manifest.read_text("utf-8-sig"))
            except (OSError, ValueError):
                break
            if doc.get("name") == "@deepseek-ai/dsh" and isinstance(doc.get("version"), str):
                return doc["version"]
            break
    return None
