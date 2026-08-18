# deepseek-harness-cli 0.3.0

**Installed the Node harness (`@deepseek-ai/dsh`) and things feel off?
Try first: `pip install deepseek-harness-cli`. 有奇效.**

```bash
pip install -U deepseek-harness-cli
export DEEPSEEK_API_KEY=sk-...
dsh doctor --node
```

Five witness probes for the official Node runtime. Each surfaces something
the Node stack does not — with the reason it happens and what to do.

---

### P1-reasoner-skip · thinking-mode history looks incomplete

**Why.** `deepseek-reasoner` sometimes skips its reasoning stream on prompts
it deems trivial. It's a model decision, not a wire bug. 200-trial overnight
sampling: bare short prompt → **60–100% silent**; same tool with a "reason
step by step" hint → **0% silent, every time**. `temp` doesn't matter;
prompt shape does.

**Fix.** The probe runs an A/B (bare vs. +CoT hint, N=5 each) and reports
the skip-rate delta. If Δ is large, your prompt is telling the model
"don't bother thinking" — add a hint, or accept reasoning-less turns as a
distinct state.

---

### P2-bom · `dsh plugin add` crashes on JSON.parse

**Why.** rc.6 `dsh-app-boot/lib/index.js:453` and `:548` call `JSON.parse`
directly on file bytes. A single UTF-8 BOM at file start crashes the whole
`plugin add`. `stripBOM` never appears in the compiled artifact.

**Fix.** Offline scan of your plugin manifest roots (`~/.dsh` and
friends). Re-save flagged files as UTF-8 without BOM. Upstream:
[#2798](https://github.com/deepseek-ai/deepseek-harness/discussions/2798).

---

### P3-serve · `dsh web` page hangs on "Select a workspace"

**Why.** The frontend loads (HTML+JS come back 200), then every data-layer
request under a non-loopback Origin gets 403. No console error. The fence
is doing its job correctly — but with no user-visible failure mode.

**Fix.** The probe sends the natural request vs. an evil-Origin request
against your running `dsh web` and reports the fence outcome. If you're
hitting the server from a hostname that isn't 127.0.0.1 / localhost / [::1],
switch. Upstream:
[#2573](https://github.com/deepseek-ai/deepseek-harness/discussions/2573).

---

### P4-spill · harness dies with `exit 1` mid-turn

**Why.** `dsh-subprocess-local/src/spawn.ts` (`spillAll()`) calls
`openSync` and `writeSync` on the spill file **with no try/catch**. Any IO
failure — EACCES on a hardened tmp dir, ENOSPC on a full disk, EPERM after
a container restart — escapes the stream `data` callback and kills the
whole harness. Sibling `discardSpill()` is guarded; this one isn't. The
asymmetry is the tell.

**Fix.** Offline writability probe against every tmp candidate dsh might
pick (`$TMPDIR`, `$TEMP`, `$TMP`, `/tmp`, `tempfile.gettempdir()`). If any
FAIL, either fix perms or point `TMPDIR` at a writable dir before starting
dsh.

---

### P5-seqgap · session won't load, or loads with silently fewer events

**Why.** Two `dsh` processes on the same workspace → both attach with
`state.owner === undefined` (the coordinator's owner check is
**in-process**, not cross-process) → both append to the same session log →
duplicate seq. `link()+unlink()` prevents overwrites of published
artifacts; it does not prevent this. `grep -rE 'flock|O_EXCL|lockf' packages/session/`
returns 0. **In-process invariants are being treated as system invariants.**

The scanner has two failure modes:

- **Silent truncation.** Gap without a subsequent `turn/end` → issue is
  stashed, events truncate at the gap, no error surfaces. User sees a
  session that just quietly lost a turn.
- **Terminal corrupt.** Any subsequent `turn/end` promotes the issue to a
  throw: `corrupt session log: seq gap in committed region at line N`.
  Session is **permanently unloadable**.

**Fix.** Offline scan of user session dirs. Reports both modes. Full
findings + suggested upstream fix (`flock(LOCK_EX|LOCK_NB)` on log fd) in
[docs/upstream/DRAFT-2571-concurrent-writers.md](https://github.com/HenryZ838978/deepseek-harness/blob/main/docs/upstream/DRAFT-2571-concurrent-writers.md).
Upstream:
[#2571](https://github.com/deepseek-ai/deepseek-harness/discussions/2571).

---

## Also in this release

- **`@deepseek-harness/dsh-doctor-plugin`** — Node-side shim
  ([packages/dsh-doctor-plugin](https://github.com/HenryZ838978/deepseek-harness/tree/main/packages/dsh-doctor-plugin)).
  A meta-plugin: since the Node runtime advertises "everything is a plugin",
  the doctor is one. `bin/dsh-doctor.mjs` spawns `python -m
  deepseek_harness_cli doctor --node`.
- **First-screen mermaid map** in the README: failure mode → symptom →
  doctor verdict. Three columns, five rows. Find your symptom in the middle,
  read across.
- **DEVLOG** ([docs/DEVLOG.md](https://github.com/HenryZ838978/deepseek-harness/blob/main/docs/DEVLOG.md))
  now records the reasoning trail behind every probe — including two
  reversals (#2802 static-hole after end-to-end validation; P1 from
  "wire silence" to "reasoner skip" after 200-trial sampling).

## Breaking change (dev-only)

Probe id renamed: `P1-reasoner-wire` → `P1-reasoner-skip`. No stable API
was ever documented under the old id, but if you scripted around it,
update the string.

## Not the same tool as

[`@simon-world/dsh-toolkit`](https://github.com/SIMON-WORLD/dsh-toolkit)
`doctor` (Node-side, checks Node version / koffi pin / ports / ASCII paths
/ sandbox) — complementary. Theirs: "will it install and start". Ours:
"what will silently bite you after it does".

## Provenance

- `deepseek-harness` on PyPI: 0.2.0 published 2026-05-11 (unchanged this release).
- `deepseek-harness-cli` on PyPI: 0.3.0 (this release).
- Related public discussion numbers cited above are from the official
  `deepseek-ai/deepseek-harness` GitHub Discussions.
