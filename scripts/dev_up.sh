#!/usr/bin/env bash
# Dev launcher: kill prior backend/student/dashboard processes, then open
# three new Terminal.app tabs and start each service.
set -euo pipefail

PROJECT_ROOT="$( cd "$( dirname "${BASH_SOURCE[0]}" )/.." && pwd )"

kill_port() {
  local port=$1
  local pids
  pids=$(lsof -ti tcp:"$port" 2>/dev/null || true)
  if [[ -n "$pids" ]]; then
    echo "  port $port: killing $pids"
    kill -9 $pids 2>/dev/null || true
  else
    echo "  port $port: free"
  fi
}

echo "==> killing previous processes"
kill_port 8000
kill_port 8001
kill_port 5173
pkill -f 'uvicorn backend.main' 2>/dev/null || true
pkill -f 'chainlit run student_app' 2>/dev/null || true
sleep 0.3

BACKEND_CMD="cd '$PROJECT_ROOT' && source .venv/bin/activate && uvicorn backend.main:app --reload --port 8000"
STUDENT_CMD="cd '$PROJECT_ROOT' && source .venv/bin/activate && chainlit run student_app/app.py --port 8001"
DASH_CMD="cd '$PROJECT_ROOT/dashboard' && npm run dev"

echo "==> launching three tabs in Terminal.app"

osascript <<EOF
tell application "Terminal"
  activate
  -- 'do script' with no target opens a brand-new window (tab 1).
  do script "echo '--- backend (uvicorn :8000) ---'; $BACKEND_CMD"
end tell
delay 0.5
-- Add tab 2 to that new window.
tell application "System Events" to keystroke "t" using {command down}
delay 0.3
tell application "Terminal" to do script "echo '--- student app (chainlit :8001) ---'; $STUDENT_CMD" in front window
delay 0.3
-- Add tab 3 to that new window.
tell application "System Events" to keystroke "t" using {command down}
delay 0.3
tell application "Terminal" to do script "echo '--- dashboard (vite :5173) ---'; $DASH_CMD" in front window
EOF

cat <<MSG

==> launched.
    backend     http://127.0.0.1:8000
    student app http://127.0.0.1:8001
    dashboard   http://127.0.0.1:5173
MSG
