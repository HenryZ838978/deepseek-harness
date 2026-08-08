#!/usr/bin/env bash
# Build a user-installable offline release bundle for deepseek-harness.
#
# Produces:
#   release/deepseek-harness-<version>/
#     python/     wheel + sdist for core and cli
#     npm/        @deepseek-harness/mcp tarball
#     skill/      Anthropic Skill drop-in tree
#     INSTALL.md  install instructions
#     SHA256SUMS  checksums
#   release/deepseek-harness-<version>.tar.gz
#
# Usage:
#   ./scripts/package_release.sh
#   ./scripts/package_release.sh --skip-build   # reuse existing package dist/
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PYTHON="${PYTHON:-}"
if [[ -z "$PYTHON" ]]; then
  if command -v python3 >/dev/null 2>&1; then
    PYTHON=python3
  elif command -v python >/dev/null 2>&1; then
    PYTHON=python
  else
    echo "error: python3/python not found" >&2
    exit 1
  fi
fi

VERSION="$("$PYTHON" - <<'PY'
import tomllib
from pathlib import Path
data = tomllib.loads(Path("packages/core/pyproject.toml").read_text())
print(data["project"]["version"])
PY
)"

SKIP_BUILD=0
for arg in "$@"; do
  case "$arg" in
    --skip-build) SKIP_BUILD=1 ;;
    -h|--help)
      sed -n '2,16p' "$0"
      exit 0
      ;;
    *)
      echo "unknown argument: $arg" >&2
      exit 2
      ;;
  esac
done

BUNDLE_NAME="deepseek-harness-${VERSION}"
OUT_DIR="$ROOT/release/${BUNDLE_NAME}"
ARCHIVE="$ROOT/release/${BUNDLE_NAME}.tar.gz"

echo "==> packaging ${BUNDLE_NAME}"

if [[ "$SKIP_BUILD" -eq 0 ]]; then
  echo "==> building Python packages"
  ( cd packages/core && rm -rf dist build *.egg-info && "$PYTHON" -m build )
  ( cd packages/cli  && rm -rf dist build *.egg-info && "$PYTHON" -m build )

  echo "==> building MCP package"
  ( cd packages/mcp && npm install --no-fund --no-audit && npm run build )
  ( cd packages/mcp && rm -f ./*.tgz && npm pack >/dev/null )
fi

# Sanity: expected artifacts must exist
shopt -s nullglob
CORE_WHEELS=(packages/core/dist/deepseek_harness-"${VERSION}"-*.whl)
CLI_WHEELS=(packages/cli/dist/deepseek_harness_cli-"${VERSION}"-*.whl)
MCP_TGZ=(packages/mcp/deepseek-harness-mcp-"${VERSION}".tgz)
if [[ ${#CORE_WHEELS[@]} -eq 0 || ${#CLI_WHEELS[@]} -eq 0 || ${#MCP_TGZ[@]} -eq 0 ]]; then
  echo "error: missing build artifacts; run without --skip-build" >&2
  exit 1
fi
shopt -u nullglob

echo "==> assembling bundle at release/${BUNDLE_NAME}"
rm -rf "$OUT_DIR"
mkdir -p "$OUT_DIR"/{python,npm,skill}

cp -a packages/core/dist/. "$OUT_DIR/python/"
cp -a packages/cli/dist/.  "$OUT_DIR/python/"
cp -a "${MCP_TGZ[0]}" "$OUT_DIR/npm/"
cp -a packages/skill/. "$OUT_DIR/skill/"
# drop local caches if any slipped in
rm -rf "$OUT_DIR/skill/**/__pycache__" "$OUT_DIR/skill/**/.DS_Store" 2>/dev/null || true
find "$OUT_DIR/skill" -type d -name '__pycache__' -prune -exec rm -rf {} + 2>/dev/null || true

cp LICENSE "$OUT_DIR/"
cp CHANGELOG.md "$OUT_DIR/"
cp README.md "$OUT_DIR/README.md"

cat > "$OUT_DIR/INSTALL.md" <<EOF
# deepseek-harness ${VERSION} — offline install

This bundle contains every published form of the harness so you can install
without waiting on a registry mirror.

## Prerequisites

- Python ≥ 3.9 (\`pip\`)
- Node.js ≥ 18 (\`npm\` / \`npx\`) — only required for the MCP server
- \`DEEPSEEK_API_KEY\` for live API calls

## 1. Python library + CLI

\`\`\`bash
# from this directory
python3 -m pip install --upgrade pip
python3 -m pip install ./python/deepseek_harness-${VERSION}-py3-none-any.whl
python3 -m pip install ./python/deepseek_harness_cli-${VERSION}-py3-none-any.whl

# verify
dsh version          # expect ${VERSION}
# optional live check (needs DEEPSEEK_API_KEY):
# dsh doctor
\`\`\`

Import in code:

\`\`\`python
from deepseek_harness import DeepSeekHarness
client = DeepSeekHarness(disable_thinking_by_default=True)
\`\`\`

## 2. MCP server (Claude Desktop / Cursor / Cline / …)

\`\`\`bash
# one-shot from this directory (installs deps into an npx cache)
npx -y ./npm/deepseek-harness-mcp-${VERSION}.tgz
\`\`\`

Client config example:

\`\`\`json
{
  "mcpServers": {
    "deepseek-harness": {
      "command": "npx",
      "args": ["-y", "/absolute/path/to/npm/deepseek-harness-mcp-${VERSION}.tgz"],
      "env": { "DEEPSEEK_API_KEY": "sk-..." }
    }
  }
}
\`\`\`

Or publish/install from the registry after uploading the same tarball:

\`\`\`bash
npm install -g ./npm/deepseek-harness-mcp-${VERSION}.tgz
\`\`\`

## 3. Anthropic Skill (Claude Code)

\`\`\`bash
mkdir -p ~/.claude/skills
cp -R ./skill ~/.claude/skills/deepseek-harness
\`\`\`

Zero-dependency snippet (no install):

\`\`\`bash
cp ./skill/scripts/safe_init.py ./safe_init.py
python3 -c 'from safe_init import safe_deepseek_call; print("ok")'
\`\`\`

## 4. Registry install (when online)

If you do not need the offline artifacts:

\`\`\`bash
pip install deepseek-harness deepseek-harness-cli
npx -y @deepseek-harness/mcp
\`\`\`

## Checksums

See \`SHA256SUMS\` in this directory.
EOF

(
  cd "$OUT_DIR"
  # portable checksum: sha256sum on Linux, shasum on macOS
  if command -v sha256sum >/dev/null 2>&1; then
    find python npm skill -type f ! -name '*.map' -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS
  else
    find python npm skill -type f ! -name '*.map' -print0 | sort -z | xargs -0 shasum -a 256 > SHA256SUMS
  fi
)

echo "==> writing archive ${ARCHIVE}"
mkdir -p "$ROOT/release"
rm -f "$ARCHIVE"
tar -C "$ROOT/release" -czf "$ARCHIVE" "$BUNDLE_NAME"

# Also emit a MANIFEST for automation / release notes
MANIFEST="$ROOT/release/${BUNDLE_NAME}.manifest.txt"
{
  echo "name=${BUNDLE_NAME}"
  echo "version=${VERSION}"
  echo "archive=$(basename "$ARCHIVE")"
  echo "archive_bytes=$(wc -c < "$ARCHIVE" | tr -d ' ')"
  if command -v sha256sum >/dev/null 2>&1; then
    echo "archive_sha256=$(sha256sum "$ARCHIVE" | awk '{print $1}')"
  else
    echo "archive_sha256=$(shasum -a 256 "$ARCHIVE" | awk '{print $1}')"
  fi
  echo "contents:"
  find "$OUT_DIR" -type f | sed "s|^$OUT_DIR/|  |" | sort
} > "$MANIFEST"

echo
echo "OK  bundle : $OUT_DIR"
echo "OK  archive: $ARCHIVE"
echo "OK  manifest: $MANIFEST"
ls -lh "$ARCHIVE"
cat "$MANIFEST"
