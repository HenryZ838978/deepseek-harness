# `deepseek-harness-cli`

`dsh` — command-line companion to [`deepseek-harness`](https://pypi.org/project/deepseek-harness/).

```bash
pip install deepseek-harness-cli
export DEEPSEEK_API_KEY=sk-...

dsh doctor                       # verify env + 1-token live call
dsh chat                         # interactive REPL with all guards on
dsh chat -r                      # enable thinking mode
dsh validate path/to/msgs.json   # offline contract audit (no API call)
dsh estimate path/to/msgs.json   # offline cache-hit estimate (no API call)
dsh probe probe_2 --n 3          # run a probe by name
dsh version
```

Why use this over a vanilla OpenAI client: the harness enforces all 10 contract rules from the [DeepSeek V4 spec](https://github.com/HenryZ838978/deepseek-harness/tree/main/spec) by default — saving you from the documented `400 reasoning_content`, V8 `Invalid string length` crashes, parallel-tool-delta misalignment, and dual cache-field invisibility.

License: MIT.
