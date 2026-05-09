# `deepseek-harness`

Protocol-aware Python client for **DeepSeek V4-Pro / V4-Flash**.
Survives the [16 documented quirks](https://github.com/HenryZ838978/deepseek-harness/blob/main/reports/REPORT_2026-05-09.md); ships the 50× cache discount.

```bash
pip install deepseek-harness
```

```python
from deepseek_harness import DeepSeekHarness

c = DeepSeekHarness(disable_thinking_by_default=True)
out = c.chat(
    model="deepseek-v4-pro",
    messages=[{"role": "user", "content": "Hello"}],
    max_tokens=4096,
)
print(out["message"]["content"])
print(f"cost: ${out['usage']['estimated_cost_usd']:.6f}  ·  cache hit: {out['usage']['cache_hit_rate']:.0%}")
```

The harness wraps `openai.OpenAI` and enforces 10 contract rules by default. See the [main repository](https://github.com/HenryZ838978/deepseek-harness) for the full spec, probe corpus, and three other distribution forms (`dsh` CLI, `@deepseek-harness/mcp` server, Anthropic `SKILL.md`).

License: MIT.
