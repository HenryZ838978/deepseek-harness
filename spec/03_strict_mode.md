# §3 — `strict: true` mode (FIXED-IN-V4 — but still avoid)

## 3.1 Historical symptom (from upstream issue)

When all of:
  - `base_url` ends with `/beta`
  - tool definition has `function.strict: true`
  - tool's parameter schema has `additionalProperties: false`

…were true on the V3 series, DeepSeek would return `arguments` JSON missing the
closing `"` on the FIRST property key, e.g.:

```
arguments (broken):  {"selected: ["A", "C", "D"], "confidence": 0.9}
arguments (expected):{"selected": ["A", "C", "D"], "confidence": 0.9}
```

→ `json.JSONDecodeError`.

## 3.2 Citations

| Source | Status |
|---|---|
| `deepseek-ai/DeepSeek-V3#1069` | **Closed as `not-planned` by maintainers (Dec 2025).** |

## 3.3 Empirical status on V4 (probe_4 + probe_4_v4flash, 2026-05-09)

| endpoint | model | strict=true | additionalProperties=false | trials | corruption rate |
|---|---|---|---|---|---|
| `https://api.deepseek.com` | `deepseek-v4-pro` | yes | yes | 8 | **0%** |
| `https://api.deepseek.com/beta` | `deepseek-v4-pro` | yes | yes | 8 | **0%** |
| `https://api.deepseek.com` | `deepseek-v4-flash` | yes | yes | 8 | **0%** |
| `https://api.deepseek.com/beta` | `deepseek-v4-flash` | yes | yes | 8 | **0%** |

→ The bug appears to be **silently fixed** in the V4 series, despite the upstream
issue still being closed-as-not-planned.

## 3.4 Independent surprise: `/beta` endpoint silently remaps models

While running probe_4 we discovered:

> `/beta` endpoint maps `deepseek-v4-pro` → legacy `deepseek-reasoner`. The
> remapped model rejects `tool_choice={"type":"function","function":{"name":"X"}}`
> with: `400 deepseek-reasoner does not support this tool_choice`.

This is an undocumented behaviour and is itself a hazard for any agent framework
that auto-routes to /beta when "extended features" are enabled.

## 3.5 Normative rule

```yaml
strict_mode:
  status: FIXED-IN-V4
  upstream_position: WONTFIX (documentation lag)
  recommendation: |
    Adapters MAY enable function.strict=true on V4-pro / V4-flash
    against the standard endpoint. JSON corruption was not observed
    across 32 trials on 2026-05-09.

    Adapters SHOULD STILL avoid /beta routing when tools are passed,
    because /beta silently remaps modern models to legacy aliases
    (e.g. v4-pro → reasoner) with reduced feature support.

    Adapters SHOULD continue to perform their OWN schema validation
    post-hoc using json.loads() + jsonschema, because:
      - the fix is not officially announced;
      - the bug may regress under load / on alternate endpoints (vLLM, SGLang).
```

## 3.6 Reference implementation

`tool_calls.detect_strict_mode_corruption()` is retained as a fingerprint
function for log telemetry and future regression detection.
