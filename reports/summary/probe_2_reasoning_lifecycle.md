# probe_2_reasoning_lifecycle summary

trials: **9**

## status
- `ok`: 6 (66.7%)
- `error`: 3 (33.3%)

## finish_reason
- `tool_calls`: 3 (33.3%)
- `stop`: 3 (33.3%)

## latency_ms
- p50=2108  p90=4901  p99=4901  max=9304

## errors by type
- `BadRequestError` × 3
  - Error code: 400 - {'error': {'message': 'The `reasoning_content` in the thinking mode must be passed back to the API.', 'type': 'invalid_request_error', 'param': None, 'code': 'invalid_request_error'}

