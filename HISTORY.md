# dsh (Node) — history of what broke, per release

Machine-verifiable one-liners. Each entry: **date · release · what broke · fix**.
No opinion column. No hedge. Source lines are commit SHAs and file paths;
fix is always `pip install deepseek-harness-cli && dsh doctor --node`.

---

## 2026-05-11 · `deepseek-harness` **0.2.0** (this repo, PyPI; first commit 2026-05-09)

- Pure harness for DeepSeek V4-Pro / V4-Flash: 12 probes, 16 documented protocol behaviours, 270+ trials, one contract ([`spec/`](spec/), RFC 2119 normative) in four wrapper formats. Predates `@deepseek-ai/dsh` by three months. → PyPI: `pip install deepseek-harness` / `pip install deepseek-harness-cli`. Full timeline: [Provenance](README.md#provenance).

---

## 2026-08-13 · `@deepseek-ai/dsh` **0.1.0-rc.6** (GA, released with V4-Pro-0813)

- **`spillAll()` has no try/catch around `openSync`/`writeSync`** — the sibling `discardSpill()` is guarded, this one is not. EACCES / ENOSPC on the tmp dir escapes the `data` callback and takes the whole harness to `exit 1`. `dsh-subprocess-local/src/spawn.ts`. → **`dsh doctor --node --only P4-spill`**
- **`dsh plugin add` calls `JSON.parse` directly on file bytes** — a UTF-8 BOM crashes it. `stripBOM` never appears in `dsh-app-boot/lib/index.js`. → **`dsh doctor --node --only P2-bom`**
- **`dsh web` frontend loads under any Host, data layer 403s under any non-loopback Origin** — no user-visible error, page hangs on "Select a workspace". `api-request-trust.ts` does a literal `host ===` compare. → **`dsh doctor --node --only P3-serve --url http://your-dsh-web:3080`**
- **Concurrent writers on one session log produce silent truncation or permanent corrupt** — `session-persistence-jsonl` has zero flock / O_EXCL; `state.owner` is in-process only. → **`dsh doctor --node --only P5-seqgap`**

---

## 2026-08-17 · `@deepseek-ai/dsh` **0.1.0-rc.7**

- All four rc.6 defects above still present. `grep -rE 'flock|O_EXCL|lockf' packages/session/` still returns 0. rc.7 → rc.8 diff = **0** touches to `spillAll` / `stripBOM` / `Origin` check / persistence lock. → **`dsh doctor --node`** (all five probes)

---

## 2026-08-19 · `@deepseek-ai/dsh` **0.1.0-rc.8** (536 commits since rc.7; `next` tag, not yet `latest`)

- **All four rc.6 defects still present**, per source diff.
- **New: Agent Teams (`packages/experimental/agent-team`) inherits the session-log seq-gap failure mode** — Team state appends to the root Session log. README self-declares "not cross-process exactly-once delivery" and "no shared mailbox transaction across processes". Multi-subagent scenarios raise the trigger probability of the rc.6 seq-gap defect. → **`dsh doctor --node --only P5-seqgap`**
- **New: subagent env-scrub false positive** — `SENSITIVE_ENV_PATTERN = /KEY|PASSWORD|SECRET|TOKEN/i` in `packages/subprocess/subprocess/src/index.ts:44` is a substring match. It silently strips user-defined vars whose names contain those tokens (`MY_SERVICE_KEY`, `AWS_ACCESS_KEY_ID`, `GITHUB_TOKEN`, `MY_API_TOKEN`) from subagent children. No warning. → **`dsh doctor --node --only P6-subagent-env-scrub`**
- **New: subagent-codex plugin load crashes on missing `@openai/codex`** — `subagent-codex/src/run.ts:44` calls `createRequire(...).resolve('@openai/codex/package.json')` + `readFileSync` at module top-level with no try/catch. A Profile that references the Codex provider without `@openai/codex` installed takes down the entire dsh boot. → **`dsh doctor --node --only P7-subagent-codex-preflight`**
- **New: llm-deepseek multimodal composition can commit half a turn** — `adapter.ts:245-249` throws `UNSUPPORTED_CONTENT` inside `stream()` when a user turn carries an image but the attachment service is absent or the model's `inputModalities` doesn't include `image`. The throw happens *after* agent-loop appended the user turn (`agent.ts:346`), so the session persists an image-bearing user message with no assistant reply. User re-sends → double upload. → **`dsh doctor --node --only P8-multimodal-preflight`**
- **New: `subagent-codex` synchronously writes stderr via `writeFileSync(process.stderr.fd, bytes)`** — a slow host stderr sink blocks the event loop. Comment on `wire.ts:261` acknowledges "A slow host sink can block this event-loop turn". Chaos-only test surface; no offline probe.

---

## How to read this file

- **All entries are code-referenceable.** Every claim above cites a specific file or a specific defect id from the official `deepseek-ai/deepseek-harness` GitHub Discussions.
- **The fix column is always `dsh doctor --node`.** That command is: `pip install deepseek-harness-cli && dsh doctor --node`. It runs five probes offline and one live-network probe; each reports what the official Node stack does not.
- **Cross-check.** Every probe's source is [packages/cli/deepseek_harness_cli/doctor_node/](packages/cli/deepseek_harness_cli/doctor_node/) in this repo. Every "still present" claim is a `grep` you can run against the compiled rc.N artifact from `npm view @deepseek-ai/dsh@<version>`.
