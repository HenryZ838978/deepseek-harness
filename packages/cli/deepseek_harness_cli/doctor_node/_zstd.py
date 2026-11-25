"""Decode dsh's compressed session logs (`session.v4.jsonl.zstd`).

Since the 0.1.7 line every session log dsh writes is compressed. The format is
not private: `session-persistence-jsonl/src/zstd.ts` writes a concatenation of
ordinary Zstandard frames (magic 0xFD2FB528, checksum flag on) through
`node:zlib`, one frame per appended batch, and treats an incomplete final frame
as the torn tail its repair path truncates. So any stock decoder reads it.

`decode()` tries the `zstandard` module, then the `zstd` CLI, and reports
which one it used. A torn final frame decodes to the complete prefix and sets
`torn=True` — the same split the upstream scanner makes.
"""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass

ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"


@dataclass
class Decoded:
    data: bytes | None
    torn: bool = False
    via: str = ""
    error: str = ""


def _via_module(buf: bytes) -> Decoded | None:
    try:
        import zstandard  # type: ignore[import-not-found]
    except ImportError:
        return None
    out = bytearray()
    view = memoryview(buf)
    pos = 0
    while pos < len(buf):
        if bytes(view[pos:pos + 4]) != ZSTD_MAGIC:
            return Decoded(bytes(out), torn=True, via="zstandard", error=f"no frame magic at byte {pos}")
        obj = zstandard.ZstdDecompressor().decompressobj()
        try:
            out += obj.decompress(bytes(view[pos:]))
        except zstandard.ZstdError as e:
            return Decoded(bytes(out), torn=True, via="zstandard", error=str(e))
        if not obj.eof:
            return Decoded(bytes(out), torn=True, via="zstandard", error="incomplete final frame")
        consumed = len(buf) - pos - len(obj.unused_data)
        pos += consumed
    return Decoded(bytes(out), via="zstandard")


def _via_cli(buf: bytes) -> Decoded | None:
    exe = shutil.which("zstd")
    if not exe:
        return None
    try:
        r = subprocess.run([exe, "-dc", "-q"], input=buf, capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as e:
        return Decoded(None, via="zstd-cli", error=repr(e))
    if r.returncode == 0:
        return Decoded(r.stdout, via="zstd-cli")
    # The CLI still emits every complete frame before failing on the torn one.
    return Decoded(r.stdout, torn=True, via="zstd-cli",
                   error=r.stderr.decode("utf-8", "replace").strip()[:200])


def decode(buf: bytes) -> Decoded:
    if not buf.startswith(ZSTD_MAGIC):
        return Decoded(None, error="not a zstd stream")
    for fn in (_via_module, _via_cli):
        res = fn(buf)
        if res is not None:
            return res
    return Decoded(None, error="no zstd decoder (pip install zstandard, or install the zstd CLI)")
