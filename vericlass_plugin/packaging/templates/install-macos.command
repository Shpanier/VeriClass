#!/usr/bin/env bash
# VeriClass — exam client installer (macOS).
# Double-click this file. It installs the VeriClass plugin into your JetBrains IDE
# (CLion or PyCharm, per exam.conf), points it at your instructor's backend, and
# launches the IDE into the exam. No admin rights.
set -euo pipefail

cd "$(dirname "$0")"
PKG_DIR="$(pwd)"

echo "=============================================="
echo "  VeriClass — Exam Client Installer (macOS)"
echo "=============================================="
echo

# --- read exam.conf (KEY=VALUE; we parse, never `source`, untrusted text) -----
conf() {
  local key="$1" default="${2:-}"
  local line
  line=$(grep -E "^[[:space:]]*${key}[[:space:]]*=" exam.conf 2>/dev/null | head -1 || true)
  if [[ -z "$line" ]]; then printf '%s' "$default"; return; fi
  printf '%s' "${line#*=}" | sed -E 's/^[[:space:]]+//; s/[[:space:]]+$//'
}

BACKEND_URL="$(conf BACKEND_URL 'http://127.0.0.1:8000')"
PROJECT_DIR="$(conf PROJECT_DIR '')"
DEV_LOGIN_CODE="$(conf DEV_LOGIN_CODE '')"
IDE_PRODUCT="$(conf IDE_PRODUCT 'CLion')"
PLUGIN_ZIP="$PKG_DIR/plugin/vericlass-exam-plugin.zip"

# Candidate macOS app names for the target IDE — Community/Professional/Toolbox
# installs use different bundle names, so try them in order.
case "$IDE_PRODUCT" in
  PyCharm) APP_NAMES=("PyCharm" "PyCharm CE" "PyCharm Community Edition") ;;
  *)       APP_NAMES=("$IDE_PRODUCT") ;;
esac

echo "Backend:  $BACKEND_URL"
[[ -n "$PROJECT_DIR" ]] && echo "Project:  $PROJECT_DIR"
echo

if [[ ! -f "$PLUGIN_ZIP" ]]; then
  echo "✖ Missing $PLUGIN_ZIP — is this the full package folder?" >&2
  read -r -p "Press Enter to close…" _ ; exit 1
fi

# --- locate the newest IDE config directory ----------------------------------
# The product-folder prefix is CLion* or PyCharm* (which also matches PyCharmCE*).
shopt -s nullglob
CONFIG_DIRS=("$HOME/Library/Application Support/JetBrains/"${IDE_PRODUCT}*)
shopt -u nullglob
if (( ${#CONFIG_DIRS[@]} == 0 )); then
  echo "✖ Couldn't find a $IDE_PRODUCT config folder." >&2
  echo "  Install $IDE_PRODUCT and launch it once, then run this installer again." >&2
  read -r -p "Press Enter to close…" _ ; exit 1
fi
CONFIG_DIR="$(printf '%s\n' "${CONFIG_DIRS[@]}" | sort -V | tail -1)"
echo "$IDE_PRODUCT config: $CONFIG_DIR"

# --- close the IDE so it reloads the plugin on next launch -------------------
for app in "${APP_NAMES[@]}"; do
  osascript -e "tell application \"$app\" to quit" >/dev/null 2>&1 || true
done
sleep 2

# --- install the plugin (extract into the plugins dir) -----------------------
PLUGINS_DIR="$CONFIG_DIR/plugins"
mkdir -p "$PLUGINS_DIR"
TOP="$(unzip -Z1 "$PLUGIN_ZIP" | head -1 | cut -d/ -f1)"
[[ -n "$TOP" ]] && rm -rf "$PLUGINS_DIR/${TOP:?}"
unzip -oq "$PLUGIN_ZIP" -d "$PLUGINS_DIR"
echo "✔ Plugin installed."

# --- preset the backend URL (application-level plugin settings) --------------
xml_escape() { printf '%s' "$1" | sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g' -e 's/"/\&quot;/g'; }
OPTIONS_DIR="$CONFIG_DIR/options"
mkdir -p "$OPTIONS_DIR"
cat > "$OPTIONS_DIR/vericlass.xml" <<XML
<application>
  <component name="VeriClassSettings">
    <option name="backendUrl" value="$(xml_escape "$BACKEND_URL")" />
    <option name="devLoginCode" value="$(xml_escape "$DEV_LOGIN_CODE")" />
  </component>
</application>
XML
echo "✔ Backend URL configured."

# --- launch the IDE ----------------------------------------------------------
echo
echo "Launching $IDE_PRODUCT…"
for app in "${APP_NAMES[@]}"; do
  if [[ -n "$PROJECT_DIR" ]]; then
    open -a "$app" "$PROJECT_DIR" 2>/dev/null && break
  fi
  open -a "$app" 2>/dev/null && break
done

cat <<DONE

✔ Done.
  • Open the "VeriClass" tool window on the right (it should appear automatically).
  • Log in with the code your instructor gave you.
  • The exam runs in full screen. If you leave $IDE_PRODUCT, your instructor is notified.

הותקן בהצלחה. פתחו את חלון "VeriClass" מימין, התחברו עם הקוד שקיבלתם,
ועבדו אך ורק בתוך $IDE_PRODUCT. יציאה מהחלון תדווח למרצה.
DONE
# `|| true`: when run without a TTY (EOF on stdin) read returns non-zero, which
# under `set -e` would make a successful install exit 1. Don't let it.
read -r -p "Press Enter to close…" _ || true
