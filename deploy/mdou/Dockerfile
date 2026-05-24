# dsh-server container — runs on mdou (Rainbond/Aliyun K8s) and any plain K8s
# / docker-compose / docker run setup.
#
# Multi-stage so the final image stays under 250 MB:
#   stage 1: install npm deps + @anthropic-ai/claude-code into a clean prefix
#   stage 2: copy /opt/app + node_modules into a slim node:alpine image,
#            symlink claude into /usr/local/bin.

ARG NODE_VERSION=22-alpine

# ---- stage 1: build ---------------------------------------------------------
FROM node:${NODE_VERSION} AS build

WORKDIR /build

# Use npmmirror by default for fast / reliable installs from mdou (Aliyun cloud).
# Override with --build-arg NPM_REGISTRY=https://registry.npmjs.org for global.
ARG NPM_REGISTRY=https://registry.npmmirror.com
RUN npm config set registry "${NPM_REGISTRY}"

COPY packages/server/package.json ./
RUN npm install --omit=dev --no-audit --no-fund

# Pull claude-code globally into a local prefix so we can copy it into stage 2.
RUN npm install --prefix /opt/claude-prefix --no-audit --no-fund \
    @anthropic-ai/claude-code@^2.1.0

# Copy the server source last so code edits don't bust the npm cache.
COPY packages/server/src ./src
COPY packages/server/bin ./bin
COPY packages/skill ./skills/deepseek-harness

# ---- stage 2: runtime -------------------------------------------------------
FROM node:${NODE_VERSION}

# Tools the agent might shell out to (git, curl, ripgrep, jq, python3 for
# tiny scripts). Keep this list intentionally small.
RUN apk add --no-cache git curl ripgrep jq python3 ca-certificates tini && \
    addgroup -g 1000 dsh && \
    adduser  -u 1000 -G dsh -s /bin/sh -D dsh

WORKDIR /opt/app
COPY --from=build /build /opt/app
COPY --from=build /opt/claude-prefix /opt/claude-prefix
RUN ln -s /opt/claude-prefix/bin/claude /usr/local/bin/claude && \
    mkdir -p /data && chown -R dsh:dsh /opt/app /data

# Drop privileges. The runtime needs RW on /data (the PVC mount point).
USER dsh

# Default env. The K8s deployment (or `docker run -e`) overrides what matters.
ENV NODE_ENV=production \
    DSH_HOST=0.0.0.0 \
    DSH_PORT=7777 \
    DSH_DATA_DIR=/data \
    DSH_AUTH_MODE=bearer \
    DSH_LOG_LEVEL=info \
    ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic \
    ANTHROPIC_MODEL=deepseek-v4-pro[1m] \
    ANTHROPIC_DEFAULT_HAIKU_MODEL=deepseek-v4-flash \
    ANTHROPIC_DEFAULT_SONNET_MODEL=deepseek-v4-pro[1m] \
    ANTHROPIC_DEFAULT_OPUS_MODEL=deepseek-v4-pro[1m] \
    DISABLE_TELEMETRY=1

EXPOSE 7777

# Container readiness — Rainbond / K8s livenessProbe hits /health.
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD wget -qO- http://127.0.0.1:7777/health | grep -q '"ok":true' || exit 1

ENTRYPOINT ["/sbin/tini", "--"]
CMD ["node", "/opt/app/bin/dsh-server.js"]
