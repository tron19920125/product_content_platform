#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CODEX_PYTHON="${HOME}/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"
CODEX_NODE_BIN="${HOME}/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin"
CODEX_PNPM="${HOME}/.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/fallback/pnpm"

if ! command -v node >/dev/null 2>&1 && [[ -x "$CODEX_NODE_BIN/node" ]]; then
  export PATH="$CODEX_NODE_BIN:$PATH"
fi

if [[ -n "${PCP_PYTHON:-}" ]]; then
  PYTHON_BIN="$PCP_PYTHON"
elif command -v python3.12 >/dev/null 2>&1; then
  PYTHON_BIN="python3.12"
elif [[ -x "$CODEX_PYTHON" ]]; then
  PYTHON_BIN="$CODEX_PYTHON"
else
  PYTHON_BIN="python3"
fi

cd "$PROJECT_ROOT"
"$PYTHON_BIN" -c 'import sys; assert sys.version_info >= (3, 11), "Python 3.11+ is required"'
"$PYTHON_BIN" -m venv .venv
.venv/bin/python -m pip install -e 'backend[dev]'

cd frontend
if command -v pnpm >/dev/null 2>&1; then
  pnpm install
elif [[ -x "$CODEX_PNPM" ]]; then
  "$CODEX_PNPM" install
else
  corepack pnpm install
fi

echo "Local dependencies are ready."
