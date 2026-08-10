#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUN_ROOT="$PROJECT_ROOT/.run"
LOG_ROOT="$PROJECT_ROOT/data/logs"
ENV_FILE="$PROJECT_ROOT/.env"

load_safe_dotenv() {
  local line line_number=0 name value first last
  [[ -f "$ENV_FILE" ]] || return 0
  while IFS= read -r line || [[ -n "$line" ]]; do
    line_number=$((line_number + 1))
    line="${line%$'\r'}"
    [[ "$line" =~ ^[[:space:]]*$ ]] && continue
    [[ "$line" =~ ^[[:space:]]*# ]] && continue
    if [[ ! "$line" =~ ^[A-Za-z_][A-Za-z0-9_]*= ]]; then
      echo "Invalid .env entry at line $line_number. Expected KEY=VALUE." >&2
      return 1
    fi
    name="${line%%=*}"
    value="${line#*=}"
    if (( ${#value} >= 2 )); then
      first="${value:0:1}"
      last="${value: -1}"
      if [[ ( "$first" == '"' && "$last" == '"' ) || ( "$first" == "'" && "$last" == "'" ) ]]; then
        value="${value:1:${#value}-2}"
      fi
    fi
    export "$name=$value"
  done < "$ENV_FILE"
}

is_running() {
  local pid_file="$1" pid
  [[ -f "$pid_file" ]] || return 1
  pid="$(tr -d '[:space:]' < "$pid_file")"
  [[ "$pid" =~ ^[0-9]+$ ]] || return 1
  kill -0 "$pid" 2>/dev/null
}

wait_http_ready() {
  local url="$1" attempt
  for attempt in $(seq 1 40); do
    if curl --silent --fail --max-time 2 "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.5
  done
  return 1
}

load_safe_dotenv
export PCP_DATA_ROOT="${PCP_DATA_ROOT:-$PROJECT_ROOT/data}"
PCP_HOST="${PCP_HOST:-127.0.0.1}"
PCP_BACKEND_PORT="${PCP_BACKEND_PORT:-8000}"
PCP_FRONTEND_PORT="${PCP_FRONTEND_PORT:-5173}"
export VITE_API_BASE_URL="${VITE_API_BASE_URL:-http://${PCP_HOST}:${PCP_BACKEND_PORT}/api}"

PYTHON_BIN="$PROJECT_ROOT/.venv/bin/python"
VITE_ENTRY="$PROJECT_ROOT/frontend/node_modules/vite/bin/vite.js"
if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Python environment is missing. Run ./scripts/bootstrap_local.sh first." >&2
  exit 1
fi
if ! command -v node >/dev/null 2>&1; then
  echo "Node.js is missing from PATH. Install Node.js 20+ first." >&2
  exit 1
fi
if [[ ! -f "$VITE_ENTRY" ]]; then
  echo "Frontend dependencies are missing. Run pnpm install in frontend first." >&2
  exit 1
fi

echo "Configuration ready: generation=${PCP_GENERATION_MODE:-local}, qa=${PCP_QA_MODE:-local}, backend=$PCP_BACKEND_PORT, frontend=$PCP_FRONTEND_PORT"
if [[ "${1:-}" == "--check" ]]; then
  exit 0
fi

mkdir -p "$RUN_ROOT" "$LOG_ROOT"
BACKEND_PID_FILE="$RUN_ROOT/backend.pid"
FRONTEND_PID_FILE="$RUN_ROOT/frontend.pid"
if is_running "$BACKEND_PID_FILE" || is_running "$FRONTEND_PID_FILE"; then
  echo "Tracked services are already running. Run ./scripts/stop_local.sh first." >&2
  exit 1
fi

BACKEND_LOG="$LOG_ROOT/backend.log"
FRONTEND_LOG="$LOG_ROOT/frontend.log"
backend_pid=""
frontend_pid=""
cleanup_failed_start() {
  [[ -n "$frontend_pid" ]] && kill "$frontend_pid" 2>/dev/null || true
  [[ -n "$backend_pid" ]] && kill "$backend_pid" 2>/dev/null || true
  rm -f "$BACKEND_PID_FILE" "$FRONTEND_PID_FILE"
}
trap cleanup_failed_start ERR INT TERM

cd "$PROJECT_ROOT"
nohup "$PYTHON_BIN" -m uvicorn product_content_platform.api.app:app \
  --host "$PCP_HOST" --port "$PCP_BACKEND_PORT" >"$BACKEND_LOG" 2>&1 &
backend_pid=$!
printf '%s\n' "$backend_pid" > "$BACKEND_PID_FILE"

cd "$PROJECT_ROOT/frontend"
nohup node "$VITE_ENTRY" --host "$PCP_HOST" --port "$PCP_FRONTEND_PORT" >"$FRONTEND_LOG" 2>&1 &
frontend_pid=$!
printf '%s\n' "$frontend_pid" > "$FRONTEND_PID_FILE"

wait_http_ready "http://${PCP_HOST}:${PCP_BACKEND_PORT}/api/health" || {
  echo "Backend health check timed out. See $BACKEND_LOG." >&2
  false
}
wait_http_ready "http://${PCP_HOST}:${PCP_FRONTEND_PORT}/" || {
  echo "Frontend health check timed out. See $FRONTEND_LOG." >&2
  false
}
trap - ERR INT TERM

echo "Services are ready: http://${PCP_HOST}:${PCP_FRONTEND_PORT}/"
echo "API docs: http://${PCP_HOST}:${PCP_BACKEND_PORT}/docs"
echo "Logs: $LOG_ROOT"

