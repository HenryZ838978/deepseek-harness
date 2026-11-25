"""Generation detection used by probes whose defect was fixed upstream."""
from __future__ import annotations

import json
from pathlib import Path

from deepseek_harness_cli.doctor_node import _upstream
from deepseek_harness_cli.doctor_node.p4_spill_dir import PROBE as P4


def test_prerelease_ordering() -> None:
    assert _upstream.at_least("0.2.1-alpha.2", "0.2.1-alpha.2")
    assert _upstream.at_least("0.2.1-rc.1", "0.2.1-alpha.9")
    assert _upstream.at_least("0.2.1", "0.2.1-rc.5")
    assert not _upstream.at_least("0.1.7-alpha.1", "0.1.7-alpha.2")
    assert _upstream.at_least(None, "0.1.0") is None


def test_detects_only_the_node_package(tmp_path: Path) -> None:
    node = tmp_path / "lib/node_modules/@deepseek-ai/dsh"
    (node / "bin").mkdir(parents=True)
    (node / "package.json").write_text(json.dumps({"name": "@deepseek-ai/dsh", "version": "0.2.2-rc.5"}))
    (node / "bin/dsh").write_text("#!/bin/sh\n")
    py_bin = tmp_path / "pybin"
    py_bin.mkdir()
    (py_bin / "dsh").write_text("#!/bin/sh\necho 9.9.9\n")  # our own Python CLI
    node_bin = tmp_path / "bin"
    node_bin.mkdir()
    (node_bin / "dsh").symlink_to(node / "bin/dsh")
    env = {"PATH": f"{py_bin}:{node_bin}"}
    assert _upstream.installed_version(env) == "0.2.2-rc.5"
    assert _upstream.installed_version({"PATH": str(py_bin)}) is None


def test_p4_downgrades_unwritable_spill_on_fixed_harness(tmp_path: Path, monkeypatch) -> None:
    from deepseek_harness_cli.doctor_node import p4_spill_dir
    monkeypatch.setattr(p4_spill_dir, "_spill_candidates", lambda: [tmp_path / "missing"])
    assert P4.run({"env": {"DSH_VERSION": "0.1.7-alpha.1"}}).state == "fail"
    v = P4.run({"env": {"DSH_VERSION": "0.2.2-rc.5"}})
    assert v.state == "warn"
    assert v.evidence["fixed_in"] == "0.1.7-alpha.2"
