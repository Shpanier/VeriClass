#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────
#  tunnel.sh — the control macro for exposing the VeriClass backend over the web.
#
#  Reads deploy/tunnel.conf and starts the chosen tunnel (ngrok / cloudflare).
#  Optionally starts the backend too. Keeps your laptop awake during the exam.
#
#    bash deploy/tunnel.sh                  # use PROVIDER from tunnel.conf
#    bash deploy/tunnel.sh ngrok            # override provider for this run
#    bash deploy/tunnel.sh cloudflare
#    bash deploy/tunnel.sh --with-backend   # also launch uvicorn in background
#    bash deploy/tunnel.sh -h               # help
#
#  Students never run this — it's teacher-side only.
# ─────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CONF="$SCRIPT_DIR/tunnel.conf"

# Homebrew installs ngrok/cloudflared into /usr/local/bin (Intel) or
# /opt/homebrew/bin (Apple Silicon); some shells don't have these on PATH.
export PATH="$PATH:/opt/homebrew/bin:/usr/local/bin"

WITH_BACKEND=0
PROVIDER_OVERRIDE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --with-backend) WITH_BACKEND=1; shift ;;
    ngrok|cloudflare|cloudflare-quick) PROVIDER_OVERRIDE="$1"; shift ;;
    -h|--help) grep -E '^#( |$)' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown argument: $1  (try -h)" >&2; exit 2 ;;
  esac
done

[[ -f "$CONF" ]] || { echo "✖ Missing config: $CONF" >&2; exit 1; }
# shellcheck disable=SC1090
source "$CONF"
[[ -n "$PROVIDER_OVERRIDE" ]] && PROVIDER="$PROVIDER_OVERRIDE"
BACKEND_PORT="${BACKEND_PORT:-8000}"

say() { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m✖\033[0m %s\n' "$*" >&2; exit 1; }

need() {
  command -v "$1" >/dev/null 2>&1 || die "'$1' not found on PATH ($PATH).
   Install it (brew install $1) — see deploy/README-${2}.md"
}

# ── optionally start the backend ───────────────────────────────────────────
BACKEND_PID=""
cleanup() {
  [[ -n "$BACKEND_PID" ]] && kill "$BACKEND_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

backend_up() { lsof -ti "tcp:$BACKEND_PORT" >/dev/null 2>&1; }

if [[ "$WITH_BACKEND" -eq 1 ]]; then
  if backend_up; then
    say "Backend already running on :$BACKEND_PORT — not starting another."
  else
    say "Starting backend (uvicorn :$BACKEND_PORT) in the background…"
    ( cd "$PROJECT_ROOT" \
      && source .venv/bin/activate \
      && exec uvicorn backend.main:app --port "$BACKEND_PORT" ) \
      >"$PROJECT_ROOT/deploy/backend.log" 2>&1 &
    BACKEND_PID=$!
    sleep 2
    backend_up || die "Backend failed to start. Check deploy/backend.log"
  fi
else
  backend_up || die "Backend is not running on :$BACKEND_PORT. Start it first
   (bash scripts/dev_up.sh) or re-run with:  bash deploy/tunnel.sh --with-backend"
fi

# ── keep the laptop awake while the tunnel is up (macOS) ─────────────────────
if command -v caffeinate >/dev/null 2>&1; then
  caffeinate -dimsu -w $$ &  # dies when this script exits
  say "caffeinate on — laptop won't sleep while the tunnel runs."
fi

# ── start the chosen tunnel ──────────────────────────────────────────────────
case "$PROVIDER" in
  ngrok)
    need ngrok NGROK
    NGROK_DOMAIN="${NGROK_DOMAIN#https://}"; NGROK_DOMAIN="${NGROK_DOMAIN#http://}"
    NGROK_DOMAIN="${NGROK_DOMAIN%/}"
    [[ "$NGROK_DOMAIN" == CHANGEME* ]] && die "Set NGROK_DOMAIN in deploy/tunnel.conf first."
    say "ngrok → https://$NGROK_DOMAIN  (forwarding to :$BACKEND_PORT)"
    say "Students' plugin must be packaged with: https://$NGROK_DOMAIN"
    exec ngrok http --url="$NGROK_DOMAIN" "$BACKEND_PORT"
    ;;
  cloudflare)
    need cloudflared CLOUDFLARE
    say "Cloudflare named tunnel '$CF_TUNNEL_NAME' → :$BACKEND_PORT"
    say "Students' plugin must be packaged with your routed hostname (https://…)."
    exec cloudflared tunnel run --url "http://localhost:$BACKEND_PORT" "$CF_TUNNEL_NAME"
    ;;
  cloudflare-quick)
    need cloudflared CLOUDFLARE
    say "Cloudflare QUICK tunnel — a RANDOM https URL prints below."
    say "⚠ This URL changes every run. You must re-stamp exam.conf + re-zip each time."
    exec cloudflared tunnel --url "http://localhost:$BACKEND_PORT"
    ;;
  *)
    die "Unknown PROVIDER '$PROVIDER' in tunnel.conf (use ngrok | cloudflare | cloudflare-quick)"
    ;;
esac
