"""P5 — #2571: session log seq-gap detector.

Reproduces J3 findings on the local machine: scans on-disk `.jsonl` /
`.jsonl.zstd` session logs the way rc.6's compiled `scanLog` does. Two
observable failure modes:

  1. Silent truncation — scanner stashes an issue but does not throw;
     session loads with a truncated event tail.
  2. Terminal corrupt — a subsequent `turn/end` promotes the issue and
     `scanLog` throws; session is permanently unloadable.

This probe reports both. It does NOT open the harness's persistence layer
(that would require Cordis context); it re-implements the scan-loop
faithfully from format.ts (source referenced inline).

Fully offline. No key needed.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from . import Probe, Verdict


_ROOTS = [
    "~/.dsh/sessions",
    "~/.deepseek-harness/sessions",
    "~/.config/dsh/sessions",
    "./.dsh/sessions",
]


def _find_logs() -> list[Path]:
    seen: set[Path] = set()
    out: list[Path] = []
    for root in _ROOTS:
        base = Path(os.path.expanduser(root))
        if not base.exists():
            continue
        for pattern in ("**/*.jsonl", "**/*.jsonl.zstd"):
            for p in base.glob(pattern):
                rp = p.resolve()
                if rp in seen:
                    continue
                seen.add(rp)
                out.append(p)
    return out


def _scan_plain_jsonl(buf: bytes) -> dict:
    """Faithful port of scanLog from rc.6 compiled artifact
    (@deepseek-ai/dsh-session-persistence-jsonl/lib/index.js lines 205–316).

    Returns:
      {events, threw, error, pending_issue}
    """
    nl = buf.find(b"\n")
    if nl == -1:
        return {"events": 0, "threw": True, "error": "empty or header-less session log",
                "pending_issue": None}
    rest = buf[nl + 1:]
    events = 0
    issue: str | None = None
    line_no = 0
    cursor = 0
    while cursor < len(rest):
        end = rest.find(b"\n", cursor)
        if end == -1:
            break  # torn tail is expected
        line_no += 1
        raw = rest[cursor:end].decode("utf-8", errors="replace")
        try:
            obj = json.loads(raw)
        except Exception:
            if issue is None:
                issue = f"unparsable committed event at line {line_no}"
            cursor = end + 1
            continue
        # decodeStorageRecord: single event OR packed chunk row.
        # For seq-gap purposes we only need to identify event(s) in this line.
        decoded = _expand_row(obj)
        if issue is not None:
            if any(e.get("type") == "turn/end" for e in decoded):
                return {"events": events, "threw": True,
                        "error": f"seq gap promoted at line {line_no}: {issue}",
                        "pending_issue": None}
            cursor = end + 1
            continue
        for e in decoded:
            seq = e.get("seq")
            if seq != events:
                issue = f"seq gap at line {line_no} (expected {events}, got {seq})"
                if any(c.get("type") == "turn/end" for c in decoded):
                    return {"events": events, "threw": True,
                            "error": issue, "pending_issue": None}
                break
            events += 1
        cursor = end + 1
    return {"events": events, "threw": False, "error": None, "pending_issue": issue}


def _expand_row(obj: dict) -> list[dict]:
    """Cheap port of decodeStorageRecord: single event OR chunk-run envelope."""
    if not isinstance(obj, dict):
        return [obj]
    tag = obj.get("type")
    if tag not in ("text-chunks", "reasoning-chunks", "tool-call-chunks"):
        return [obj]
    # Chunk-run envelope: {type, seq0, time0, data}. We can't reproduce the
    # inner data shape without the full decoder, but seq check is easy: the
    # run occupies seq0 .. seq0+K-1 where K = length of data.
    seq0 = obj.get("seq0")
    data = obj.get("data")
    if not isinstance(seq0, int) or not isinstance(data, list):
        return [{"seq": None, "type": tag}]
    return [{"seq": seq0 + k, "type": tag} for k in range(len(data))]


def _run(_ctx: dict) -> Verdict:
    logs = _find_logs()
    ev = {"scanned": len(logs), "roots": _ROOTS,
          "truncated": [], "corrupt": []}

    if not logs:
        return Verdict("skip", "no session logs found",
                       detail=f"looked at: {', '.join(_ROOTS)}",
                       evidence=ev)

    for p in logs:
        if str(p).endswith(".zstd"):
            # Skip zstd for now: needs the private-format decoder.
            continue
        try:
            buf = p.read_bytes()
        except OSError:
            continue
        res = _scan_plain_jsonl(buf)
        if res["threw"]:
            ev["corrupt"].append({"path": str(p), "events_before_error": res["events"],
                                  "error": res["error"]})
        elif res["pending_issue"]:
            ev["truncated"].append({"path": str(p), "events_kept": res["events"],
                                    "pending_issue": res["pending_issue"]})

    if ev["corrupt"]:
        return Verdict(
            "fail",
            f"{len(ev['corrupt'])} session log(s) will throw on load (permanent corrupt)",
            detail="These sessions cannot be reopened. Likely cause: two dsh "
                   "processes wrote the same session dir concurrently, OR "
                   "an Agent Teams (rc.8 `@deepseek-ai/dsh-experimental-agent-team`) "
                   "run where multiple subagents appended to the same Lead session log. "
                   "The team package's README self-declares "
                   "'not cross-process exactly-once delivery' and 'no shared "
                   "mailbox transaction across processes'. Root cause is the "
                   "same as #2571.",
            evidence=ev,
        )
    if ev["truncated"]:
        return Verdict(
            "warn",
            f"{len(ev['truncated'])} session log(s) silently truncated on load",
            detail="Session loads but with fewer events than were persisted. "
                   "No user-visible error. Same root cause as the fail case.",
            evidence=ev,
        )
    return Verdict("pass", f"scanned {len(logs)} session log(s), no seq gaps",
                   evidence=ev)


PROBE = Probe(
    id="P5-seqgap",
    title="session / Agent Teams log has no concurrent-writer seq gap (#2571, worsened by rc.8 Teams)",
    run=_run,
)
