#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CODEX_NODE_BIN="${HOME}/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin"
CODEX_PNPM="${HOME}/.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/fallback/pnpm"

if ! command -v node >/dev/null 2>&1 && [[ -x "$CODEX_NODE_BIN/node" ]]; then
  export PATH="$CODEX_NODE_BIN:$PATH"
fi

cd "$PROJECT_ROOT/frontend"

if command -v pnpm >/dev/null 2>&1; then
  exec pnpm run dev
elif [[ -x "$CODEX_PNPM" ]]; then
  exec "$CODEX_PNPM" run dev
else
  exec corepack pnpm run dev
fi
