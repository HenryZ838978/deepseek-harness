# P5 seqgap scanner — session-persistence-jsonl replay, 2026-08-17

Raw evidence for the `P5-seqgap` doctor probe in `packages/cli/deepseek_harness_cli/doctor_node/p5_seqgap.py`. Corresponds to upstream Discussion [#2571](https://github.com/deepseek-ai/deepseek-harness/discussions/2571) — session log corruption from concurrent writers.

## Design

Faithful port of `scanLog` from the compiled artifact
`node_modules/@deepseek-ai/dsh-session-persistence-jsonl/lib/index.js:205–316`
(rc.6), fed hand-crafted JSONL fixtures that mimic the byte-level state two
concurrent writers would produce. `scanLog` is a pure function; feeding it
fixtures is equivalent to observing what happens after two processes append
to the same session log.

## Files

- `scan_probe.json` — trial matrix, 9 patterns × outcome (threw / event count / pending issue).
- `notes.md` — full narrative + code citations + suggested upstream fix (`flock(LOCK_EX | LOCK_NB)`).

## Headline findings

**Two failure modes, one root cause:**

| pattern                       | scanLog outcome                          |
|-------------------------------|------------------------------------------|
| `0,1,2` healthy               | ok, 3 events                             |
| `0,1,1` (no `turn/end`)       | **silent truncation** — 2 events, no error |
| `0,1,1, turn/end@2`           | **THROWS** `corrupt session log: seq gap` |
| `0,1,0,1, turn/end@1`         | **THROWS** — concurrent-writer pattern with normal turn end |

Two concurrent writers who each complete a normal turn hit the terminal
mode with probability 1 as soon as either appends `turn/end`. Root cause:
`link()+unlink()` prevents overwrites but not concurrent `open()` for
append; `PersistenceCoordinator.state.owner` is in-process only.
`grep -rE 'flock|O_EXCL|lockf' packages/session/` returns 0.

Full analysis: [`notes.md`](notes.md) or [`docs/upstream/DRAFT-2571-concurrent-writers.md`](../../../docs/upstream/DRAFT-2571-concurrent-writers.md).

## Reproduce

```bash
# Standalone: needs the rc.6 (or later) artifact locally.
node overnight/j3/j3_scan_probe.mjs
```

Preserved on the original probe host under `globaltest/j3_scan_probe.mjs`.
