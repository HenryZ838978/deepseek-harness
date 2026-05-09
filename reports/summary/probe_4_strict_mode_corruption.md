# probe_4_strict_mode_corruption summary

trials: **10**

## status
- `error`: 10 (100.0%)

## latency_ms
- p50=92  p90=185  p99=185  max=492

## errors by type
- `BadRequestError` × 10
  - Error code: 400 - {'error': {'message': 'deepseek-reasoner does not support this tool_choice', 'type': 'invalid_request_error', 'param': None, 'code': 'invalid_request_error'}}

