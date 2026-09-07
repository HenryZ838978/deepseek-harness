"""P11 verdicts against a synthetic DSH_HOME shaped like `initProfile` output."""
from __future__ import annotations

import json
from pathlib import Path

from deepseek_harness_cli.doctor_node.p11_plugin_inventory_manifest import PROBE


def _profile(home: Path, name: str, patch: str = "[]\n") -> Path:
    pdir = home / "profiles" / name
    pdir.mkdir(parents=True)
    # boot/app-boot/src/profile.ts:205-210 — name, no version.
    (pdir / "package.json").write_text(json.dumps({
        "name": f"dsh-profile-{name}",
        "private": True,
        "dependencies": {},
        "dsh": {"profile": {"bundles": ["@deepseek-ai/dsh-base"]}},
    }, indent=2) + "\n")
    (pdir / "cordis.patch.yml").write_text(patch)
    return pdir


def _run(home: Path):
    return PROBE.run({"env": {"DSH_HOME": str(home)}})


def test_skip_without_profiles(tmp_path: Path) -> None:
    assert _run(tmp_path / "nope").state == "skip"


def test_generated_manifest_alone_warns(tmp_path: Path) -> None:
    _profile(tmp_path, "default")
    v = _run(tmp_path)
    assert v.state == "warn"
    assert v.evidence["profiles"][0]["manifest_shape"] == "rejected"
    assert v.evidence["rejected_entries"] == []


def test_relative_entry_under_profile_fails(tmp_path: Path) -> None:
    _profile(tmp_path, "default", "- insert:\n    - name: './my-plugin.js'\n")
    v = _run(tmp_path)
    assert v.state == "fail"
    [hit] = v.evidence["rejected_entries"]
    assert hit["entry"] == "./my-plugin.js"
    assert hit["nearest_manifest"].endswith("profiles/default/package.json")
    assert hit["shape"] == "rejected"


def test_plugin_with_own_versioned_manifest_is_fine(tmp_path: Path) -> None:
    pdir = _profile(tmp_path, "vendored", "- insert:\n    - name: ./plugins/good/index.js\n")
    good = pdir / "plugins" / "good"
    good.mkdir(parents=True)
    (good / "package.json").write_text('{"name":"good","version":"1.0.0"}\n')
    v = _run(tmp_path)
    assert v.state == "warn"  # profile manifest still rejected-shape, entry is safe
    assert v.evidence["rejected_entries"] == []


def test_bom_manifest_on_entry_path_fails(tmp_path: Path) -> None:
    pdir = _profile(tmp_path, "bom", "- insert:\n    - name: ./plugins/x/index.js\n")
    x = pdir / "plugins" / "x"
    x.mkdir(parents=True)
    (x / "package.json").write_bytes(b"\xef\xbb\xbf" + b'{"name":"x","version":"1.0.0"}\n')
    v = _run(tmp_path)
    assert v.state == "fail"
    assert v.evidence["rejected_entries"][0]["shape"] == "bom"


def test_home_patch_disabling_inventory_passes(tmp_path: Path) -> None:
    _profile(tmp_path, "default", "- insert:\n    - name: ./my-plugin.js\n")
    (tmp_path / "cordis.patch.yml").write_text(
        "- id: plugin-package-inventory-deepseek\n  enabled: false\n"
    )
    v = _run(tmp_path)
    assert v.state == "pass"
    assert v.evidence["inventory_disabled_in"] == [str(tmp_path / "cordis.patch.yml")]
