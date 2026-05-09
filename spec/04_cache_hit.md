# §4 — Prefix cache: rules + field-name bridge

## 4.1 Why this section is the whole game

V4-Flash pricing (USD per million input tokens):
  - cache **miss**: `$0.14`
  - cache **hit** : `$0.0028`  → **98% off**

V4 Pro pricing has the same cache-vs-miss ratio (exact dollars vary by tier).

If your agent is rebuilt around DeepSeek's prefix-cache rules, you pay roughly
2% of what an LLM-naive agent pays. If you accidentally invalidate the prefix
on every turn, you pay 50× more for the same conversation.

## 4.2 Server-side rules (validated by probe_5 on 2026-05-09)

1. Cache works **prefix-from-0**, BUT: it is bucketed by ~256-token blocks. A
   single byte change near the START of input invalidates only the block(s)
   containing that byte and EVERYTHING AFTER it; earlier blocks still hit.
   (Empirically: probe_5 S2 mid-flip → `1280→512` cached tokens, i.e. the first
   2 × 256-token blocks survive.)
2. Practical minimum prefix length to begin caching: **~1024 tokens**. Below
   that, the server does not cache. (probe_5 confirmed: 1336 prompt → 1280
   cached after warmup.)
3. **Minimum cache granularity ≈ 256 tokens.** All observed cached_tokens
   counts are multiples of 256. Below that boundary, partial cache is rounded
   down.
4. **Cache eviction is real and observable.** probe_5 S1#3 saw a sudden return
   to 0% hit on an otherwise identical prefix sequence (S1#0–#2 and #4–#7 all
   95.8%). Cause unknown — possibly LRU pressure, server restart, or
   region-routing change.
5. **Tail changes preserve head cache.** probe_5 S3 last-char flip → 95.8%
   hit unchanged across 8 trials.
6. Cache persistence is triggered by:
   - request boundary (each request is a candidate),
   - common-prefix detection across recent requests for the same API key,
   - fixed-interval flush.

## 4.3 Field-name mismatch (pi-mono#3880)

DeepSeek populates:
```json
{ "usage": { "prompt_cache_hit_tokens": 1234, "prompt_cache_miss_tokens": 56 } }
```

OpenAI populates:
```json
{ "usage": { "prompt_tokens_details": { "cached_tokens": 1234 } } }
```

A vanilla OpenAI parser inspects only the latter, sees 0, and reports "no
cache hit" while the server happily charged you the cached price. 万恶之源。

## 4.4 Normative rules

1. Adapter **MUST** read both `prompt_cache_hit_tokens` and
   `prompt_tokens_details.cached_tokens`, take the maximum, and back-fill the
   other field for downstream telemetry.
2. Adapter **MUST** expose a pre-flight estimator `estimate_cache_hit(messages,
   previous_prefix)` returning at least `common_prefix_tokens` and
   `eligible_cached_tokens`.
3. Adapter **SHOULD** warn when an agent action would invalidate the prefix,
   e.g.:
     - reordering tool messages,
     - injecting reasoning_content from prior turns (see §1 rule 3),
     - inserting "system reminder" messages mid-conversation.
4. Adapter **MUST NOT** let agent-side history truncation/summarisation
   silently kill the cache. Either:
     - keep the full prefix and let DeepSeek charge cached price, OR
     - explicitly opt out with a flag like `cache_aware=False`.

## 4.5 Reference implementation

`src/deepseek_v4pro_kit/cache.py::normalize_usage` and `estimate_cache_hit`.

## 4.6 Cross-reference: V3.2 → V4 cache regression

`deepseek-ai/DeepSeek-V3#1261` reports a real-world drop from 92% → 35% cache
hit rate after the V3.2 → V4 upgrade, costing one user ¥7,870 in 72 hours.
Hypothesised root causes (still investigating):
  - the `reasoning_content` field's content is non-deterministic across retries,
    so re-sending it perturbs the prefix;
  - V4's tokenizer changes mean prefixes built under V3 tokenisation hash
    differently;
  - server-side cache buckets may be per-model, so re-routing requests across
    V4 / V4-Pro splits the cache.

probe_5 cannot fully resolve this without server logs, but it CAN measure the
hit-rate distribution over time for any given prefix — which is the data point
to escalate with.
