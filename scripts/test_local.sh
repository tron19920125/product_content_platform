#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CODEX_NODE_BIN="${HOME}/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin"
CODEX_PNPM="${HOME}/.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/fallback/pnpm"

if ! command -v node >/dev/null 2>&1 && [[ -x "$CODEX_NODE_BIN/node" ]]; then
  export PATH="$CODEX_NODE_BIN:$PATH"
fi

cd "$PROJECT_ROOT"

.venv/bin/python -m unittest discover -s backend/tests -v

cd "$PROJECT_ROOT/frontend"
if command -v pnpm >/dev/null 2>&1; then
  pnpm run build
elif [[ -x "$CODEX_PNPM" ]]; then
  "$CODEX_PNPM" run build
else
  corepack pnpm run build
fi
