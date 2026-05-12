# Changelog

All notable changes to this project will be documented in this file.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] — 2026-05-11

### Added — initial public release

- **`packages/core`** — Python library `deepseek-harness` published to PyPI.
  Public API: `DeepSeekHarness`, `normalize_usage`, `estimate_cache_hit`,
  `ReasoningLifecycle`, `salvage_tool_calls_from_content`.
- **`packages/cli`** — Command-line tool `deepseek-harness-cli` published to
  PyPI. Entrypoint `dsh` with subcommands `doctor`, `chat`, `probe`, `validate`,
  `estimate`, `version`.
- **`packages/mcp`** — TypeScript MCP server `@deepseek-harness/mcp` published
  to npm. Stdio transport, MCP protocol version `2024-11-05`. Exposes four
  tools: `deepseek_chat`, `deepseek_chat_stream`, `validate_message_history`,
  `estimate_cache_hit`.
- **`packages/skill`** — Anthropic `SKILL.md` with bundled `safe_init.py`
  zero-dependency snippet and compact reference card.
- **`spec/`** — Six chapters of RFC 2119 normative protocol contract.
- **`reports/`** — Twelve probes, 270+ trial JSONL fixtures, 16 documented
  findings, paper-style technical report.
- **`docs/`** — Technical report, machine-readable trust ledger, narrative
  blog companion.

### Verified

- 14/14 unit tests pass.
- `dsh doctor` returns green status table; live call cost ≈ \$0.000002 USD.
- MCP server `initialize` + `tools/list` + `deepseek_chat` succeed via JSON-RPC
  over stdio.
- `probe_2` reproduces the `reasoning_content` lifecycle 400 in 3/3 trials,
  confirming the harness performs a non-trivial transformation.

### Distribution

- PyPI: <https://pypi.org/project/deepseek-harness/0.2.0/>
- PyPI: <https://pypi.org/project/deepseek-harness-cli/0.2.0/>
- npm: <https://www.npmjs.com/package/@deepseek-harness/mcp>
- GitHub release: <https://github.com/HenryZ838978/deepseek-harness/releases/tag/v0.2.0>

[0.2.0]: https://github.com/HenryZ838978/deepseek-harness/releases/tag/v0.2.0
