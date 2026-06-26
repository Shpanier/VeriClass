#!/usr/bin/env bash
# Dev launcher: kill prior backend/student/dashboard processes, then open
# three Terminal.app windows and start each service.
set -euo pipefail

# Do NOT run under sudo. The AppleScript below drives Terminal, and GUI
# automation permissions are granted per-user — as root they don't apply and
# you get "osascript is not allowed to send keystrokes / control Terminal".
# Killing your own dev ports never needs root either.
if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
  echo "✖ Don't run this with sudo. Re-run as:  ./dev_up.sh" >&2
  exit 1
fi

PROJECT_ROOT="$( cd "$( dirname "${BASH_SOURCE[0]}" )/.." && pwd )"

# Ports for the three dev services. Change them here and the rest follows.
BACKEND_PORT=8010
STUDENT_PORT=8011
DASH_PORT=5173

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
# Free the new ports AND the legacy 8000/8001, so switching ports never leaves
# an orphan holding the old one. Then also kill by process name — this catches a
# service that grabbed some other port after a crash, so "previously running
# sessions" are reliably gone before we start fresh.
for p in "$BACKEND_PORT" "$STUDENT_PORT" "$DASH_PORT" 8000 8001; do
  kill_port "$p"
done
pkill -f 'uvicorn backend.main' 2>/dev/null || true
pkill -f 'chainlit run student_app' 2>/dev/null || true
sleep 0.3

BACKEND_CMD="cd '$PROJECT_ROOT' && source .venv/bin/activate && uvicorn backend.main:app --reload --port $BACKEND_PORT"
STUDENT_CMD="cd '$PROJECT_ROOT' && source .venv/bin/activate && BACKEND_URL=http://127.0.0.1:$BACKEND_PORT chainlit run student_app/app.py --port $STUDENT_PORT"
DASH_CMD="cd '$PROJECT_ROOT/dashboard' && npm run dev"

echo "==> launching three Terminal.app windows"

# Each `do script` with no target opens a NEW window. We deliberately avoid the
# old `System Events` + ⌘T tab trick: sending keystrokes needs Accessibility
# permission and fails with "osascript is not allowed to send keystrokes".
# Opening windows needs only Automation (Terminal controlling Terminal), which
# macOS prompts for once on first run — just click OK.
osascript <<EOF
tell application "Terminal"
  activate
  do script "echo '--- backend (uvicorn :$BACKEND_PORT) ---'; $BACKEND_CMD"
  do script "echo '--- student app (chainlit :$STUDENT_PORT) ---'; $STUDENT_CMD"
  do script "echo '--- dashboard (vite :$DASH_PORT) ---'; $DASH_CMD"
end tell
EOF

cat <<MSG

==> launched.
    backend     http://127.0.0.1:$BACKEND_PORT
    student app http://127.0.0.1:$STUDENT_PORT
    dashboard   http://127.0.0.1:$DASH_PORT

    Alternative student client: the CLion plugin (clion_plugin/).
    Behavior is set by STUDENT_CLIENT_MODE in .env (chat | ide).
    Run it with:  cd clion_plugin && ./gradlew runIde
MSG
