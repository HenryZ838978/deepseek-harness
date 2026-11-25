# `deepseek-harness-cli`

`dsh` — command-line companion to [`deepseek-harness`](https://pypi.org/project/deepseek-harness/).

```bash
pip install deepseek-harness-cli
export DEEPSEEK_API_KEY=sk-...

dsh doctor                       # verify env + 1-token live call
dsh doctor --node                # 12 witness probes for the official Node harness (@deepseek-ai/dsh)
dsh chat                         # interactive REPL with all guards on
dsh chat -r                      # enable thinking mode
dsh validate path/to/msgs.json   # offline contract audit (no API call)
dsh estimate path/to/msgs.json   # offline cache-hit estimate (no API call)
dsh probe probe_2 --n 3          # run a probe by name
dsh version
```

Why use this over a vanilla OpenAI client: the harness enforces all 10 contract rules from the [DeepSeek V4 spec](https://github.com/HenryZ838978/deepseek-harness/tree/main/spec) by default — saving you from the documented `400 reasoning_content`, V8 `Invalid string length` crashes, parallel-tool-delta misalignment, and dual cache-field invisibility.

`dsh doctor --node` checks an installed `@deepseek-ai/dsh` for what its own tooling does not report. That covers session-log seq gaps (it reads the v4 `.zstd` logs; `pip install deepseek-harness-cli[zstd]` or have the `zstd` CLI), env vars silently scrubbed from subagents, Files API cross-install deletion, and multimodal turns left without a reply. It also measures model behaviour live, such as `deepseek-v4-pro` making spurious tool calls with thinking off. Probes whose defect upstream has fixed read the installed version and stop reporting it. Per-release record: [HISTORY.md](https://github.com/HenryZ838978/deepseek-harness/blob/main/HISTORY.md).

License: MIT.
