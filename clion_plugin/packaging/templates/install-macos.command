#!/usr/bin/env bash
# OS Lab — exam client installer (macOS).
# Double-click this file. It installs the OS Lab plugin into CLion, points it at
# your instructor's backend, and launches CLion into the exam. No admin rights.
set -euo pipefail

cd "$(dirname "$0")"
PKG_DIR="$(pwd)"

echo "=============================================="
echo "  OS Lab — Exam Client Installer (macOS)"
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
PLUGIN_ZIP="$PKG_DIR/plugin/oslab-exam-plugin.zip"

echo "Backend:  $BACKEND_URL"
[[ -n "$PROJECT_DIR" ]] && echo "Project:  $PROJECT_DIR"
echo

if [[ ! -f "$PLUGIN_ZIP" ]]; then
  echo "✖ Missing $PLUGIN_ZIP — is this the full package folder?" >&2
  read -r -p "Press Enter to close…" _ ; exit 1
fi

# --- locate the newest CLion config directory --------------------------------
shopt -s nullglob
CONFIG_DIRS=("$HOME/Library/Application Support/JetBrains/"CLion*)
shopt -u nullglob
if (( ${#CONFIG_DIRS[@]} == 0 )); then
  echo "✖ Couldn't find a CLion config folder." >&2
  echo "  Install CLion and launch it once, then run this installer again." >&2
  read -r -p "Press Enter to close…" _ ; exit 1
fi
CONFIG_DIR="$(printf '%s\n' "${CONFIG_DIRS[@]}" | sort -V | tail -1)"
echo "CLion config: $CONFIG_DIR"

# --- close CLion so it reloads the plugin on next launch ---------------------
osascript -e 'tell application "CLion" to quit' >/dev/null 2>&1 || true
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
cat > "$OPTIONS_DIR/oslab.xml" <<XML
<application>
  <component name="OsLabSettings">
    <option name="backendUrl" value="$(xml_escape "$BACKEND_URL")" />
    <option name="devLoginCode" value="$(xml_escape "$DEV_LOGIN_CODE")" />
  </component>
</application>
XML
echo "✔ Backend URL configured."

# --- launch CLion ------------------------------------------------------------
echo
echo "Launching CLion…"
if [[ -n "$PROJECT_DIR" ]]; then
  open -a CLion "$PROJECT_DIR" 2>/dev/null || open -a CLion 2>/dev/null || true
else
  open -a CLion 2>/dev/null || true
fi

cat <<DONE

✔ Done.
  • Open the "OS Lab" tool window on the right (it should appear automatically).
  • Log in with the code your instructor gave you.
  • The exam runs in full screen. If you leave CLion, your instructor is notified.

הותקן בהצלחה. פתחו את חלון "OS Lab" מימין, התחברו עם הקוד שקיבלתם,
ועבדו אך ורק בתוך CLion. יציאה מהחלון תדווח למרצה.
DONE
# `|| true`: when run without a TTY (EOF on stdin) read returns non-zero, which
# under `set -e` would make a successful install exit 1. Don't let it.
read -r -p "Press Enter to close…" _ || true
