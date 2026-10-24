#!/usr/bin/env bash
# Build the VeriClass exam client and assemble the ZIP a teacher hands to students.
#
# Run on a machine with JDK 21 (both IDEs' 2024.2 run on JBR 21). The first build
# downloads the IDE SDK and is large; later builds are cached.
#
#   ./packaging/make_exam_package.sh --backend-url http://10.0.0.5:8000
#   ./packaging/make_exam_package.sh --product pycharm --backend-url http://10.0.0.5:8000
#
# Output:
#   dist/VeriClassInstaller/        the package folder (installers + plugin + docs)
#   dist/VeriClassInstaller.zip     the same, zipped — this is what you send students
#
# Flags:
#   --product NAME       clion (default) or pycharm — which IDE this package targets
#   --backend-url URL    stamp this into exam.conf (default http://127.0.0.1:8000)
#   --plugin-zip PATH    use an already-built plugin zip; skip the Gradle build
#   --ide-version V      forwarded to Gradle (-PclionVersion / -PpycharmVersion)
#   --clion-version V    alias for --ide-version (kept for back-compat)
#   --skip-build         reuse the newest zip already built for that product
#   -h | --help          show this help
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
TEMPLATES="$SCRIPT_DIR/templates"

PRODUCT="clion"
BACKEND_URL="http://127.0.0.1:8000"
PLUGIN_ZIP=""
IDE_VERSION=""
SKIP_BUILD=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --product)     PRODUCT="$2"; shift 2 ;;
    --backend-url) BACKEND_URL="$2"; shift 2 ;;
    --plugin-zip)  PLUGIN_ZIP="$2"; shift 2 ;;
    --ide-version|--clion-version) IDE_VERSION="$2"; shift 2 ;;
    --skip-build)  SKIP_BUILD=1; shift ;;
    -h|--help) grep -E '^#( |$)' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown flag: $1" >&2; exit 2 ;;
  esac
done
case "$PRODUCT" in
  clion)   IDE_PRODUCT="CLion";   IDE_VERSION_PROP="clionVersion" ;;
  pycharm) IDE_PRODUCT="PyCharm"; IDE_VERSION_PROP="pycharmVersion" ;;
  *) echo "✖ --product must be 'clion' or 'pycharm' (got '$PRODUCT')" >&2; exit 2 ;;
esac
DIST="$PRODUCT/build/distributions"

cd "$PLUGIN_DIR"
echo "==> Plugin dir: $PLUGIN_DIR"
echo "==> Target IDE: $IDE_PRODUCT  (module :$PRODUCT)"
echo "==> Backend URL to stamp: $BACKEND_URL"

# --- build the plugin zip (unless given / skipped) ---------------------------
if [[ -z "$PLUGIN_ZIP" && "$SKIP_BUILD" -eq 0 ]]; then
  # Ensure the Gradle wrapper jar exists (this repo ships the scripts, not the
  # binary jar). Prefer a system Gradle; otherwise fetch the matching jar.
  WRAPPER_JAR="gradle/wrapper/gradle-wrapper.jar"
  if [[ ! -f "$WRAPPER_JAR" ]]; then
    GVER="$(grep -oE 'gradle-[0-9.]+-bin\.zip' gradle/wrapper/gradle-wrapper.properties | grep -oE '[0-9][0-9.]*' | head -1)"
    echo "==> Gradle wrapper jar missing (need Gradle $GVER)."
    if command -v gradle >/dev/null 2>&1; then
      echo "    Generating it with system Gradle…"
      gradle wrapper --gradle-version "$GVER"
    else
      echo "    Downloading gradle-wrapper.jar for $GVER…"
      curl -fsSL "https://raw.githubusercontent.com/gradle/gradle/v${GVER}/gradle/wrapper/gradle-wrapper.jar" \
        -o "$WRAPPER_JAR" || {
          echo "✖ Could not obtain gradle-wrapper.jar." >&2
          echo "  Install Gradle, or open vericlass_plugin/ in IntelliJ once (it generates the jar)." >&2
          exit 1
        }
    fi
  fi

  if ! command -v java >/dev/null 2>&1; then
    echo "✖ No Java found. Install JDK 21 (e.g. 'brew install --cask temurin@21') and retry." >&2
    exit 1
  fi

  echo "==> Building the plugin (./gradlew :$PRODUCT:buildPlugin)…"
  BUILD_CMD=(./gradlew ":$PRODUCT:buildPlugin" --no-daemon)
  [[ -n "$IDE_VERSION" ]] && BUILD_CMD+=("-P${IDE_VERSION_PROP}=$IDE_VERSION")
  "${BUILD_CMD[@]}"
fi

if [[ -z "$PLUGIN_ZIP" ]]; then
  PLUGIN_ZIP="$(ls -t "$DIST/vericlass-$PRODUCT-plugin-"*.zip 2>/dev/null | head -1 || true)"
fi
if [[ -z "$PLUGIN_ZIP" || ! -f "$PLUGIN_ZIP" ]]; then
  echo "✖ No plugin zip found in $DIST/. Build first, or pass --plugin-zip." >&2
  exit 1
fi
echo "==> Plugin zip: $PLUGIN_ZIP"

# --- assemble the package ----------------------------------------------------
OUT_DIR="$PLUGIN_DIR/dist/VeriClassInstaller"
echo "==> Assembling $OUT_DIR"
rm -rf "$OUT_DIR"
mkdir -p "$OUT_DIR/plugin"

cp "$PLUGIN_ZIP" "$OUT_DIR/plugin/vericlass-exam-plugin.zip"
cp "$TEMPLATES/install-macos.command" "$OUT_DIR/"
cp "$TEMPLATES/install-windows.ps1"   "$OUT_DIR/"
cp "$TEMPLATES/install-windows.bat"   "$OUT_DIR/"
# Student docs mention the IDE by name — stamp the target product (no-op for CLion).
sed "s/CLion/${IDE_PRODUCT}/g" "$TEMPLATES/README-STUDENT.md"    > "$OUT_DIR/README-STUDENT.md"
sed "s/CLion/${IDE_PRODUCT}/g" "$TEMPLATES/README-STUDENT.he.md" > "$OUT_DIR/README-STUDENT.he.md"
chmod +x "$OUT_DIR/install-macos.command"

# Stamp the backend URL and target IDE into exam.conf.
sed -e "s#__BACKEND_URL__#${BACKEND_URL//#/\\#}#" \
    -e "s#__IDE_PRODUCT__#${IDE_PRODUCT}#" \
    "$TEMPLATES/exam.conf" > "$OUT_DIR/exam.conf"

# --- zip it ------------------------------------------------------------------
( cd "$PLUGIN_DIR/dist" && rm -f VeriClassInstaller.zip && zip -rqX VeriClassInstaller.zip VeriClassInstaller )

cat <<DONE

==> Package ready.
    Folder: $OUT_DIR
    Zip:    $PLUGIN_DIR/dist/VeriClassInstaller.zip   <-- send this to students

Before the exam, on the backend (.env):
    STUDENT_CLIENT_MODE=ide
    EXAM_MODE=true          # (optional; defaults on in ide mode)
    FULLSCREEN=true         # (optional; defaults on with exam mode)
Then restart the backend and open the dashboard to watch students.

If you change BACKEND_URL later, just edit dist/VeriClassInstaller/exam.conf and re-zip,
or re-run this script with a new --backend-url.
DONE
