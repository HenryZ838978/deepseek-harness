# Deploy `dsh-server` to mdou (Rainbond on Aliyun)

This folder ships everything mdou needs to build + run `dsh-server` as a multi-tenant cloud backend for the DeepSeek-Harness Mac app and PWA.

## What gets deployed

A single container running `node bin/dsh-server.js`:

- Listens on `:7777` (mdou maps to an external HTTPS endpoint via "添加域名")
- `DSH_AUTH_MODE=bearer` (multi-tenant, JWT-gated)
- `/data` is the PVC mount — per-user sessions, usage log, budget, workspace
- `claude` (Anthropic Claude Code) baked in
- Agent CLI toolchain pre-baked — see "Pre-installed agent toolchain" below
- Image size targets < 500 MB

### Pre-installed agent toolchain

When the cloudagent loop writes + runs code we don't want it stuck behind a
fresh `apk add` / `pip install` on every cold request. The Dockerfile bakes
in a representative chunk of what an agent typically reaches for:

| layer | items |
|---|---|
| OS (`apk`)   | `git curl wget ripgrep jq fd bash less openssh-client tini ca-certificates` |
| build deps   | `make build-base linux-headers` (so `pip` can compile wheels from source if needed) |
| python       | `python3 py3-pip` upgraded, plus `uv` (fast resolver) |
| python libs  | `requests httpx anthropic openai pydantic pyyaml rich tqdm ipython` |

**Why no Homebrew?** The original brief said "homebrew、python 之类的需要用的都给他预装上". Homebrew is not portable to Alpine / musl libc — the formulae expect Linuxbrew on glibc — so it would balloon the image past 500 MB and add no value. The spirit of the request is "agent's typical toolchain ready to go", which the apk + uv + pip layer above satisfies. If a future task genuinely needs glibc Homebrew we should switch the base image to `node:22-bookworm-slim` and install Linuxbrew, not bolt brew onto Alpine.

## One-time mdou setup (the steps you do in mdou web UI)

1. Go to https://mdou.modelbest.co → 新建应用 → 中文名 "深求云端 (server)" → 英文名 `dsh-cloudagent` → 域名前缀 `dsh-api` (final URL `https://dsh-api.mdou.modelbest.co`)
2. Note the **应用 ID** (a number, e.g. 123). You'll feed it back to Cursor.
3. Add 端口 `7777` (协议 HTTP), enable "对外服务"
4. 添加域名 → 选 `dsh-api` 前缀 → mdou auto-routes 7777
5. 添加环境变量:
   | name | value | secret? |
   |---|---|---|
   | `DEEPSEEK_API_KEY` | DeepSeek API key (used by the buddy / agent loop) | ✅ |
   | `ANTHROPIC_AUTH_TOKEN` | DeepSeek API key (claude-code reads this name) | ✅ |
   | `DSH_BEARER_TOKEN` | a 64-char hex string (`openssl rand -hex 32`) | ✅ |
   | `DSH_JWT_SECRET` | a 64-char hex string (`openssl rand -hex 32`) | ✅ |
   | `DSH_OTP_PROVIDER` | `aliyun` (later, when SMS is wired) or leave `mock` for now | |
   | `DSH_ALLOWED_ORIGINS` | `https://cloud.deepseek-harness.dev,https://dsh-api.mdou.modelbest.co` | |
6. Add a **PVC** mounted at `/data` (≥ 10 GB; resize later)

## Build & deploy (the one-line you actually use)

From repo root, with `mdou-deploy` skill installed and `.credentials.json` ready, just say to Cursor:

```
部署 123
```

(where `123` is the 应用 ID from step 2)

The `mdou-deploy` skill picks up `deploy/mdou/Dockerfile` automatically (since there's no root Dockerfile and there is one here, configure mdou's "构建上下文" to `.` and "Dockerfile 路径" to `deploy/mdou/Dockerfile`).

If mdou's UI doesn't allow custom Dockerfile path, symlink at the repo root before deploying:

```bash
ln -s deploy/mdou/Dockerfile Dockerfile
```

(and `.dockerignore` is already at `deploy/mdou/.dockerignore`; symlink that to root too, or move it to root).

## After deploy — verify

```bash
curl https://dsh-api.mdou.modelbest.co/health
# {"ok":true,"version":"0.1.0","runtime":"claude-code","auth_mode":"bearer","has_anthropic_key":true}

# OTP login (mock provider returns dev_code in response)
curl -X POST https://dsh-api.mdou.modelbest.co/v1/auth/otp \
  -H 'content-type: application/json' \
  -d '{"phone":"+8613800138000"}'
# {"sent":true,"devCode":"123456"}

curl -X POST https://dsh-api.mdou.modelbest.co/v1/auth/login \
  -H 'content-type: application/json' \
  -d '{"phone":"+8613800138000","otp":"123456"}'
# {"token":"eyJ…","exp":…,"uid":"u_…"}

# Stream a real prompt
TOKEN=eyJ…
curl -N -X POST https://dsh-api.mdou.modelbest.co/v1/run \
  -H "authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d '{"prompt":"用一个字回答：你好","model":"flash"}'
```

Then point the PWA at `https://dsh-api.mdou.modelbest.co` (via the in-app "服务器" setting or by setting `localStorage.BACKEND_URL`) and you have a working cloud agent.

## Operational notes

- **Scaling**: mdou (Rainbond) supports HPA + idle-scaling. v1 = 1 replica always-on; v2 add `KEDA` per-user pod (see `deploy/helm/`).
- **Logs**: `mdou logs <APP_ID>` once that subcommand ships; meanwhile mdou web UI → 实例日志.
- **PVC**: `/data` survives container restarts. NEVER store secrets here — put them in env vars.
- **Updating**: re-say `部署 <ID>` to Cursor; mdou rebuilds + rolls.
- **Cost**: mdou charges by CPU / RAM hour. Single-replica node:alpine + node server ≈ ¥0.2 / hour at the smallest size. DeepSeek API costs go on the `ANTHROPIC_AUTH_TOKEN` account separately.

## Local testing (no mdou)

```bash
# Build locally
docker build -t dsh-server -f deploy/mdou/Dockerfile .

# Run with the same env you'd give mdou
docker run --rm -p 7777:7777 \
  -e ANTHROPIC_AUTH_TOKEN=sk-... \
  -e DSH_JWT_SECRET=$(openssl rand -hex 32) \
  -e DSH_AUTH_MODE=bearer \
  -v $(pwd)/data:/data \
  dsh-server
```

Or skip docker entirely (Mac dev): from `packages/server/`, `node bin/dsh-server.js` works as long as `claude` and `node` are on PATH.
