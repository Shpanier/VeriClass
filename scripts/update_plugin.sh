#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────
#  update_plugin.sh — install/update the VeriExam plugin over the tunnel.
#
#  Run this on ANY machine (teacher or student). It downloads the plugin the
#  build machine published to the backend and drops it into the matching
#  JetBrains IDE's plugins folder. The IDE (CLion or PyCharm) is detected from
#  the published zip itself, so ONE script serves both products. Restart the
#  IDE afterwards to load it.
#
#    ./update_plugin.sh                          # newest published, any product
#    ./update_plugin.sh https://my.server        # override the server
#    ./update_plugin.sh --product pycharm         # only the PyCharm plugin
#    ./update_plugin.sh --product clion           # only the CLion plugin
#
#  Server URL:  positional argument, else $OSLAB_SERVER, else the default below.
#  Product:     --product, else $OSLAB_PRODUCT, else DEFAULT_PRODUCT (blank = auto:
#               take whatever was published last and install into the matching IDE).
#  Override the JetBrains config base for testing with $JETBRAINS_DIR.
# ─────────────────────────────────────────────────────────────────────────
set -euo pipefail

DEFAULT_SERVER="https://upgrade-nape-smasher.ngrok-free.dev"
DEFAULT_PRODUCT=""   # the /api/plugin/install-<product>.sh endpoint rewrites this
NG_HDR='ngrok-skip-browser-warning: true'   # skip ngrok-free's interstitial page

# Parse an optional server URL (positional) and optional --product.
SERVER=""
PRODUCT="${OSLAB_PRODUCT:-$DEFAULT_PRODUCT}"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --product)   PRODUCT="${2:-}"; shift 2 ;;
    --product=*) PRODUCT="${1#*=}"; shift ;;
    *)           SERVER="$1"; shift ;;
  esac
done
SERVER="${SERVER:-${OSLAB_SERVER:-$DEFAULT_SERVER}}"
SERVER="${SERVER%/}"

say() { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m✖\033[0m %s\n' "$*" >&2; exit 1; }
command -v curl  >/dev/null || die "curl not found."
command -v unzip >/dev/null || die "unzip not found."
case "$PRODUCT" in
  ""|clion|pycharm) ;;
  *) die "--product must be 'clion' or 'pycharm' (got '$PRODUCT')." ;;
esac
# Query suffix that pins the backend to one product (blank = newest of any).
Q=""; [[ -n "$PRODUCT" ]] && Q="?product=$PRODUCT"

# --- what's published? -------------------------------------------------------
META="$(curl -fsS -H "$NG_HDR" "$SERVER/api/plugin/version$Q" 2>/dev/null)" \
  || die "Can't reach $SERVER. Is the tunnel/backend up?"
echo "$META" | grep -q '"version": *null' \
  && die "No ${PRODUCT:+$PRODUCT }plugin has been published yet (run publish.sh${PRODUCT:+ --product $PRODUCT} on the build machine)."
VER="$(echo "$META" | sed -n 's/.*"version": *"\([^"]*\)".*/\1/p')"
say "Published version: ${VER:-unknown}${PRODUCT:+  (product: $PRODUCT)}"

# --- download ----------------------------------------------------------------
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
ZIP="$TMP/oslab-plugin.zip"
say "Downloading…"
curl -fsS -H "$NG_HDR" "$SERVER/api/plugin/latest$Q" -o "$ZIP" || die "Download failed."
# A valid zip starts with 'PK'. If ngrok served an HTML page instead, catch it.
[[ "$(head -c2 "$ZIP")" == "PK" ]] || die "Downloaded file is not a zip (got a web page?). Check the server URL."

# --- which product is this? --------------------------------------------------
# The zip's top-level folder is the plugin name: oslab-clion-plugin/ or
# oslab-pycharm-plugin/. Use it to (a) target the right IDE family and (b)
# know the exact folder to replace — never hardcode a product here.
TOP="$(unzip -Z1 "$ZIP" 2>/dev/null | awk -F/ 'NF{print $1}' | sort -u | head -1)"
[[ -n "$TOP" ]] || die "Couldn't read the plugin folder name from the zip."
if [[ -n "$PRODUCT" ]]; then
  # Pinned by --product: target that IDE regardless of what the zip looks like.
  case "$PRODUCT" in
    pycharm) GLOBS=("PyCharm*") ; IDE_NAME="PyCharm" ;;   # PyCharm* also matches PyCharmCE*
    clion)   GLOBS=("CLion*")   ; IDE_NAME="CLion" ;;
  esac
else
  # Auto: infer the IDE family from the plugin's own top-level folder name.
  case "$TOP" in
    *pycharm*) GLOBS=("PyCharm*") ; IDE_NAME="PyCharm" ;;
    *clion*)   GLOBS=("CLion*")   ; IDE_NAME="CLion" ;;
    *)         GLOBS=("CLion*" "PyCharm*") ; IDE_NAME="your IDE" ;;
  esac
fi
say "Plugin: $TOP  →  target IDE: $IDE_NAME"

# --- find the IDE's plugins directory ----------------------------------------
# JetBrains stores plugins in a per-product dir, but the LAYOUT differs by OS —
# and getting it wrong means the IDE silently never loads the plugin:
#   macOS:   ~/Library/Application Support/JetBrains/<product>/plugins/
#   Linux:   ~/.local/share/JetBrains/<product>/          (NO plugins/ subfolder)
#   Windows: %APPDATA%/JetBrains/<product>/plugins/       (Git Bash / MSYS)
# Detect the OS from `uname` and set BASE + the plugins subfolder accordingly.
# For testing, JETBRAINS_DIR overrides the base and JETBRAINS_PLUGINS_SUBDIR
# overrides the subfolder ("" selects the Linux layout).
case "$(uname -s)" in
  Darwin)
    OS_NAME="macOS"
    BASE="$HOME/Library/Application Support/JetBrains"
    SUBDIR="plugins" ;;
  Linux)
    OS_NAME="Linux"
    BASE="$HOME/.local/share/JetBrains"
    SUBDIR="" ;;                       # the product dir IS the plugins dir
  MINGW*|MSYS*|CYGWIN*)
    OS_NAME="Windows"
    BASE="${APPDATA:-$HOME/AppData/Roaming}/JetBrains"
    SUBDIR="plugins" ;;
  *)
    OS_NAME="$(uname -s) (unknown — assuming Linux layout)"
    BASE="$HOME/.local/share/JetBrains"
    SUBDIR="" ;;
esac
if [[ -n "${JETBRAINS_DIR:-}" ]]; then
  BASE="$JETBRAINS_DIR"
  SUBDIR="${JETBRAINS_PLUGINS_SUBDIR-$SUBDIR}"
fi
say "Detected OS: $OS_NAME"

# Newest product dir across the target IDE's globs (e.g. PyCharm* covers CE too).
list_products() { for g in "${GLOBS[@]}"; do ls -d "$BASE"/$g 2>/dev/null || true; done; }
CONFIG_DIR="$(list_products | sort -V | tail -1 || true)"
if [[ -z "$CONFIG_DIR" ]]; then
  DEST="$HOME/Downloads/${TOP}-${VER:-latest}.zip"
  cp "$ZIP" "$DEST"
  say "No $IDE_NAME config dir found under $BASE."
  echo "   Saved the plugin to: $DEST"
  echo "   Install it manually:  $IDE_NAME → Settings → Plugins → ⚙ → Install Plugin from Disk…"
  exit 0
fi

PLUGINS="$CONFIG_DIR${SUBDIR:+/$SUBDIR}"
mkdir -p "$PLUGINS"
say "Installing into: $PLUGINS"
# Remove any previous copy — in the correct spot AND the pre-fix wrong spot
# (older versions of this script mistakenly used <product>/plugins on Linux).
rm -rf "$CONFIG_DIR/$TOP" "$CONFIG_DIR/plugins/$TOP"
unzip -oq "$ZIP" -d "$PLUGINS"
[[ -d "$PLUGINS/$TOP" ]] || die "Unexpected zip layout — expected a top-level $TOP/ folder."

say "✓ Installed version ${VER:-?}. RESTART $IDE_NAME to load it."
# All matching product dirs except the newest (the one we installed into).
# `sed '$d'` drops the last line — portable, unlike `head -n -1` which BSD/macOS head rejects.
OTHERS="$(list_products | sort -V | sed '$d' || true)"
[[ -n "$OTHERS" ]] && echo "   (Installed into the newest $IDE_NAME only. Other versions found: $(echo "$OTHERS" | xargs -n1 basename | tr '\n' ' '))"
