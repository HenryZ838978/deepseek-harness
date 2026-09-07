"""P11 — the default-on `dsh_plugin_packages` request field fails every model
request when an active plugin's nearest manifest has a `name` but no
`version` — and the manifest dsh generates for its own profiles is exactly
that shape.

Discovery: 0.1.2-rc.1 (2026-09-03, tag a66e4702). The contributor itself
landed in 0.1.1-rc.2 (`.agents/notes/implemented/architecture/
2026-08-21-deepseek-llm-api-request-extensions.md`); rc.1 is the first
release that promoted it to `latest`. Verified on both the source tag and
the published `@deepseek-ai/dsh-plugin-package-inventory-deepseek@0.1.2-rc.1`
artifact.

The chain, each link a grep:

  1. Mounted and on by default.
     `packages/bundle/base/cordis.patch.yml:70-71` mounts
     `@deepseek-ai/dsh-plugin-package-inventory-deepseek` (sdk-minimal:23-24
     likewise). `plugin-package-inventory-deepseek/src/index.ts:38`
     `enabled: z.boolean().default(true)`; `:187` only an explicit
     `enabled === false` skips registration. The package README: "every
     official DeepSeek request carries the package inventory when
     preparation succeeds."

  2. Preparation fails hard on a name-without-version manifest.
     `src/index.ts:61-69` `identityFromManifest`:
       `JSON.parse(readFileSync(path, 'utf8'))`           ← no BOM strip (P2 family)
       `if (allowAnonymous && manifest.name === undefined) return undefined`
       `if (typeof manifest.name !== 'string' || ... || typeof manifest.version
        !== 'string' || manifest.version.length === 0) throw new Error(
        '... must declare non-empty name and version')`
     A manifest with no `name` is a "loose module" and is skipped. A manifest
     with a `name` and no `version` throws. The test at
     `tests/inventory.spec.ts:97-103` pins this: "fails request preparation for
     an active package with malformed identity metadata". Design, not
     accident.

  3. The throw is per request, forever.
     `:98-100` the identity cache is only written on success, so a failing
     manifest is re-read and re-thrown on every request.
     `llm-deepseek/src/adapter.ts:621-628` (inside `stream()`, `:440`) wraps
     any preparation failure as `LlmError('DeepSeek request extension
     preparation failed', 'REQUEST_EXTENSION')` — before `fetch`, so no
     HTTP request is made. Compiled: `dsh-llm-deepseek/lib/index.js:1746`.

  4. It lands after the user turn was committed.
     `core/agent-loop/src/agent.ts:292` appends `user/message`; `:364` calls
     `stream()`. Same half-turn shape as P8, new trigger.

  5. dsh's own profile manifest is the rejected shape.
     `boot/app-boot/src/profile.ts:205-210` `initProfile` writes
     `~/.dsh/profiles/<name>/package.json` as
       `{ name: 'dsh-profile-<name>', private: true, dependencies: {},
          dsh: { profile: {...} } }`
     — `name` present, `version` absent. Compiled:
     `dsh-app-boot/lib/index.js:384`.

  6. Relative plugin entries resolve against that directory.
     `apps/cli/src/profile-boot.ts:230` roots the tree at
     `<profile dir>/cordis.yml`; `boot/app-boot/src/index.ts:784` sets
     `ctx.baseUrl` to that directory. `src/index.ts:119-122` resolves a
     relative entry name against the tree base and walks up
     (`nearestManifest`, `:85-95`) to the first `package.json` — which, for
     any `./plugin.js` dropped in the profile directory or a subdirectory
     without its own manifest, is the file from step 5.

Net effect: add one line — `name: ./my-plugin.js` — to a profile's
`cordis.patch.yml`, and every `deepseek-official` request in that profile
fails with "DeepSeek request extension preparation failed" whose cause names
the profile's own package.json. Nothing in the error points at the
inventory plugin, and nothing in the profile was authored by the user except
the plugin line. The remedy dsh offers (`plugin-package-inventory-deepseek:
enabled: false`, or adding a `version` to a file dsh generated) is
discoverable only by reading the source.

This probe is offline. It reads each profile's `package.json` and
`cordis.patch.yml` (plus the home-level `$DSH_HOME/cordis.patch.yml`, which
patches the same tree), finds relative or absolute module entries, resolves
each to its nearest manifest, and reports the ones the inventory would reject.
It also reports whether the profile manifests themselves carry the
rejected shape — that is the loaded gun even when no relative entry has
pulled the trigger yet. YAML is scanned line-wise (the CLI carries no YAML
dependency); an entry disabled by an `enabled: false` line within the same
block is still counted, because the Loader-state filter runs on fiber state
the probe cannot observe offline.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from . import Probe, Verdict


_INVENTORY_ID = "plugin-package-inventory-deepseek"
_PATCH = "cordis.patch.yml"

# `name: ./x.js`, `name: '../x.mjs'`, `name: "/abs/x.js"` — the entry shapes
# `barePackageName()` returns undefined for and `nearestManifest()` then walks.
_MODULE_ENTRY = re.compile(
    r"""^\s*-?\s*name:\s*['"]?((?:\.\.?/|/)[^'"\s#]+)['"]?\s*(?:#.*)?$"""
)
_DISABLE_LINE = re.compile(
    rf"""^\s*-?\s*id:\s*['"]?{re.escape(_INVENTORY_ID)}['"]?\s*$"""
)
_ENABLED_FALSE = re.compile(r"""^\s*enabled:\s*false\s*$""")


def _dsh_home(env: dict) -> Path:
    raw = env.get("DSH_HOME", "").strip() or "~/.dsh"
    return Path(os.path.expanduser(raw))


def _manifest_shape(path: Path) -> str:
    """'rejected' = name without version (the throw); 'loose' = no name
    (skipped); 'ok' = name and version; 'bom' = starts with U+FEFF (JSON.parse
    throws before the shape is even looked at); 'unreadable' otherwise."""
    try:
        raw = path.read_bytes()
    except OSError:
        return "unreadable"
    if raw[:3] == b"\xef\xbb\xbf":
        return "bom"
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return "unreadable"
    if not isinstance(doc, dict):
        return "unreadable"
    name, version = doc.get("name"), doc.get("version")
    if name is None:
        return "loose"
    if isinstance(name, str) and name and isinstance(version, str) and version:
        return "ok"
    return "rejected"


def _nearest_manifest(start: Path) -> Path | None:
    cur = start if start.is_dir() else start.parent
    while True:
        cand = cur / "package.json"
        if cand.exists():
            return cand
        if cur.parent == cur:
            return None
        cur = cur.parent


def _module_entries(patch: Path) -> list[str]:
    try:
        lines = patch.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    return [m.group(1) for line in lines if (m := _MODULE_ENTRY.match(line))]


def _inventory_disabled(patch: Path) -> bool:
    """True if the patch carries an `id: plugin-package-inventory-deepseek`
    block followed (within the block) by `enabled: false`."""
    try:
        lines = patch.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return False
    in_block = False
    for line in lines:
        if _DISABLE_LINE.match(line):
            in_block = True
            continue
        if in_block:
            if _ENABLED_FALSE.match(line):
                return True
            if re.match(r"^\s*-\s*id:", line):
                in_block = False
    return False


def _run(ctx: dict) -> Verdict:
    home = _dsh_home(ctx.get("env", {}))
    profiles_dir = home / "profiles"
    ev: dict = {
        "dsh_home": str(home),
        "profiles": [],
        "rejected_entries": [],
        "inventory_disabled_in": [],
        "upstream_ref": {
            "throw": "plugin-package-inventory-deepseek/src/index.ts:66 (rc.1); "
                     "lib/index.js:34 in the npm artifact",
            "default_on": "src/index.ts:38 `enabled: z.boolean().default(true)`; "
                          "bundle/base/cordis.patch.yml:70-71",
            "request_failure": "llm-deepseek/src/adapter.ts:628 REQUEST_EXTENSION, "
                               "pre-fetch; lib/index.js:1746",
            "after_user_append": "core/agent-loop/src/agent.ts:292 append → :364 stream()",
            "generated_manifest": "boot/app-boot/src/profile.ts:205-210 — "
                                  "name without version; lib/index.js:384",
        },
    }

    if not profiles_dir.is_dir():
        return Verdict(
            "skip",
            "no dsh profiles directory",
            detail=f"looked at: {profiles_dir}. Nothing for the inventory to read.",
            evidence=ev,
        )

    home_patch = home / _PATCH
    home_entries = _module_entries(home_patch) if home_patch.exists() else []
    home_disabled = home_patch.exists() and _inventory_disabled(home_patch)
    if home_disabled:
        ev["inventory_disabled_in"].append(str(home_patch))

    rejected_shape_profiles: list[str] = []
    for pdir in sorted(p for p in profiles_dir.iterdir() if p.is_dir()):
        if pdir.name == "node_modules":
            continue
        manifest = pdir / "package.json"
        shape = _manifest_shape(manifest) if manifest.exists() else "absent"
        patch = pdir / _PATCH
        entries = (_module_entries(patch) if patch.exists() else []) + home_entries
        profile_disabled = patch.exists() and _inventory_disabled(patch)
        if profile_disabled:
            ev["inventory_disabled_in"].append(str(patch))
        disabled = home_disabled or profile_disabled
        rec = {
            "profile": pdir.name,
            "manifest_shape": shape,
            "module_entries": entries,
            "inventory_disabled": disabled,
        }
        ev["profiles"].append(rec)
        if shape == "rejected":
            rejected_shape_profiles.append(pdir.name)
        if disabled:
            continue
        for entry in entries:
            near = _nearest_manifest((pdir / entry).resolve())
            near_shape = _manifest_shape(near) if near else "loose"
            if near_shape in ("rejected", "bom"):
                ev["rejected_entries"].append({
                    "profile": pdir.name,
                    "entry": entry,
                    "nearest_manifest": str(near),
                    "shape": near_shape,
                })

    if not ev["profiles"]:
        return Verdict(
            "skip",
            "profiles directory is empty",
            detail=f"{profiles_dir} has no profile subdirectories.",
            evidence=ev,
        )

    if ev["rejected_entries"]:
        n = len(ev["rejected_entries"])
        first = ev["rejected_entries"][0]
        return Verdict(
            "fail",
            f"{n} plugin entr{'y resolves' if n == 1 else 'ies resolve'} to a "
            f"manifest the request inventory rejects → every DeepSeek request in profile "
            f"'{first['profile']}' fails before HTTP",
            detail=f"`{first['entry']}` walks up to `{first['nearest_manifest']}` "
                   f"({first['shape']}). plugin-package-inventory-deepseek re-reads "
                   "it on every request and throws; llm-deepseek wraps that as "
                   "REQUEST_EXTENSION before fetch, after the user turn was already "
                   "appended. Fix: add a `\"version\"` to that package.json, give "
                   "the plugin its own versioned package.json, or set "
                   "`plugin-package-inventory-deepseek: { enabled: false }` in "
                   "cordis.patch.yml. Upstream: the manifest is the one dsh "
                   "generated (boot/app-boot/src/profile.ts:205-210).",
            evidence=ev,
        )

    if rejected_shape_profiles and not all(p["inventory_disabled"] for p in ev["profiles"]):
        return Verdict(
            "warn",
            f"{len(rejected_shape_profiles)} profile manifest(s) have the shape the "
            "request inventory rejects; no relative plugin entry currently "
            "reaches them",
            detail="dsh wrote `name` without `version` into "
                   f"{', '.join(rejected_shape_profiles)}/package.json. The "
                   "inventory contributor (on by default) throws on exactly that "
                   "shape when a plugin resolves to it. One `name: ./plugin.js` "
                   "line in cordis.patch.yml — the ordinary way to try a local "
                   "plugin — turns this into every request failing. Pre-empt it by "
                   "giving local plugins their own versioned package.json, or "
                   "adding a version line to the profile manifest.",
            evidence=ev,
        )

    if ev["inventory_disabled_in"]:
        return Verdict(
            "pass",
            "request inventory disabled by patch; manifest shape irrelevant",
            evidence=ev,
        )
    return Verdict(
        "pass",
        f"{len(ev['profiles'])} profile(s); manifests carry name+version, "
        "no rejected entries",
        evidence=ev,
    )


PROBE = Probe(
    id="P11-plugin-inventory-manifest",
    title="default-on request inventory rejects dsh's own profile manifest "
          "(0.1.2-rc.1)",
    run=_run,
)
