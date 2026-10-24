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

# Every window we open gets its tab's custom title prefixed with this tag, so a
# later run can find and close the previous run's windows (and only those).
WIN_TAG="VERICLASS-DEV"

kill_port() {
  local port=$1
  local pids
  # Only the process LISTENING on the port: a client connected to it (the ngrok
  # tunnel forwarding to the backend) must survive the restart.
  pids=$(lsof -ti tcp:"$port" -sTCP:LISTEN 2>/dev/null || true)
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

echo "==> closing Terminal windows from a previous run"
# The processes are dead now (killed above), so the windows just hold an idle
# shell — closing them won't prompt. We match on the custom title we stamped
# each tab with, so only OUR windows close, never the one you launched from.
osascript <<EOF 2>/dev/null || true
tell application "Terminal"
  repeat with w in (every window)
    try
      repeat with t in (tabs of w)
        if custom title of t starts with "$WIN_TAG" then
          close w saving no
          exit repeat
        end if
      end repeat
    end try
  end repeat
end tell
EOF

BACKEND_CMD="cd '$PROJECT_ROOT' && source .venv/bin/activate && uvicorn backend.main:app --reload --port $BACKEND_PORT"
STUDENT_CMD="cd '$PROJECT_ROOT' && source .venv/bin/activate && BACKEND_URL=http://127.0.0.1:$BACKEND_PORT chainlit run student_app/app.py --port $STUDENT_PORT"
DASH_CMD="cd '$PROJECT_ROOT/dashboard' && npm run dev"

echo "==> launching three Terminal.app windows"

# Each `do script` with no target opens a NEW window. We deliberately avoid the
# old `System Events` + ⌘T tab trick: sending keystrokes needs Accessibility
# permission and fails with "osascript is not allowed to send keystrokes".
# Opening windows needs only Automation (Terminal controlling Terminal), which
# macOS prompts for once on first run — just click OK.
# Stamp each new tab's custom title with WIN_TAG so the next run can find and
# close exactly these windows.
osascript <<EOF
tell application "Terminal"
  activate
  set custom title of (do script "echo '--- backend (uvicorn :$BACKEND_PORT) ---'; $BACKEND_CMD") to "$WIN_TAG backend :$BACKEND_PORT"
  set custom title of (do script "echo '--- student app (chainlit :$STUDENT_PORT) ---'; $STUDENT_CMD") to "$WIN_TAG student :$STUDENT_PORT"
  set custom title of (do script "echo '--- dashboard (vite :$DASH_PORT) ---'; $DASH_CMD") to "$WIN_TAG dashboard :$DASH_PORT"
end tell
EOF

# Open the teacher dashboard in the default browser once the stack is actually
# ready. We wait for TWO things (up to ~30s), not just the dashboard port:
#   1. the backend RESPONDS to HTTP on :$BACKEND_PORT — a bound port isn't
#      enough, uvicorn binds before the app finishes importing, and the page
#      auto-logs-in the instant it loads, so an early request hits a dead
#      backend ("Can't reach the lab server").
#   2. Vite is serving on :$DASH_PORT.
# Runs in the background so the script returns right away.
DASH_URL="http://localhost:$DASH_PORT/"
(
  backend_ready=""
  for _ in $(seq 1 60); do
    if [[ -z "$backend_ready" ]] && curl -s -o /dev/null "http://127.0.0.1:$BACKEND_PORT/"; then
      backend_ready=1
    fi
    if [[ -n "$backend_ready" ]] && lsof -ti tcp:"$DASH_PORT" >/dev/null 2>&1; then
      open "$DASH_URL"
      exit 0
    fi
    sleep 0.5
  done
  echo "  (stack didn't come up in time — open $DASH_URL manually)" >&2
) &

cat <<MSG

==> launched.
    backend     http://127.0.0.1:$BACKEND_PORT
    student app http://127.0.0.1:$STUDENT_PORT
    dashboard   http://127.0.0.1:$DASH_PORT  (opening in your browser…)

    Alternative student client: the CLion / PyCharm plugin (vericlass_plugin/).
    Behavior is set by STUDENT_CLIENT_MODE in .env (chat | ide).
    Run it with:  cd vericlass_plugin && ./gradlew :clion:runIde   (or :pycharm:runIde)
MSG
