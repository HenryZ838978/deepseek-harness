"""P5 / P10 on dsh's v4 compressed logs: concatenated zstd frames, header
frame first. Fixture shape copied from a live 0.2.2-rc.5 headless session
(2026-11-25, zw10g0579); seeded dup/gap verdicts were cross-checked against
upstream `dsh headless --session-id` refusing the same files."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from deepseek_harness_cli.doctor_node import _zstd
from deepseek_harness_cli.doctor_node.p5_seqgap import PROBE as P5
from deepseek_harness_cli.doctor_node.p10_jsonl_repair_unguarded import PROBE as P10

zstandard = pytest.importorskip("zstandard")


def _lines(seqs: list[int]) -> list[bytes]:
    head = {"type": "session", "version": 4, "id": "session-t", "createdAt": 1, "cwd": "/w"}
    out = [json.dumps(head).encode() + b"\n"]
    types = ["permission/preset", "sandbox/mode", "approval/policy", "turn/start"]
    for i, s in enumerate(seqs):
        out.append(json.dumps({"type": types[i % len(types)], "seq": s, "time": 1, "data": {}}).encode() + b"\n")
    out.append(json.dumps({"type": "turn/end", "seq": seqs[-1] + 1, "time": 2, "data": {}}).encode() + b"\n")
    return out


def _write(home: Path, lines: list[bytes], torn: bool = False) -> Path:
    d = home / ".dsh/sessions/--w--/session-t"
    d.mkdir(parents=True)
    c = zstandard.ZstdCompressor(write_checksum=True)
    blob = c.compress(lines[0]) + c.compress(b"".join(lines[1:]))
    if torn:
        blob += c.compress(b'{"type":"x","seq":99}\n')[:-6]
    f = d / "session.v4.jsonl.zstd"
    f.write_bytes(blob)
    return f


def _run(probe, home: Path, monkeypatch):
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(home)
    return probe.run({"env": {}})


def test_clean_v4_log_passes(tmp_path: Path, monkeypatch) -> None:
    _write(tmp_path, _lines([0, 1, 2, 3]))
    v = _run(P5, tmp_path, monkeypatch)
    assert v.state == "pass" and v.evidence["zstd_decoded"] == 1


@pytest.mark.parametrize("seqs", [[0, 1, 1, 2], [0, 1, 3, 4]], ids=["dup", "gap"])
def test_seeded_seq_defect_in_zstd_log_fails(tmp_path: Path, monkeypatch, seqs) -> None:
    _write(tmp_path, _lines(seqs))
    v = _run(P5, tmp_path, monkeypatch)
    assert v.state == "fail"
    assert "seq gap" in v.evidence["corrupt"][0]["error"]


def test_torn_final_frame_is_reported_by_p10_and_ignored_by_p5(tmp_path: Path, monkeypatch) -> None:
    f = _write(tmp_path, _lines([0, 1, 2]), torn=True)
    dec = _zstd.decode(f.read_bytes())
    assert dec.torn and dec.data is not None
    assert _run(P5, tmp_path, monkeypatch).state == "pass"
    v = _run(P10, tmp_path, monkeypatch)
    assert v.evidence["torn"] and v.evidence["zstd_skipped"] == 0
