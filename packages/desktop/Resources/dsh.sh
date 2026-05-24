#!/usr/bin/env bash
# whalecode · 鲸码 · DeepSeek-harnessed coding agent
# https://github.com/HenryZ838978/whalecode
#
# Subcommands:
#   whalecode "..."             one-shot prompt (cost-tracked)
#   whalecode                   interactive REPL (passes through to claude)
#   whalecode doctor            connectivity + skill audit
#   whalecode init              30-second guided demo on a fresh sandbox
#   whalecode skills            list installed skills
#   whalecode skills add NAME   pull a skill from upstream catalog
#   whalecode budget            today's spend / daily cap
#   whalecode budget set USD    raise/lower daily cap (writes ~/.whalecode/budget)
#   whalecode --about           the story
#   whalecode --version
#
# Anything else passes straight through to claude-code with the env sourced.

set -e

WC_HOME="${WC_HOME:-$HOME/.whalecode}"
WC_VERSION="0.1.0"
ENV_FILE="$WC_HOME/env.sh"
USAGE_LOG="$WC_HOME/usage.jsonl"
BUDGET_FILE="$WC_HOME/budget"
DEFAULT_BUDGET_USD="5.00"

# ---- styling (only when stdout is a tty) ----
if [[ -t 1 ]]; then
  C_RST='\033[0m'; C_DIM='\033[2m'; C_BOLD='\033[1m'
  C_OK='\033[32m'; C_WARN='\033[33m'; C_ERR='\033[31m'
  C_BLUE='\033[36m'; C_PURPLE='\033[35m'
else
  C_RST=''; C_DIM=''; C_BOLD=''; C_OK=''; C_WARN=''; C_ERR=''; C_BLUE=''; C_PURPLE=''
fi

# ---- preflight: first-run auto-init when env file missing ----
if [[ ! -f "$ENV_FILE" ]]; then
  # find install.sh: bundled alongside this binary, or downloaded from upstream
  here="$( cd "$( dirname "${BASH_SOURCE[0]:-$0}" )" 2>/dev/null && pwd )"
  candidates=(
    "$here/../install.sh"             # npm global prefix layout
    "$here/install.sh"                # same dir as bin
    "$WC_HOME/install.sh"
  )
  installer=""
  for c in "${candidates[@]}"; do
    [[ -f "$c" ]] && { installer="$c"; break; }
  done
  if [[ -z "$installer" ]]; then
    # fall back to upstream
    installer="$WC_HOME/install.sh"
    mkdir -p "$WC_HOME"
    curl -fsSL "${WC_REPO_BASE:-https://raw.githubusercontent.com/HenryZ838978/whalecode/main}/install.sh" -o "$installer" 2>/dev/null || {
      printf "%bwhalecode: first-run setup needed but no installer found%b\n" "$C_ERR" "$C_RST" >&2
      exit 1
    }
  fi
  printf "${C_BOLD}🐋 first run${C_RST} — quick setup (≈10 seconds)\n"
  bash "$installer"
  echo
fi
# shellcheck disable=SC1090
source "$ENV_FILE"

# ---- helpers ----
budget_today() {
  if [[ -f "$BUDGET_FILE" ]]; then cat "$BUDGET_FILE"; else echo "$DEFAULT_BUDGET_USD"; fi
}
spent_today() {
  [[ -f "$USAGE_LOG" ]] || { echo "0"; return; }
  local today; today="$(date +%Y-%m-%d)"
  python3 -c "
import json,sys
total=0.0
for ln in open('$USAGE_LOG'):
    try:
        r=json.loads(ln)
        if r.get('ts','').startswith('$today'): total+=float(r.get('cost_usd',0))
    except: pass
print(f'{total:.4f}')"
}
log_usage() {
  # args: cost_usd turns model
  mkdir -p "$WC_HOME"
  printf '{"ts":"%s","cost_usd":%s,"turns":%s,"model":"%s"}\n' \
    "$(date -Iseconds 2>/dev/null || date)" "$1" "$2" "$3" >> "$USAGE_LOG"
}
preflight_budget() {
  local cap; cap="$(budget_today)"
  local sp;  sp="$(spent_today)"
  python3 -c "
cap=float('$cap'); sp=float('$sp')
if sp >= cap:
    print(f'BLOCK::{sp:.2f}::{cap:.2f}')
elif sp >= 0.8*cap:
    print(f'WARN::{sp:.2f}::{cap:.2f}')
else:
    print(f'OK::{sp:.2f}::{cap:.2f}')"
}
fmt_cost() {
  # args: cost_usd cache_read input output
  python3 -c "
cost=float('$1'); cr=int('$2'); ip=int('$3'); op=int('$4')
total_in = cr+ip
hit = (cr/total_in*100) if total_in>0 else 0
print(f'\${cost:.3f} · {hit:.0f}% cached · in {total_in/1000:.1f}k / out {op/1000:.1f}k')"
}

# ---- subcommands ----

cmd_about() {
  cat <<ABOUT

  ${C_BOLD}🐋 WhaleCode · 鲸码${C_RST}  v$WC_VERSION

  Anthropic Claude Code, harnessed for DeepSeek V4.
  One install, one key, one daily budget cap.

  ${C_DIM}Built on:
    @anthropic-ai/claude-code   (the runtime)
    api.deepseek.com/anthropic  (DeepSeek's official Anthropic-compatible endpoint)
    deepseek-harness            (10 protocol contract rules)
    superpowers (optional)      (TDD / debug / plan / review skills)${C_RST}

  ${C_DIM}https://github.com/HenryZ838978/whalecode${C_RST}

ABOUT
}

cmd_doctor() {
  printf "${C_BOLD}🐋 whalecode doctor${C_RST}\n"
  printf "  endpoint    %s\n" "$ANTHROPIC_BASE_URL"
  printf "  model       %s\n" "${ANTHROPIC_MODEL:-?}"
  printf "  claude      %s\n" "$(claude --version 2>/dev/null | head -1 || echo 'NOT INSTALLED')"
  printf "  skills      "
  local sk_dir="$HOME/.claude/skills"
  if [[ -d "$sk_dir" ]]; then
    ls "$sk_dir" 2>/dev/null | tr '\n' ' '; echo
  else
    echo "(none)"
  fi
  printf "  budget      \$%s today / \$%s cap\n" "$(spent_today)" "$(budget_today)"
  printf "  smoke       "
  local resp
  resp="$(curl -sS -m 15 -X POST "$ANTHROPIC_BASE_URL/v1/messages" \
    -H "x-api-key: $ANTHROPIC_AUTH_TOKEN" \
    -H "anthropic-version: 2023-06-01" \
    -H "content-type: application/json" \
    -d '{"model":"deepseek-chat","max_tokens":8,"messages":[{"role":"user","content":"ok"}]}' 2>/dev/null || true)"
  if echo "$resp" | grep -q '"role":"assistant"'; then
    printf "${C_OK}✓ ok${C_RST}\n"
  else
    printf "${C_ERR}✗ failed${C_RST}\n"
    echo "$resp" | head -2
    return 1
  fi
}

cmd_skills_list() {
  local sk_dir="$HOME/.claude/skills"
  printf "${C_BOLD}skills installed:${C_RST}  ${C_DIM}(%s)${C_RST}\n" "$sk_dir"
  for s in "$sk_dir"/*/; do
    [[ -d "$s" ]] || continue
    local name; name="$(basename "$s")"
    local desc=""
    [[ -f "$s/SKILL.md" ]] && desc="$(awk '/^description:/{sub(/^description: */,""); print; exit}' "$s/SKILL.md" | cut -c1-70)"
    printf "  %b·%b %-40s ${C_DIM}%s${C_RST}\n" "$C_BLUE" "$C_RST" "$name" "$desc"
  done
}

cmd_skills_add() {
  local name="$1"
  [[ -z "$name" ]] && { echo "usage: whalecode skills add <name>" >&2; exit 1; }
  local cache="$WC_HOME/cache/superpowers"
  if [[ ! -d "$cache" ]]; then
    git clone --depth 1 --quiet https://github.com/obra/superpowers.git "$cache"
  else
    (cd "$cache" && git pull --quiet 2>/dev/null || true)
  fi
  local src="$cache/skills/$name"
  if [[ -d "$src" ]]; then
    rm -rf "$HOME/.claude/skills/superpowers-$name"
    cp -r "$src" "$HOME/.claude/skills/superpowers-$name"
    printf "${C_OK}✓${C_RST} installed superpowers-%s\n" "$name"
  else
    printf "${C_ERR}✗${C_RST} skill not found upstream: %s\n" "$name" >&2
    printf "  available: " >&2
    ls "$cache/skills" 2>/dev/null | tr '\n' ' ' >&2; echo >&2
    exit 1
  fi
}

cmd_budget() {
  local sub="${1:-}"
  if [[ "$sub" == "set" ]]; then
    [[ -z "${2:-}" ]] && { echo "usage: whalecode budget set <usd>" >&2; exit 1; }
    echo "$2" > "$BUDGET_FILE"
    printf "${C_OK}✓${C_RST} daily cap set to \$%s\n" "$2"
  else
    printf "  today  \$%s\n" "$(spent_today)"
    printf "  cap    \$%s ${C_DIM}(whalecode budget set <usd> to change)${C_RST}\n" "$(budget_today)"
  fi
}

cmd_init() {
  local dir="${1:-/tmp/whalecode-demo}"
  mkdir -p "$dir"
  cd "$dir"
  cat > demo.py <<'PY'
def fizz(n):
    out = []
    for i in range(1, n+1):
        if i % 3 == 0 and i % 5 == 0: out.append("FizzBuzz")
        elif i % 3 == 0: out.append("Fizz")
        else: out.append(str(i))
    return out

if __name__ == "__main__":
    print(fizz(15))
PY
  printf "${C_BOLD}🐋 whalecode init${C_RST}\n"
  printf "  scratch dir: %s\n" "$dir"
  printf "  demo file:   demo.py (FizzBuzz with a missing-Buzz bug)\n"
  printf "  before:      "
  python3 demo.py
  printf "\n  ${C_DIM}calling whalecode to fix it...${C_RST}\n\n"
  WC_QUIET=1 "$0" -p --permission-mode bypassPermissions \
    "demo.py prints FizzBuzz but is missing the 'Buzz' branch (multiples of 5 not divisible by 3). Read it, fix it, run python3 demo.py to verify, then reply with one short sentence."
  printf "\n  after:       "
  python3 demo.py
  printf "\n  ${C_OK}✓ first run done${C_RST} — try ${C_BOLD}whalecode \"...\"${C_RST} on your own code.\n"
}

# ---- main dispatcher ----
case "${1:-}" in
  doctor)        shift; cmd_doctor "$@"; exit ;;
  init)          shift; cmd_init "$@"; exit ;;
  skills)
    shift
    case "${1:-list}" in
      list|"")          cmd_skills_list ;;
      add)              shift; cmd_skills_add "$@" ;;
      *) echo "usage: whalecode skills [list|add NAME]" >&2; exit 1 ;;
    esac
    exit ;;
  budget)        shift; cmd_budget "$@"; exit ;;
  --about)       cmd_about; exit ;;
  --version)     echo "whalecode $WC_VERSION (claude $(claude --version 2>/dev/null | awk '{print $1}'))"; exit ;;
esac

# everything else → claude-code with env, with cost wrapping when -p mode
HAS_PRINT=0
HAS_PERM=0
for a in "$@"; do
  [[ "$a" == "-p" || "$a" == "--print" ]] && HAS_PRINT=1
  [[ "$a" == "--permission-mode" || "$a" == "--dangerously-skip-permissions" || "$a" == "--allow-dangerously-skip-permissions" ]] && HAS_PERM=1
done

# Inject default permission mode (configurable; defaults to bypassPermissions for the
# "无脑" experience). Override by passing --permission-mode explicitly.
if [[ $HAS_PERM -eq 0 ]]; then
  set -- --permission-mode "${WC_DEFAULT_PERMISSION_MODE:-bypassPermissions}" "$@"
fi

# budget preflight (only block on print mode; interactive uses claude's own /budget)
if [[ $HAS_PRINT -eq 1 ]]; then
  pf="$(preflight_budget)"
  state="${pf%%::*}"
  rest="${pf#*::}"; sp="${rest%%::*}"; cap="${rest##*::}"
  case "$state" in
    BLOCK)
      printf "${C_ERR}🐋 budget exceeded${C_RST}: today \$%s ≥ cap \$%s\n" "$sp" "$cap" >&2
      printf "  raise: ${C_BOLD}whalecode budget set $(python3 -c "print(round(float('$cap')*2,2))")${C_RST}\n" >&2
      exit 2 ;;
    WARN)
      [[ -z "${WC_QUIET:-}" ]] && \
        printf "${C_WARN}🐋 ${C_DIM}\$%s / \$%s used today${C_RST}\n" "$sp" "$cap" >&2 ;;
  esac
fi

# pass-through; in -p mode, intercept JSON to render cost footer
if [[ $HAS_PRINT -eq 1 ]]; then
  # force json output if user hasn't already specified a format
  HAS_FORMAT=0
  for a in "$@"; do [[ "$a" == --output-format ]] && HAS_FORMAT=1; done
  if [[ $HAS_FORMAT -eq 0 ]]; then
    out_json="$(claude --output-format json "$@" </dev/null 2>&1)"
    rc=$?
    # parse + render
    python3 - "$out_json" <<'PY'
import json, sys
raw = sys.argv[1]
try:
    d = json.loads(raw)
except Exception:
    print(raw); sys.exit(0)
result = d.get("result") or ""
print(result)
cost = d.get("total_cost_usd", 0) or 0
turns = d.get("num_turns", 0)
u = d.get("usage") or {}
ip = int(u.get("input_tokens") or 0)
op = int(u.get("output_tokens") or 0)
cr = int(u.get("cache_read_input_tokens") or 0)
total_in = cr + ip
hit = (cr/total_in*100) if total_in else 0
import os
print()
print(f"  \033[2m🐋 ${cost:.3f} · {hit:.0f}% cached · {turns} turns · in {total_in/1000:.1f}k / out {op/1000:.1f}k\033[0m")
PY
    # log usage
    log_cost="$(echo "$out_json" | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); print(d.get('total_cost_usd',0))" 2>/dev/null || echo 0)"
    log_turns="$(echo "$out_json" | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); print(d.get('num_turns',0))" 2>/dev/null || echo 0)"
    log_model="${ANTHROPIC_MODEL:-unknown}"
    log_usage "$log_cost" "$log_turns" "$log_model"
    exit $rc
  fi
fi

# default: just exec claude
exec claude "$@"
