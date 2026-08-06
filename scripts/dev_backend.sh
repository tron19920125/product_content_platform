#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PCP_DATA_ROOT="${PCP_DATA_ROOT:-$PROJECT_ROOT/data}"

cd "$PROJECT_ROOT"
exec .venv/bin/python -m uvicorn product_content_platform.api.app:app \
  --host 127.0.0.1 \
  --port "${PCP_BACKEND_PORT:-8000}" \
  --reload
