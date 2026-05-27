# dsh-server container — runs on mdou (Rainbond/Aliyun K8s) and any plain K8s
# / docker-compose / docker run setup.
#
# Multi-stage so the final image stays well under 500 MB:
#   stage 1: install npm deps + @anthropic-ai/claude-code into a clean prefix
#   stage 2: slim alpine runtime + agent toolchain (python/uv/git/rg/jq/...)
#            so the agent can immediately exec real code on first request
#            instead of suffering an apk/pip install storm.

ARG NODE_VERSION=22-alpine

# Pull base images through DaoCloud's Docker Hub mirror — mdou's cloud builder
# can't reach docker.io directly. (Override with --build-arg DOCKER_MIRROR=
# docker.io for global docker daemons that hit Docker Hub fine.)
ARG DOCKER_MIRROR=docker.m.daocloud.io/library

# ---- stage 1: build ---------------------------------------------------------
FROM ${DOCKER_MIRROR}/node:${NODE_VERSION} AS build

WORKDIR /build

# Use npmmirror + Aliyun apk + pypi mirrors so installs work from mdou's
# in-cloud builder. Override the *_MIRROR build args for global use.
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
FROM ${DOCKER_MIRROR}/node:${NODE_VERSION}

ARG DOCKER_MIRROR=docker.m.daocloud.io/library
ARG APK_MIRROR=https://mirrors.aliyun.com/alpine
ARG PYPI_INDEX=https://mirrors.aliyun.com/pypi/simple/

# Pre-install the agent's typical Linux toolchain so the cloudagent loop can
# write + run code without an apk / pip install storm on first request.
#
# Note: the original spec called for "homebrew、python 之类的" preinstalled.
# Homebrew literally does not run on Alpine/musl; the spirit of the request
# ("agent's typical CLI toolchain pre-baked") is satisfied via apk + uv +
# pip below. See deploy/mdou/README.md for the substitution rationale.
#
# build-base / linux-headers / make are needed when uv/pip falls back to
# building a wheel from source (numpy etc.). openssh-client lets the agent
# clone private repos via ssh URLs.
#
# Switch apk + pip to Aliyun mirrors first so the layer doesn't time out
# trying to reach dl-cdn.alpinelinux.org / pypi.org from the mdou builder.
RUN sed -i "s|https://dl-cdn.alpinelinux.org/alpine|${APK_MIRROR}|g" /etc/apk/repositories \
    && apk add --no-cache \
        git curl wget ca-certificates tini \
        ripgrep jq fd \
        python3 py3-pip \
        make build-base linux-headers \
        openssh-client bash less \
    && python3 -m pip config set global.index-url "${PYPI_INDEX}" \
    && python3 -m pip install --no-cache-dir --upgrade --break-system-packages pip \
    && python3 -m pip install --no-cache-dir --break-system-packages \
        uv \
        requests httpx \
        anthropic openai \
        pydantic pyyaml \
        rich tqdm ipython \
    && addgroup -g 1500 dsh \
    && adduser  -u 1500 -G dsh -s /bin/bash -D dsh \
    && mkdir -p /home/dsh /home/dsh/.cache /home/dsh/.local /workspace \
    && chown -R dsh:dsh /home/dsh /workspace
# (UID/GID 1500 — node:22-alpine ships a 'node' user already at UID/GID 1000.)

WORKDIR /opt/app
COPY --from=build /build /opt/app
COPY --from=build /opt/claude-prefix /opt/claude-prefix
RUN ln -s /opt/claude-prefix/bin/claude /usr/local/bin/claude && \
    mkdir -p /data && chown -R dsh:dsh /opt/app /data

# Drop privileges. The runtime needs RW on /data (the PVC mount point) and
# /workspace (scratch area the agent can write into).
USER dsh

ENV HOME=/home/dsh \
    PATH=/home/dsh/.local/bin:/usr/local/bin:/usr/bin:/bin

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
