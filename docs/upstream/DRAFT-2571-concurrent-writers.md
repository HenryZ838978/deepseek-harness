# DRAFT — #2571: session log seq-gap is dual-mode; concurrent writers hit both

**Status:** draft. Send privately first, publish after 5 business days if no reply.
**Repo:** `@deepseek-ai/dsh-session-persistence-jsonl`
**Version:** rc.6 (`0.1.0-rc.6`, compiled artifact).
**Reporter's issue:** #2571 identified the terminal case; this note adds the
silent-truncation case and the missing lock discipline that lets both happen.

## TL;DR

`scanLog` has two failure modes for a seq gap in the committed region:

1. **Silent truncation.** If the corrupt row is not followed by any
   `turn/end`, the scanner stashes the issue and stops accumulating events
   at the gap. The session loads with fewer events than were persisted.
   No user-visible error.
2. **Terminal corrupt.** Once any subsequent line contains a `turn/end`,
   `scanLog` throws
   `corrupt session log: seq gap in committed region at line N (expected X, got Y)`.
   The session is permanently unloadable — history is gone.

Both are reachable from the same underlying pattern (duplicate or regressed
seq). Two concurrent writers who each complete a normal turn will hit the
terminal mode with probability 1 as soon as one of them appends `turn/end`.

## Repro

Fully offline; no key needed; ~2s CPU. The scanner is pure — feeding it
byte-level fixtures IS the workload two concurrent writers produce.

See attached `scan_probe.json` for the full trial matrix. Selected lines:

| pattern (seq sequence)       | scanLog outcome                                           |
|------------------------------|-----------------------------------------------------------|
| `0, 1, 2` (healthy)          | ok, 3 events                                              |
| `0, 1, 1`                    | ok, 2 events, **pending issue "seq gap at line 3"**       |
| `0, 1, 1, 2`                 | ok, 2 events, pending issue (subsequent `text/append` doesn't promote) |
| `0, 1, 0, 1`                 | ok, 2 events, pending issue                               |
| `0, 1, 1, turn/end@2`        | **THROWS**                                                |
| `0, 1, end@1`                | **THROWS**                                                |
| `0, 1, 0, end@1`             | **THROWS** — the concurrent-writer pattern with a normal turn end |

Faithful port of the scan loop from
`packages/session/session-persistence-jsonl/src/format.ts` (as compiled in
rc.6 to `dsh-session-persistence-jsonl/lib/index.js:205–316`).

## Why the persistence layer doesn't catch this

The publish path uses `link()+unlink()` (`session-persistence-jsonl/src/index.ts:544–546`)
which prevents *overwriting* an already-published artifact. It does not
prevent two processes from both `open()`-ing the log for append.

`PersistenceCoordinator.state.owner` (`session-persistence/src/coordinator.ts:940`)
is an **in-process** guard. Two Node processes each see their own
coordinator with `owner === undefined` and each attaches.

`grep -rE 'flock|O_EXCL|lockf|proper-lockfile'` across `packages/session/**`
returns **zero** hits. In-process invariants are being treated as system
invariants; they are not the same thing.

## Suggested fix

Take an `flock(LOCK_EX | LOCK_NB)` on the log fd inside
`session-persistence-jsonl` when opening for append. Release on close.
If the lock is unavailable, either wait (short backoff) or refuse to open
with a diagnostic — either beats silent truncation and permanent corruption.

Alternatively: a pid/lock file in the session dir written on attach and
verified on subsequent attaches. Slightly weaker (survives crashes badly)
but avoids the flock/NFS caveats.

The scan-loop itself is fine — it correctly refuses to load a corrupt log.
The fix belongs at the writer, not the reader.

## Impact for a real user

- Two dsh windows / two IDE extensions / one script + one interactive shell,
  all pointed at the same workspace → will eventually persist a duplicate
  seq → next load throws.
- Users who "resumed" a session and don't understand why one turn is missing
  are seeing mode #1 (silent truncation) — mode #1 is arguably worse
  because it looks like success.

## Reproducer files

Under `overnight/j3/` in the reporter's workspace:
- `scan_probe.json` — the trial matrix results
- `notes.md` — this note's long form + reasoning trail

## Downstream: our doctor

We added `P5-seqgap` to `dsh doctor --node` (Python-side witness stack,
`deepseek-harness-cli>=0.3.0`), which walks user session dirs and reports
both failure modes.

---

*Filed by the author of `deepseek-harness` on PyPI (2026-05-11, 0.2.0).
Related public discussion: #2571. This note is factual; recommendation
above is a suggestion, not a demand.*
