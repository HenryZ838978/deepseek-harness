# DeepSeek V4 Pro 的 11% 工具调用消失之谜 + 缓存命中折扣指北

> Draft. 数据点会在 probe 跑完后填进表格里。

## 0. TL;DR
- DeepSeek V4 Pro 是为 agentic loop 设计的：**缓存命中价 $0.0028/M、未命中 $0.14/M，差 50 倍**。
- 但**主流 agent 框架**（LangChain、Cline 早期、agent-framework、hermes-agent）接它会**疯狂 400 + 隐性丢工具调用**。
- 4 类 bug 必须解：reasoning_content 生命周期 / tool_call 11% 漏到 content / strict mode 破坏 JSON / cache 字段双名错位。
- 我们写了一个 80 行就能 drop-in 替换 `from openai import OpenAI` 的 [`deepseek-v4pro-kit`](../README.md)，把这 4 件事一次解决。

## 1. 11% 的幽灵
（用 probe_3 跑出来的数据填这张图）

| 维度 | 值 |
|---|---|
| 跑次数 | 100 |
| `finish_reason='tool_calls'` 占比 | TBD |
| `finish_reason='stop'` 但 content 藏着 tool 调用 | TBD% |
| 漏水的 payload 形态分布 | DSML / `<tool_call>` / 裸 JSON / fenced ```json |

加 1-2 个真实漏水样本贴出来（来自 `findings/raw/probe_3_tool_call_leakage/*.jsonl`）。

社区证据：`deepseek-ai/DeepSeek-V3#1244` 报告 11% 失败率。`hermes-agent#15453` 指出不同 endpoint（vLLM / SGLang / OpenRouter）会改变漏水形态。

**修法**：见 spec §2 + `tool_calls.salvage_tool_calls_from_content()`。

## 2. 缓存命中：你以为你在省钱，其实没有

### 2a. 字段双名灾难

DeepSeek 写的是 `usage.prompt_cache_hit_tokens`，OpenAI 标准写 `usage.prompt_tokens_details.cached_tokens`。

vanilla OpenAI parser **完全看不到** DeepSeek 的 cache hit。`pi-mono#3880` 已经修了一次，但没扩散到下游。

**修法**：`cache.normalize_usage()` 同时填两个字段并算出 `estimated_cost_usd`。

### 2b. byte-for-byte 的残酷

DeepSeek 缓存只在 **token 0 起始的逐字节前缀匹配**才命中。换句话说：
- 你在 system prompt 中段插一行 "今日日期：xxxx-xx-xx" → 整个 prefix 缓存作废；
- 你的 agent 框架对 history 做了 prune / summarize → cache 作废；
- 你把上一轮的 `reasoning_content` 误带回来（它不是确定性的）→ cache 作废；
- 工具消息顺序变了 → cache 作废。

probe_5 的 S2 / S3 给出了量化曲线（中段扰动 vs 末端扰动）。

### 2c. V3.2 → V4 的灾难性回归

`deepseek-ai/DeepSeek-V3#1261`：一个企业用户从 V3.2 升级到 V4，cache hit rate 从 92% 跌到 35%，72 小时多花 ¥7,870。

**修法**：让 agent 在发送前用 `estimate_cache_hit()` 做 pre-flight check，看实际命中率，再决定要不要把那条"系统提醒"塞进去。

## 3. reasoning_content：为什么会 400

DeepSeek 在 thinking-mode 返回的 assistant message 上有一个非标准字段 `reasoning_content`。这个字段在多轮工具调用循环里 **必须** 原样回传，否则下一轮会被 server 直接 400。

任何严格遵循 OpenAI schema 的 agent 框架都会 strip 掉这个字段——所以 LangChain / agent-framework / hermes 接 DeepSeek 全都炸过。Cline 在 PR #7888 里实现了 `addReasoningContent`，是目前最佳参考。

**修法**：`reasoning.ReasoningLifecycle` + spec §1。

## 4. strict mode：官方说不修

`deepseek-ai/DeepSeek-V3#1069` 报告：当 `base_url=.../beta` + `function.strict=true` + `additionalProperties=false` 同时成立时，返回的 `tool_calls[0].function.arguments` 第一个 key 缺闭合引号 → JSON 解析直接炸。

issue 已被官方 close 为 not-planned。

**修法**：在 spec 里写死"不要用"，并提供 `detect_strict_mode_corruption()` 让你能在日志里 fingerprint 这种坏样本。

## 5. 一行替换、L5 兼容

```python
# before
from openai import OpenAI
client = OpenAI(api_key=key, base_url="https://api.deepseek.com")

# after
from deepseek_v4pro_kit import DeepSeekClient
client = DeepSeekClient(api_key=key, base_url="https://api.deepseek.com")
```

接着：
```python
out = client.chat(
    model="deepseek-chat",
    messages=history,
    tools=[my_tool],
)
print(out["usage"])         # 同时含两种 cache 字段 + USD 估算
print(out["salvage"])       # 不为 None 就说明 11% 那批被你救回来了
print(out["message"])       # 如果 salvage 命中，tool_calls 已经被 backfill 进 message
```

## 6. 数据透明

所有 probe 的原始 jsonl 都在 `findings/raw/`，summary 在 `findings/summary/`。
社区可以 fork 跑自己的数据，直接 PR 进 spec。

---
作者：zhangjing  ·  仓库：`deepseek-v4pro-survival-kit`  ·  License: MIT
