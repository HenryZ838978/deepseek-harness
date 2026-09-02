"""P9 — DeepSeek Files API upload-index cross-instance clobber.

Discovery: rc.2 (2026-08-21) adds Files API upload with quota reclaim.
Re-verified unchanged on 0.1.2-alpha.4 (2026-09-01, tag 4e84901e):
`file-store.ts:12` is still `const OWNED_FILE_PREFIX = 'dsh-'` — a fixed
string with no host, install, or user component — and `reclaimOldestOwned`
(`:288-313`) still selects purely on `file.filename.startsWith(
OWNED_FILE_PREFIX)` before deleting. "Owned" means owned by dsh the product,
not by this installation of it; that is the whole defect.
Path in `packages/llm/llm-deepseek/src/file-store.ts:reclaimOldestOwned`
walks the remote /files list, filters by `filename.startsWith('dsh-')`,
and deletes the oldest N. The scope key is
`deepSeekFileScope(baseURL, apiKey) = sha256(baseURL || '\\0' || apiKey)`.

Two failure modes:

  1. **Cross-instance clobber under one API key.** Two dsh installs that
     share the same DeepSeek key (team, CI runner, one dev with two
     machines) both write to different local `~/.dsh/llm-deepseek/
     files-v3.json` indices but hit the same remote /files quota. When
     A fills up, `reclaimOldestOwned` deletes files uploaded by B — B's
     local index still points at those file_ids, next chat request
     rejects with "unknown file_id", B's prefix cache misses.

  2. **`OWNED_FILE_PREFIX = 'dsh-'` is dsh-ecosystem-wide, not
     instance-scoped.** Any tool that uploads files starting with `dsh-`
     via the same API key competes for the same reclaim pool. There is
     no per-user or per-install tag inside the filename.

This probe reads the local upload-index and reports:
  - the scope hash (so the user can compare across machines)
  - the file count + total bytes tracked locally
  - whether the local file exists at all (absent = never used Files API)

It cannot reach the remote /files without an API call, but the local
state is enough to flag "you have local records that could be silently
invalidated if another machine reclaims quota on this key."

Offline. No key needed.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from . import Probe, Verdict


_INDEX_PATHS = [
    "~/.dsh/llm-deepseek/files-v3.json",
    "~/.deepseek-harness/llm-deepseek/files-v3.json",
    "~/.config/dsh/llm-deepseek/files-v3.json",
]


def _find_index() -> Path | None:
    for p in _INDEX_PATHS:
        f = Path(os.path.expanduser(p))
        if f.exists():
            return f
    return None


def _run(_ctx: dict) -> Verdict:
    idx = _find_index()
    ev = {"searched": _INDEX_PATHS}

    if idx is None:
        return Verdict(
            "skip",
            "no llm-deepseek upload index found",
            detail=f"looked at: {', '.join(_INDEX_PATHS)}. "
                   "If you've never sent an image to DeepSeek via dsh, this is expected.",
            evidence=ev,
        )

    ev["index_path"] = str(idx)
    try:
        text = idx.read_text()
        data = json.loads(text)
    except Exception as e:
        return Verdict(
            "warn",
            f"upload index unreadable: {type(e).__name__}",
            detail="File exists but does not parse. Old format? Deleted while "
                   "dsh held it open? Safe to `mv` it aside to force re-upload.",
            evidence=ev,
        )

    records = data.get("records") or data.get("index") or []
    if not isinstance(records, list):
        return Verdict("warn", "upload index schema unrecognized", evidence=ev)

    scopes = {}
    total_bytes = 0
    for r in records:
        if not isinstance(r, dict):
            continue
        scope = r.get("scope", "?")
        scopes.setdefault(scope, 0)
        scopes[scope] += 1
        b = r.get("bytes", 0)
        if isinstance(b, int):
            total_bytes += b

    ev["scope_count"] = len(scopes)
    ev["record_count"] = sum(scopes.values())
    ev["total_bytes"] = total_bytes
    ev["scopes"] = {s[:12] + "…": n for s, n in scopes.items()}  # truncate hash for display

    if not records:
        return Verdict(
            "pass",
            "upload index present but empty",
            evidence=ev,
        )

    return Verdict(
        "warn",
        f"{sum(scopes.values())} Files API record(s) across {len(scopes)} scope(s), {total_bytes // 1024} KiB tracked locally",
        detail="Each scope hash = SHA-256(baseURL || \\0 || apiKey). If any "
               "other dsh install (a teammate, another dev machine, a CI "
               "runner) shares the same API key, its `reclaimOldestOwned` "
               "call can delete file_ids referenced here — this instance "
               "will then hit 'unknown file_id' on the next image request, "
               "losing prefix cache. The `dsh-*` filename prefix is "
               "ecosystem-wide, not per-install. Mitigation: give each "
               "install its own API key, or accept the occasional "
               "re-upload as a design constraint.",
        evidence=ev,
    )


PROBE = Probe(
    id="P9-files-quota-scope",
    title="DeepSeek Files API upload-index is not cross-instance safe under one API key",
    run=_run,
)
