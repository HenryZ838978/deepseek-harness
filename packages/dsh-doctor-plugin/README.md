# @deepseek-harness/dsh-doctor-plugin

**Meta-plugin. Witnesses the official DeepSeek Harness Node runtime.**

The official DeepSeek Harness (`@deepseek-ai/dsh`) advertises "Everything is a Plugin".
Fine. This plugin's job is to audit the runtime that hosts it.

## What it checks

Delegates to the Python witness suite `dsh doctor --node`:

| probe | title |
|---|---|
| `P1-reasoner-wire` | reasoner + tools ⇒ reasoning_content silence (wire-level, N-shot) |
| `P2-bom` | plugin manifests carry no UTF-8 BOM (#2798) |
| `P3-serve` | dsh web fence: cross-origin data path is rejected (#2573) |
| `P4-spill` | subprocess spill directory writable (spillAll no try/catch) |

Each probe returns `PASS` / `WARN` / `FAIL` / `SKIP`. Non-fail exit code = 0.

## Install

```bash
npm i -g @deepseek-harness/dsh-doctor-plugin
pip install deepseek-harness-cli
export DEEPSEEK_API_KEY=sk-...
```

## Run

```bash
dsh-doctor
dsh-doctor --json
dsh-doctor --only P1-reasoner-wire
dsh-doctor --url http://127.0.0.1:3080     # for P3
```

## Design

- Node shim is intentionally thin. All contract logic lives Python-side, next to the harness core.
- Probes are pure functions of `(env, argv)`. No shared state, no persistence.
- Adding a probe = one file under `deepseek_harness_cli/doctor_node/`; register in `__init__.py`.
- No probe fires a single-sample verdict on flaky wire behaviour. P1 samples N times and reports the *rate*.

## Why a meta-plugin

The official runtime treats plugins as first-class. We use that surface — instead of building a competing framework — to ship the witness. This is intentionally the *reverse* of what the runtime expects from a plugin: not a capability, but an audit.

## Provenance

Author: Henry Zhang (CyberWizard). Related: `deepseek-harness` (Python, PyPI) — the underlying protocol-aware harness. See repository root README for the full witness-stack story.
