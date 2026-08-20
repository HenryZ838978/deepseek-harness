# deepseek-harness-cli 0.3.1

Three new probes for **`@deepseek-ai/dsh` rc.8** defects, plus one expanded scope for P5.

```bash
pip install -U deepseek-harness-cli
export DEEPSEEK_API_KEY=sk-...   # only P1 needs the key
dsh doctor --node
```

## What's new

- **P5-seqgap** — scope expanded. rc.8's `packages/experimental/agent-team` appends Team state to the root Session log; multi-subagent scenarios raise the seq-gap trigger probability. Title and detail message updated; probe logic unchanged (the same scanner catches both single-session and Teams-shared logs). The team package's README self-declares "not cross-process exactly-once delivery".

- **P6-subagent-env-scrub** *(new)*. `SENSITIVE_ENV_PATTERN = /KEY|PASSWORD|SECRET|TOKEN/i` in `packages/subprocess/subprocess/src/index.ts:44` is a substring match — it silently strips user-defined vars like `MY_SERVICE_KEY`, `AWS_ACCESS_KEY_ID`, `GITHUB_TOKEN` from subagent children (Claude Code / Codex spawn paths). This probe surveys your environment, flags what will be scrubbed, and separates canonical credential handles from user surprises. Offline; no key.

- **P7-subagent-codex-preflight** *(new)*. `subagent-codex/src/run.ts:44` calls `createRequire(...).resolve('@openai/codex/package.json')` + `readFileSync` at module top-level with no try/catch. If your Profile references the Codex provider without `@openai/codex` installed, plugin load throws `ERR_MODULE_NOT_FOUND` and takes down the entire dsh boot. This probe checks whether both packages are present in reachable `node_modules`. Offline.

- **P8-multimodal-preflight** *(new)*. In `packages/llm/llm-deepseek/src/adapter.ts:235-249`, an image-bearing user turn throws `UNSUPPORTED_CONTENT` inside `stream()` when either (a) the referenced model doesn't declare `inputModalities: [image]`, or (b) no attachment provider is mounted. The throw happens **after** `agent-loop/src/agent.ts:346` appended the user turn to the session log — so the session persists an image-bearing user message with no assistant reply. The user re-sends. Double upload, and no composition-level diagnostic ever surfaces. This probe scans your dsh profiles/composition for the combination and flags it before you ship. Offline.

## Also

- HISTORY.md updated to reflect the four new probes.
- README pitch table unchanged in shape but implicitly extended (five probes → eight).
- Core `deepseek-harness` still at 0.2.0; protocol contract unchanged.

## Not fixed here (still on the list)

- **`subagent-codex` synchronous `writeFileSync(process.stderr.fd, bytes)` blocking the event loop under slow host stderr sinks** — the comment on `wire.ts:261` acknowledges the block. Requires chaos-test to demonstrate; no offline probe added.
- **`sdkEnvironmentOverlay` sets tombstones as `undefined`** — Node child_process treats `env: { X: undefined }` inconsistently on Windows. Cross-platform bug; no repro on our test machines yet.
