# probe_6b_context_ceiling summary

trials: **7**

## status
- `ok`: 6 (85.7%)
- `error`: 1 (14.3%)

## finish_reason
- `stop`: 6 (85.7%)

## latency_ms
- p50=8047  p90=12474  p99=12474  max=15566

## errors by type
- `BadRequestError` × 1
  - Error code: 400 - {'error': {'message': "This model's maximum context length is 1048576 tokens. However, you requested 1060836 tokens (1060828 in the messages, 8 in the completion). Please reduce the 

