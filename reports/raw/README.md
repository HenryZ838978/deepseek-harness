# findings/raw — probe 原始数据

每个 probe 写一个目录：`<probe_name>/<UTC-iso>.jsonl`。

每行是一个 trial 的 `TrialRecord`（见 `probes/_common.py`），包含：
- `probe`, `trial_idx`, `started_at`, `latency_ms`
- `status` (`ok` / `error`)
- `finish_reason`
- `usage` （已经过 `normalize_usage` 处理；同时含 `prompt_cache_hit_tokens` 和 `prompt_tokens_details.cached_tokens`）
- `salvage`（仅当我们救回了一个漏到 content 的 tool_call）
- `error`（如有，含 `type`/`message`）
- `notes`（probe 自定义）
- `raw_excerpt`（content 摘要 + 关键字段，避免落整个 raw response 占空间）

聚合：`make summary` → `findings/summary/<probe>.md`。
