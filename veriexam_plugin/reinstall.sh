#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────
#  reinstall.sh — rebuild a plugin as a NEW version so the IDE treats the next
#  "Install Plugin from Disk…" as an upgrade (one restart, no uninstall).
#
#  Why: with a fixed version, installing a rebuilt zip over the same version
#  makes the IDE keep the OLD code. Bumping the patch version each build fixes it.
#  The version is shared by both plugins (one pluginVersion in gradle.properties).
#
#    ./reinstall.sh                       # build CLion plugin, bump patch (0.1.0 -> 0.1.1)
#    ./reinstall.sh --product pycharm     # build the PyCharm plugin instead
#    ./reinstall.sh 0.2.0                 # set an explicit version, then build
#    ./reinstall.sh --product pycharm 0.2.0
#
#  Requires JDK 21 (the plugin only compiles there). Run on your build machine.
# ─────────────────────────────────────────────────────────────────────────
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"
PROPS="gradle.properties"

PRODUCT="clion"
NEXT_EXPLICIT=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --product)   PRODUCT="${2:?--product needs a value (clion|pycharm)}"; shift 2 ;;
    --product=*) PRODUCT="${1#*=}"; shift ;;
    -h|--help)   grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    -*)          echo "✖ Unknown option: $1" >&2; exit 2 ;;
    *)           NEXT_EXPLICIT="$1"; shift ;;
  esac
done
case "$PRODUCT" in
  clion)   IDE_NAME="CLion" ;;
  pycharm) IDE_NAME="PyCharm" ;;
  *) echo "✖ --product must be 'clion' or 'pycharm' (got '$PRODUCT')" >&2; exit 2 ;;
esac
DIST="$PRODUCT/build/distributions"
ZIPGLOB="veriexam-$PRODUCT-plugin-*.zip"

current="$(sed -n 's/^pluginVersion=//p' "$PROPS" | tr -d '[:space:]')"
[[ -n "$current" ]] || { echo "✖ pluginVersion not found in $PROPS" >&2; exit 1; }

if [[ -n "$NEXT_EXPLICIT" ]]; then
  next="$NEXT_EXPLICIT"
else
  # Bump the last dotted number: 0.1.0 -> 0.1.1
  base="${current%.*}"; patch="${current##*.}"
  if [[ "$patch" =~ ^[0-9]+$ ]]; then
    next="${base}.$((patch + 1))"
  else
    echo "✖ Can't auto-bump '$current' — pass an explicit version, e.g. ./reinstall.sh 0.2.0" >&2
    exit 1
  fi
fi

echo "==> [$IDE_NAME] version $current -> $next"
# Portable in-place edit (macOS/BSD sed needs the '' arg).
sed -i '' "s/^pluginVersion=.*/pluginVersion=$next/" "$PROPS"

echo "==> building (./gradlew :$PRODUCT:buildPlugin)…"
./gradlew ":$PRODUCT:buildPlugin"

zip="$(ls -t $DIST/$ZIPGLOB 2>/dev/null | head -1)"
if [[ -z "$zip" ]]; then
  echo "✖ Build finished but no zip found under $DIST/" >&2
  exit 1
fi

echo
echo "==> built: $zip"
echo "   Install it in $IDE_NAME:  Settings → Plugins → ⚙ → Install Plugin from Disk…"
echo "   (a single restart applies the update — no uninstall needed)"
command -v open >/dev/null 2>&1 && open -R "$zip" || true
