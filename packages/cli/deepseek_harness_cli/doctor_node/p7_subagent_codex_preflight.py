"""P7 — subagent-codex CLI preflight.

Discovery: rc.8 adds `feat(subagent): make Codex provider directly
installable`. In `@deepseek-ai/dsh-subagent-codex/src/run.ts:44-45`:

    const codexPackageJsonPath = createRequire(...).resolve('@openai/codex/package.json')
    const codexPackageManifest = JSON.parse(readFileSync(codexPackageJsonPath, 'utf8'))

Both calls are at module top-level. No try/catch. If a Profile references
the Codex subagent provider without `@openai/codex` installed, plugin load
crashes with `ERR_MODULE_NOT_FOUND` — the entire dsh boot fails rather
than the Codex row alone failing.

This probe scans reachable node_modules for `@openai/codex/package.json`.
It cannot know which Profiles the user has enabled; instead, if the
subagent-codex plugin is present, absence of Codex is flagged.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from . import Probe, Verdict


def _candidate_roots() -> list[Path]:
    seen: set[Path] = set()
    out: list[Path] = []
    for root in (
        "./node_modules",
        "~/.dsh/node_modules",
        "~/.dsh/profiles/web/node_modules",
        "~/.deepseek-harness/node_modules",
        "~/.config/dsh/node_modules",
        # global npm root; querying `npm root -g` would be nicer but avoid
        # invoking npm from a doctor probe.
        "/usr/local/lib/node_modules",
        "/opt/homebrew/lib/node_modules",
    ):
        p = Path(os.path.expanduser(root))
        rp = p.resolve() if p.exists() else p
        if rp in seen:
            continue
        seen.add(rp)
        out.append(p)
    return out


def _find_pkg(roots: list[Path], name: str) -> Path | None:
    for root in roots:
        candidate = root / name / "package.json"
        if candidate.exists():
            return candidate
        # scoped names live one level deeper
        if "/" in name:
            scope, sub = name.split("/", 1)
            candidate = root / scope / sub / "package.json"
            if candidate.exists():
                return candidate
    return None


def _run(_ctx: dict) -> Verdict:
    roots = _candidate_roots()
    codex_pkg = _find_pkg(roots, "@openai/codex")
    subagent_codex_pkg = _find_pkg(roots, "@deepseek-ai/dsh-subagent-codex")

    ev = {
        "roots_scanned": [str(r) for r in roots],
        "openai_codex_present": codex_pkg is not None,
        "openai_codex_path": str(codex_pkg) if codex_pkg else None,
        "subagent_codex_present": subagent_codex_pkg is not None,
    }

    if subagent_codex_pkg is None:
        return Verdict(
            "skip",
            "@deepseek-ai/dsh-subagent-codex not installed; nothing to preflight",
            evidence=ev,
        )
    if codex_pkg is None:
        return Verdict(
            "fail",
            "@deepseek-ai/dsh-subagent-codex is installed but @openai/codex is not — Profile load will crash",
            detail="subagent-codex/src/run.ts:44 calls "
                   "`createRequire(...).resolve('@openai/codex/package.json')` "
                   "+ readFileSync at module top-level with no try/catch. "
                   "A Profile that references the Codex provider without "
                   "@openai/codex installed will throw ERR_MODULE_NOT_FOUND "
                   "at plugin load and take down the entire dsh boot. "
                   "Install with: npm i -g @openai/codex (or add it to your "
                   "dsh profile's package.json).",
            evidence=ev,
        )

    # Sanity: manifest parseable and has bin.codex
    try:
        manifest = json.loads(codex_pkg.read_text())
        bin_codex = (manifest.get("bin") or {}).get("codex")
        if not bin_codex:
            return Verdict(
                "warn",
                "@openai/codex present but manifest has no bin.codex — subagent-codex will not resolve",
                evidence={**ev, "bin_present": False, "manifest_keys": list(manifest.keys())},
            )
    except Exception as e:
        return Verdict(
            "warn",
            f"@openai/codex manifest unparseable: {type(e).__name__}",
            evidence=ev,
        )

    return Verdict(
        "pass",
        "@openai/codex present and manifest carries bin.codex",
        evidence=ev,
    )


PROBE = Probe(
    id="P7-subagent-codex-preflight",
    title="subagent-codex plugin load will not crash on missing @openai/codex",
    run=_run,
)
