#!/usr/bin/env bash
# whalecode · install
#
#   curl -fsSL https://whalecode.dev/install.sh | bash
#   curl -fsSL .../install.sh | DEEPSEEK_API_KEY=sk-... bash
#   bash install.sh --yes      # non-interactive
#   bash install.sh --uninstall

set -euo pipefail

WC_HOME="${WC_HOME:-$HOME/.whalecode}"
BIN_DIR="${WC_BIN_DIR:-$HOME/.local/bin}"
SKILLS_DIR="$HOME/.claude/skills"
ENV_FILE="$WC_HOME/env.sh"
CLAUDE_VERSION_RANGE="${WC_CLAUDE_VERSION:-^2.1.0}"
REPO_BASE="${WC_REPO_BASE:-https://raw.githubusercontent.com/HenryZ838978/whalecode/main}"
DEFAULT_BUDGET_USD="${WC_DEFAULT_BUDGET_USD:-5.00}"

# Allow running from a local checkout (the file's own dir is the source of truth)
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]:-$0}" )" 2>/dev/null && pwd )"

if [[ -t 1 ]]; then
  R='\033[0m'; D='\033[2m'; B='\033[1m'; G='\033[32m'; Y='\033[33m'; E='\033[31m'
else
  R=''; D=''; B=''; G=''; Y=''; E=''
fi

UNINSTALL=0
NON_INTERACTIVE=${YES:-0}
for a in "$@"; do
  case "$a" in
    --uninstall) UNINSTALL=1 ;;
    --yes|-y)    NON_INTERACTIVE=1 ;;
  esac
done

if [[ $UNINSTALL -eq 1 ]]; then
  rm -rf "$WC_HOME"
  rm -f "$BIN_DIR/whalecode"
  for s in "$SKILLS_DIR"/deepseek-harness "$SKILLS_DIR"/superpowers-*; do
    [[ -d "$s" ]] && rm -rf "$s"
  done
  printf "${G}✓${R} whalecode uninstalled (claude-code itself untouched)\n"
  exit 0
fi

# ---- silent preflight: bail loudly only on missing prereqs ----
command -v node >/dev/null 2>&1 || { printf "${E}need node ≥18${R} (brew install node)\n" >&2; exit 1; }
node_major="$(node -p 'process.versions.node.split(".")[0]')"
(( node_major >= 18 )) || { printf "${E}need node ≥18 (have $(node --version))${R}\n" >&2; exit 1; }
command -v git  >/dev/null 2>&1 || { printf "${E}need git${R}\n" >&2; exit 1; }
command -v curl >/dev/null 2>&1 || { printf "${E}need curl${R}\n" >&2; exit 1; }

mkdir -p "$WC_HOME" "$BIN_DIR" "$SKILLS_DIR"

# ---- claude-code (pinned) ----
if ! command -v claude >/dev/null 2>&1; then
  npm install -g "@anthropic-ai/claude-code@${CLAUDE_VERSION_RANGE}" >/dev/null 2>&1 || \
    npm install -g "@anthropic-ai/claude-code@${CLAUDE_VERSION_RANGE}" 2>&1 | tail -3
fi

# ---- key ----
KEY="${DEEPSEEK_API_KEY:-}"
if [[ -z "$KEY" && -f "$ENV_FILE" ]]; then
  KEY="$(grep -E '^export ANTHROPIC_AUTH_TOKEN=' "$ENV_FILE" 2>/dev/null | sed 's/.*=//;s/"//g' || true)"
fi
if [[ -z "$KEY" ]]; then
  if [[ $NON_INTERACTIVE -eq 1 ]]; then
    printf "${E}no DEEPSEEK_API_KEY set${R}\n" >&2; exit 1
  fi
  printf "  DeepSeek API key (https://platform.deepseek.com): "
  read -r KEY
fi
[[ -n "$KEY" ]] || { printf "${E}empty key${R}\n" >&2; exit 1; }

# ---- verify silently ----
if ! curl -sS -m 12 -X POST https://api.deepseek.com/anthropic/v1/messages \
  -H "x-api-key: $KEY" -H "anthropic-version: 2023-06-01" -H "content-type: application/json" \
  -d '{"model":"deepseek-chat","max_tokens":4,"messages":[{"role":"user","content":"ok"}]}' \
  | grep -q '"role":"assistant"'; then
  printf "${E}key validation failed${R} — check it at https://platform.deepseek.com\n" >&2; exit 1
fi

# ---- env file ----
cat > "$ENV_FILE" <<EOF
# whalecode env · do not edit by hand · regenerate with install.sh
export ANTHROPIC_BASE_URL="https://api.deepseek.com/anthropic"
export ANTHROPIC_AUTH_TOKEN="$KEY"
export ANTHROPIC_MODEL="\${ANTHROPIC_MODEL:-deepseek-v4-pro[1m]}"
export ANTHROPIC_DEFAULT_HAIKU_MODEL="\${ANTHROPIC_DEFAULT_HAIKU_MODEL:-deepseek-v4-flash}"
export ANTHROPIC_DEFAULT_SONNET_MODEL="\${ANTHROPIC_DEFAULT_SONNET_MODEL:-deepseek-v4-pro[1m]}"
export ANTHROPIC_DEFAULT_OPUS_MODEL="\${ANTHROPIC_DEFAULT_OPUS_MODEL:-deepseek-v4-pro[1m]}"
export CLAUDE_CODE_SUBAGENT_MODEL="\${CLAUDE_CODE_SUBAGENT_MODEL:-deepseek-v4-flash}"
export WC_DEFAULT_PERMISSION_MODE="\${WC_DEFAULT_PERMISSION_MODE:-bypassPermissions}"
export DISABLE_TELEMETRY=1
EOF
chmod 600 "$ENV_FILE"

# initialize daily budget cap if absent
[[ -f "$WC_HOME/budget" ]] || echo "$DEFAULT_BUDGET_USD" > "$WC_HOME/budget"

# ---- skill bundle: protocol layer + the superpowers 6-pack ----
CACHE_DIR="$WC_HOME/cache"
mkdir -p "$CACHE_DIR"
DSH="$CACHE_DIR/deepseek-harness"
SP="$CACHE_DIR/superpowers"
if [[ -d "$DSH/.git" ]]; then (cd "$DSH" && git pull --quiet 2>/dev/null || true); else
  git clone --depth 1 --quiet https://github.com/HenryZ838978/deepseek-harness.git "$DSH"; fi
if [[ -d "$SP/.git" ]];  then (cd "$SP"  && git pull --quiet 2>/dev/null || true); else
  git clone --depth 1 --quiet https://github.com/obra/superpowers.git "$SP"; fi
rm -rf "$SKILLS_DIR/deepseek-harness"
cp -r "$DSH/packages/skill" "$SKILLS_DIR/deepseek-harness"
for s in test-driven-development systematic-debugging verification-before-completion brainstorming writing-plans executing-plans; do
  src="$SP/skills/$s"
  if [[ -d "$src" ]]; then
    rm -rf "$SKILLS_DIR/superpowers-$s"
    cp -r "$src" "$SKILLS_DIR/superpowers-$s"
  fi
done

# ---- whalecode binary ----
if [[ -f "$SCRIPT_DIR/bin/whalecode" ]]; then
  cp "$SCRIPT_DIR/bin/whalecode" "$BIN_DIR/whalecode"
else
  curl -fsSL "$REPO_BASE/bin/whalecode" -o "$BIN_DIR/whalecode"
fi
chmod +x "$BIN_DIR/whalecode"

# ---- one-screen success ----
case ":$PATH:" in *":$BIN_DIR:"*) on_path=1 ;; *) on_path=0 ;; esac
printf "${B}🐋 WhaleCode ready.${R}  ${D}claude $(claude --version 2>/dev/null | awk '{print $1}') · pro[1m] default · 7 skills · cap \$$DEFAULT_BUDGET_USD${R}\n"
if (( on_path == 0 )); then
  printf "  ${Y}!${R}  add ${B}export PATH=\"$BIN_DIR:\$PATH\"${R} to your shell rc, then re-open the shell\n"
fi
printf "  ${B}whalecode init${R}      30-second guided demo on a sandbox\n"
printf "  ${B}whalecode \"...\"${R}     run on your own code\n"
