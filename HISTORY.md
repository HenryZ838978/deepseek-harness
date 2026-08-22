# dsh (Node) — history of what broke, per release

Machine-verifiable one-liners. Each entry: **date · release · what broke · fix**.
No opinion column. No hedge. Source lines are commit SHAs and file paths;
fix is always `pip install deepseek-harness-cli && dsh doctor --node`.

---

## 2026-05-11 · `deepseek-harness` **0.2.0** (this repo, PyPI; first commit 2026-05-09)

- Pure harness for DeepSeek V4-Pro / V4-Flash: 12 probes, 16 documented protocol behaviours, 270+ trials, one contract ([`spec/`](spec/), RFC 2119 normative) in four wrapper formats. Predates `@deepseek-ai/dsh` by three months. → PyPI: `pip install deepseek-harness` / `pip install deepseek-harness-cli`. Full timeline: [Provenance](README.md#provenance).

---

## 2026-08-22 · `deepseek-harness` **0.3.0** / `deepseek-harness-cli` **0.4.0** (this repo, PyPI)

- Multimodal contract added: `spec/07_multimodal.md`, `assert_multimodal_shape`, `estimate_image_tokens`, canonical image-URL placeholder in the cache-hit estimator, `deepseek-v4-flash-vision-exp` in the catalog. Text-only path unchanged. Tracks `@deepseek-ai/dsh` 0.1.1-rc.2's default vision model without depending on it. → PyPI: `pip install -U deepseek-harness deepseek-harness-cli`.

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

## 2026-08-21 · `@deepseek-ai/dsh` **0.1.1-rc.1** (172 commits since rc.8; `next` tag; rc.8 skipped `latest`)

**Of the 8 defects `dsh doctor --node` covers, 0 fixed in this release.** Source diff confirms `spillAll` / `stripBOM` / `api-request-trust` `host ===` / `session-persistence-jsonl` flock / `SENSITIVE_ENV_PATTERN` / `subagent-codex/run.ts:44` `readFileSync` / `adapter.ts:245` throw-after-append are all byte-identical to rc.8. Our four upstream Discussion replies (#2571 / #2573 / #2751 / #2798) posted 2026-08-18 also received no engagement.

- **FIXED (in-release; independently observed):** `bwrap` PID namespace escape via `procfs`. `packages/sandbox/sandbox-local/src/profiles.ts:17` now passes `--unshare-pid --proc /proc`. Not a defect our doctor covered; noted for the record.
- **Still present, per grep on tag `dsh-v0.1.1-rc.1`:** P2-bom · P3-serve · P4-spill · P5-seqgap · P6-subagent-env-scrub · P7-subagent-codex-preflight · P8-multimodal-preflight. → **`dsh doctor --node`**
- **New: `packages/credentials/credentials-local` uses `withFileLock` from `@deepseek-ai/dsh-atomic-write`.** The same monorepo now uses cross-process file locking in one subsystem — and continues to not use it in `session/session-persistence-jsonl` (P5). The absence of locking on session logs is a subsystem-level choice, not a codebase-wide missing primitive.
- **New: Vision model published (`deepseek-v4-flash-vision-exp`).** `packages/llm/llm-deepseek/src/index.ts:55-58` adds it to the default advisory catalog. Any user who selects the model **without** mounting `@deepseek-ai/dsh-attachment-local` in their composition hits the P8 half-turn commit on the first image. rc.1 is the first release that recommends this model out of the box. → **`dsh doctor --node --only P8-multimodal-preflight`** (existing probe; scope now widened)
- **New: credentials-local README self-declares "That is discretion, not a boundary. A deployment that must keep provider keys away from its own agent cannot get there with file permissions".** Same-UID processes (including the model's own sandboxed shell) can read the credentials file. OS-keychain provider is "deferred". Consistent with the rc.8 team package README pattern: disclose a boundary limitation, ship anyway, defer.
- **Audited, not a defect: two `dangerouslySetInnerHTML` sites in the web UI.** `ui-renderer/src/client/index.ts:56` mirrors the framework-free boot DOM into React hydration — the payload is the app's own initial HTML, not user content. `ui-primitives/src/markdown/CodeBlock.tsx:56` renders shiki's static span tree — shiki's own docs sanction this as its consumption path. Markdown pipeline (`ui-primitives/src/markdown/render.tsx:267`) drops raw HTML to literal text; `sanitizeUrl` allows only `http/https/mailto`. Recording the check so a future reader knows this surface was looked at.

---

## 2026-08-21 · `@deepseek-ai/dsh` **0.1.1-rc.2** (35 commits since rc.1, ~6 hours later; **promoted to `latest`** — first version made general-audience since 0.1.0-rc.7)

Nearly the whole diff is one topic: unified request-image pipeline with the new DeepSeek Files API upload path. `feat(images): unify master and Files request pipeline` + `fix(llm-deepseek): fall back when Files resolution fails` + `fix(deepseek): decouple files and stream timeouts`.

- **All 8 previous defects still present** at tag `dsh-v0.1.1-rc.2`. Same grep as rc.1: `spillAll` / `stripBOM` / `api-request-trust host===` / `session-persistence flock` / `SENSITIVE_ENV_PATTERN` / `subagent-codex readFileSync` / `adapter.ts hasImages throw-after-append` all byte-identical.
- **New: DeepSeek Files API upload-index is not cross-instance safe under one API key.** `packages/llm/llm-deepseek/src/file-store.ts:reclaimOldestOwned` deletes remote /files entries whose filename starts with `OWNED_FILE_PREFIX = 'dsh-'`. The prefix is dsh-ecosystem-wide, not per-install. Two dsh installs sharing one API key (team, CI, one dev + two machines) each maintain a separate local `~/.dsh/llm-deepseek/files-v3.json` but hit the same remote quota — when A's `reclaimOldestOwned` fires, it happily deletes file_ids B is still using. B's next image request hits "unknown file_id", loses prefix cache. → **`dsh doctor --node --only P9-files-quota-scope`**
- **Observed but not a probe: aggressive downscale on upload.** `attachment-local/src/request-image.ts:requestImageDimensions()` scales to `maxPixels` cap with aspect-preserving integer rounding. A 5000×5000 source going to a 512×512 provider budget loses information client-side, before the model sees it. DSH-side, not a wire bug; users who wonder "why can't the model see the fine text in my screenshot" are looking at this. sharp/libvips is well-behaved code — the concern is the policy, not the implementation.
- **Observed but not a probe: no slice/tiling on dsh side.** grep for `slice|tile|patch` on the image pipeline returns 0 matches unrelated to hash prefixes. DSH sends one flat image (via data URL or file_id); server-side tiling is the model's problem, not dsh's. Architectural choice, not a defect — recorded so the map is complete.
- **Observed but not a probe: no vision streaming prefill.** Vision content is fully assembled before `stream()` opens. Aligns with DeepSeek chat/completions capabilities; no gap here.

---

## How to read this file

- **All entries are code-referenceable.** Every claim above cites a specific file or a specific defect id from the official `deepseek-ai/deepseek-harness` GitHub Discussions.
- **The fix column is always `dsh doctor --node`.** That command is: `pip install deepseek-harness-cli && dsh doctor --node`. It runs five probes offline and one live-network probe; each reports what the official Node stack does not.
- **Cross-check.** Every probe's source is [packages/cli/deepseek_harness_cli/doctor_node/](packages/cli/deepseek_harness_cli/doctor_node/) in this repo. Every "still present" claim is a `grep` you can run against the compiled rc.N artifact from `npm view @deepseek-ai/dsh@<version>`.
