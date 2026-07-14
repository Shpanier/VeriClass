#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────
#  publish.sh — build the plugin (JDK 21) and upload it to the backend so any
#  machine can install it over the always-on ngrok tunnel.
#
#  Run this on the BUILD machine. It bumps the version, builds, then POSTs the
#  zip to  <server>/api/plugin/publish  (teacher-authenticated).
#
#    ./publish.sh                       # build+publish the CLion plugin
#    ./publish.sh --product pycharm     # build+publish the PyCharm plugin instead
#    ./publish.sh --no-build            # upload the existing zip for that product
#    ./publish.sh https://my.server     # override the server URL
#
#  Only ONE product is "live" on the backend at a time (the endpoints store a
#  single latest zip); publish whichever product your current cohort uses.
#
#  Server URL resolution (first hit wins):
#    1) first non-flag argument
#    2) $OSLAB_SERVER
#    3) NGROK_DOMAIN from ../deploy/tunnel.conf
#  Teacher code:  $OSLAB_TEACHER_CODE, else you're prompted (input hidden).
# ─────────────────────────────────────────────────────────────────────────
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

BUILD=1
SERVER=""
PRODUCT="clion"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-build)  BUILD=0; shift ;;
    --product)   PRODUCT="${2:?--product needs a value (clion|pycharm)}"; shift 2 ;;
    --product=*) PRODUCT="${1#*=}"; shift ;;
    http*://*)   SERVER="$1"; shift ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done
case "$PRODUCT" in
  clion|pycharm) ;;
  *) echo "✖ --product must be 'clion' or 'pycharm' (got '$PRODUCT')" >&2; exit 2 ;;
esac

# Resolve the server URL.
if [[ -z "$SERVER" ]]; then
  SERVER="${OSLAB_SERVER:-}"
fi
if [[ -z "$SERVER" && -f ../deploy/tunnel.conf ]]; then
  SERVER="$(sed -n 's/^NGROK_DOMAIN=//p' ../deploy/tunnel.conf | tr -d '[:space:]')"
fi
[[ -n "$SERVER" ]] || { echo "✖ No server URL. Pass one, set OSLAB_SERVER, or set NGROK_DOMAIN in deploy/tunnel.conf." >&2; exit 1; }
SERVER="${SERVER%/}"  # strip trailing slash

# Build (bump version + gradle) unless told not to.
if [[ "$BUILD" -eq 1 ]]; then
  ./reinstall.sh --product "$PRODUCT" >/dev/null 2>&1 &  # bumps + builds; run it and wait
  wait $! || { echo "✖ Build failed. Run ./reinstall.sh --product $PRODUCT directly to see the error." >&2; exit 1; }
fi

VERSION="$(sed -n 's/^pluginVersion=//p' gradle.properties | tr -d '[:space:]')"
ZIP="$(ls -t "$PRODUCT/build/distributions/oslab-$PRODUCT-plugin-"*.zip 2>/dev/null | head -1)"
[[ -n "$ZIP" ]] || { echo "✖ No zip in $PRODUCT/build/distributions/. Build first (drop --no-build)." >&2; exit 1; }
echo "==> publishing $ZIP (version $VERSION, product $PRODUCT) → $SERVER"

# Teacher code → token.
CODE="${OSLAB_TEACHER_CODE:-}"
if [[ -z "$CODE" ]]; then
  read -r -s -p "Teacher login code: " CODE; echo
fi
NG_HDR='ngrok-skip-browser-warning: true'   # skip ngrok-free's interstitial page
TOKEN="$(curl -s -X POST "$SERVER/api/login" \
  -H 'Content-Type: application/json' -H "$NG_HDR" \
  -d "{\"code\":\"$CODE\"}" | sed -n 's/.*"token":"\([^"]*\)".*/\1/p')"
[[ -n "$TOKEN" ]] || { echo "✖ Login failed — check the teacher code and server URL." >&2; exit 1; }

RESP="$(curl -s -X POST \
  "$SERVER/api/plugin/publish?version=$VERSION&product=$PRODUCT&filename=$(basename "$ZIP")" \
  -H "Authorization: Bearer $TOKEN" -H "$NG_HDR" \
  --data-binary @"$ZIP")"
echo "$RESP" | grep -q '"ok":true' \
  && echo "==> ✓ published ($PRODUCT). Students can now run:  scripts/update_plugin.sh --product $PRODUCT" \
  || { echo "✖ Publish failed: $RESP" >&2; exit 1; }
