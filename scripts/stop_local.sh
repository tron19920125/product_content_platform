#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUN_ROOT="$PROJECT_ROOT/.run"

stop_tracked_process() {
  local name="$1" pid_file="$2" pid
  if [[ ! -f "$pid_file" ]]; then
    echo "$name is not tracked."
    return 0
  fi
  pid="$(tr -d '[:space:]' < "$pid_file")"
  if [[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" 2>/dev/null; then
    kill "$pid"
    for _ in $(seq 1 20); do
      kill -0 "$pid" 2>/dev/null || break
      sleep 0.1
    done
    if kill -0 "$pid" 2>/dev/null; then
      kill -9 "$pid"
    fi
    echo "Stopped $name (PID $pid)."
  else
    echo "$name was already stopped."
  fi
  rm -f "$pid_file"
}

stop_tracked_process "frontend" "$RUN_ROOT/frontend.pid"
stop_tracked_process "backend" "$RUN_ROOT/backend.pid"

