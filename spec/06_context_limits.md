# §6 — Context-window boundaries (independent finding, validated 2026-05-09)

> No public bug report covers this. We measured it directly.

## 6.1 Hard ceiling: **1,048,576 tokens (= 2^20 = 1 MiB tokens)**

`deepseek-v4-pro` accepts requests strictly under this ceiling. At or above,
the server returns:

```
HTTP 400 Bad Request
{
  "error": {
    "message": "This model's maximum context length is 1048576 tokens. However,
                you requested 1060836 tokens (1060828 in the messages, 8 in the
                completion). Please reduce the ...",
    "type": "invalid_request_error",
    ...
  }
}
```

The error breaks down `requested = messages + completion`, which means:

> `len(messages_tokens) + max_tokens <= 1_048_576`.

If you ask for `max_tokens=4096`, your messages can be at most `1_044_480` tokens.

## 6.2 Latency curve (probe_6 + probe_6b, single trial each, cold path)

| target_input | server_prompt_tokens | latency (cold) |
|---|---|---|
| 16K   | 10,093    | 2278 ms |
| 64K   | 39,110    | 1591 ms |
| 128K  | 79,441    | 1841 ms |
| 200K  | 197,912   | 5064 ms |
| 500K  | 494,559   | 8085 ms |
| 800K  | 792,075   | 12,474 ms |
| 1M    | 989,913   | **15,566 ms** |
| 1.04M | 1,038,100 | 5321 ms (cache hit on prior identical prefix) |
| **>1.05M** | rejected | hard 400 |

Approximate: **~1.5 ms / 1K input tokens** for cold prefix, much less for warm.

## 6.3 Tokenizer compression ratio (validated empirically)

For different content types:

| content type | server tokens / local chars |
|---|---|
| repeating English ASCII (`"background context block. " * N`) | ~5.9 chars/token |
| random lowercase letters (`abcdefghijklmnopqrstuvwxyz`) | ~3.5 chars/token |
| cl100k_base baseline | ~4.0 chars/token |

Implication for `cache.estimate_cache_hit()`: when prefix contains repeating /
templated content (system prompts, code), the server's effective token count
will be SMALLER than the local cl100k_base estimate. Adapter SHOULD treat
local estimates as an upper bound.

## 6.4 Normative rules

1. Adapter **MUST** validate `len(messages_tokens) + max_tokens <= 1_048_576`
   locally before sending. Use `tiktoken.cl100k_base` × 0.65 as a safe lower
   bound for English/code content.
2. Adapter **SHOULD** surface server-vs-local token-count divergence as a warning
   when > 30%; this is a sign the local tokenizer drift is about to cause a
   cache-prefix mismatch.
3. Adapter **SHOULD** budget at least **15 seconds** of latency per request when
   prompt size approaches 1M tokens. Streaming is preferred at this scale.
4. Adapter **SHOULD NOT** cap `max_tokens` near `1_048_576 - prompt_tokens`
   without leaving headroom — the server enforces the inequality strictly, and
   off-by-one rejection is silent (you get the 400 above, not a partial response).
