#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON_BIN="$PROJECT_ROOT/.venv/bin/python"
if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Python environment is missing. Run ./scripts/bootstrap_local.sh first." >&2
  exit 1
fi

# Do not source the old .env or inherit its data root/model startup behavior.
export PCP_STUDIO_DATA_ROOT="${PCP_STUDIO_DATA_ROOT:-$PROJECT_ROOT/data-refactor}"
export PYTHONPATH="$PROJECT_ROOT/backend/src${PYTHONPATH:+:$PYTHONPATH}"
cd "$PROJECT_ROOT"
exec "$PYTHON_BIN" -m product_content_platform.studio "$@"
