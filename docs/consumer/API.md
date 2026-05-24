# Consumer-side API contract (v1)

Single contract honored by:

- `packages/server` — `dsh serve` HTTP + SSE service (the runtime)
- `packages/desktop` — SwiftUI Mac app (talks to local `dsh serve` OR to cloud)
- `packages/mobile-pwa` — PWA chat client (always talks to cloud)
- `deploy/mdou` — same `dsh serve` image, multi-tenant on Rainbond K8s
- `deploy/helm` — same image, generic K8s

Versioning: path prefix `/v1`. Breaking changes bump to `/v2`.

## Auth

Two modes, gated by `DSH_AUTH_MODE`:

| mode | who uses it | how |
|---|---|---|
| `none` | local dev, single-user desktop calling its own embedded server | no token; bind to `127.0.0.1` only |
| `bearer` | cloud, multi-user | `Authorization: Bearer <jwt>` on every request |

JWT (mode `bearer`) claims:

```json
{ "sub": "<uid>", "exp": 1779000000, "tier": "free|paid", "iat": 1779000000 }
```

JWT is issued by `POST /v1/auth/login` after OTP verification.

## Endpoints

### `GET /health`

Always 200 with `{ "ok": true, "version": "0.x.y", "runtime": "claude-code@2.1.x" }`. No auth.

### `POST /v1/auth/login`

```http
POST /v1/auth/login
Content-Type: application/json

{ "phone": "+8613800000000", "otp": "123456" }
```

Response 200:

```json
{ "token": "eyJ…", "exp": 1779000000, "uid": "u_abc123" }
```

OTP delivery handled by SMS provider (Aliyun DYSMS) — server has `POST /v1/auth/otp` to trigger send.

In `none` mode this endpoint returns 404.

### `POST /v1/run` — the meat

Server-Sent Events stream.

```http
POST /v1/run
Authorization: Bearer <jwt>          # if bearer mode
Content-Type: application/json
Accept: text/event-stream

{
  "prompt": "fix the bug in app.py",
  "model": "auto",                    # auto | flash | pro | pro-1m
  "session_id": "s_xyz789",           # optional; resumes; new if omitted
  "workspace": "default",             # workspace label, server maps to /data/<uid>/<workspace>
  "attachments": [                    # optional
    {"type":"image","name":"shot.png","data_base64":"…"},
    {"type":"file","name":"app.py","data_base64":"…"}
  ],
  "permission_mode": "bypassPermissions"  # bypassPermissions|acceptEdits|plan
}
```

SSE event types (all `data: {json}` with `event: <name>`):

| event | payload | when |
|---|---|---|
| `session` | `{ session_id, created }` | first frame |
| `thinking` | `{ delta }` | reasoning chunk |
| `tool_call` | `{ id, name, args_preview, status:"started" }` | tool start |
| `tool_result` | `{ id, ok, rc, elapsed_ms }` | tool finish |
| `delta` | `{ text }` | answer token |
| `usage` | `{ input_tokens, output_tokens, cached_tokens, cost_usd }` | periodic (~1Hz) |
| `done` | `{ result, usage_total, cost_usd_total, num_turns }` | final |
| `error` | `{ code, message, hint }` | terminal error |

Codes for `error`:

- `budget_exceeded` — daily cap reached, `hint` carries cap
- `model_unavailable` — DeepSeek backend 5xx/429
- `auth_expired` — JWT expired, client should re-login
- `agent_crash` — claude-code exited non-zero with no result event

### `GET /v1/sessions`

List sessions for the authenticated user. Returns `[{ id, title, model, last_active, cost_usd_total }, …]`.

### `GET /v1/sessions/{id}`

Full transcript including prompts, deltas, tool calls, usage per turn.

### `DELETE /v1/sessions/{id}`

Delete a session (and its PVC scoped subdir).

### `GET /v1/budget`

```json
{ "today_usd": 0.42, "cap_usd": 5.00, "month_usd": 12.30, "tier": "paid" }
```

### `POST /v1/budget`

```json
{ "cap_usd": 10.00 }
```

Returns 403 if `tier=free` and `cap_usd > 1.00`.

### `POST /v1/cancel/{session_id}`

SIGINT the running agent for that session. Returns `{ ok: true }`.

## Streaming format

Always SSE (`Content-Type: text/event-stream`). No WebSocket in v1; SSE goes through:

- iOS Safari / Android Chrome ✅
- China-mainland CDN (Aliyun / Cloudflare) ✅
- HTTP/2 multi-stream ✅
- WeChat browser ✅

Each event:

```
event: delta
data: {"text":"hello"}

```

(Double newline terminator.)

## Errors (non-SSE)

JSON with HTTP status:

```json
{ "error": { "code": "auth_expired", "message": "...", "hint": "..." } }
```

## Rate limiting

Per-user, sliding 1-min window: 30 `/v1/run` starts. Returns 429 with `Retry-After`.

## CORS

`Access-Control-Allow-Origin` mirrored from `Origin` if it matches `DSH_ALLOWED_ORIGINS` (comma-separated). Default in `none` mode: `*`. Default in `bearer` mode: empty (must be configured).

## Storage layout (server-side)

```
/data/
  <uid>/
    .claude/                 # claude-code config + history (mounted as ~/.claude)
    workspaces/
      default/               # default working dir for agent
      <label>/               # additional workspaces
    sessions.db              # SQLite: sessions index, usage log
    budget                   # daily cap (USD)
```

In single-user desktop / `DSH_AUTH_MODE=none`, `<uid>` is fixed to `local`.
