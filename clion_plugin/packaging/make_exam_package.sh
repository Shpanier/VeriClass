#!/usr/bin/env bash
# Build the OS Lab exam client and assemble the ZIP a teacher hands to students.
#
# Run on a machine with JDK 21 (CLion 2024.2 runs on JBR 21). The first build
# downloads the CLion SDK and is large; later builds are cached.
#
#   ./packaging/make_exam_package.sh --backend-url http://10.0.0.5:8000
#
# Output:
#   dist/OsLabExam/        the package folder (installers + plugin + docs)
#   dist/OsLabExam.zip     the same, zipped — this is what you send students
#
# Flags:
#   --backend-url URL    stamp this into exam.conf (default http://127.0.0.1:8000)
#   --plugin-zip PATH    use an already-built plugin zip; skip the Gradle build
#   --clion-version V    forwarded to Gradle as -PclionVersion (e.g. 2024.3.5)
#   --skip-build         reuse the newest zip already in build/distributions
#   -h | --help          show this help
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
TEMPLATES="$SCRIPT_DIR/templates"

BACKEND_URL="http://127.0.0.1:8000"
PLUGIN_ZIP=""
CLION_VERSION=""
SKIP_BUILD=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --backend-url) BACKEND_URL="$2"; shift 2 ;;
    --plugin-zip)  PLUGIN_ZIP="$2"; shift 2 ;;
    --clion-version) CLION_VERSION="$2"; shift 2 ;;
    --skip-build)  SKIP_BUILD=1; shift ;;
    -h|--help) grep -E '^#( |$)' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown flag: $1" >&2; exit 2 ;;
  esac
done

cd "$PLUGIN_DIR"
echo "==> Plugin dir: $PLUGIN_DIR"
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
          echo "  Install Gradle, or open clion_plugin/ in IntelliJ once (it generates the jar)." >&2
          exit 1
        }
    fi
  fi

  if ! command -v java >/dev/null 2>&1; then
    echo "✖ No Java found. Install JDK 21 (e.g. 'brew install --cask temurin@21') and retry." >&2
    exit 1
  fi

  echo "==> Building the plugin (./gradlew buildPlugin)…"
  BUILD_CMD=(./gradlew buildPlugin --no-daemon)
  [[ -n "$CLION_VERSION" ]] && BUILD_CMD+=("-PclionVersion=$CLION_VERSION")
  "${BUILD_CMD[@]}"
fi

if [[ -z "$PLUGIN_ZIP" ]]; then
  PLUGIN_ZIP="$(ls -t build/distributions/oslab-clion-plugin-*.zip 2>/dev/null | head -1 || true)"
fi
if [[ -z "$PLUGIN_ZIP" || ! -f "$PLUGIN_ZIP" ]]; then
  echo "✖ No plugin zip found in build/distributions/. Build first, or pass --plugin-zip." >&2
  exit 1
fi
echo "==> Plugin zip: $PLUGIN_ZIP"

# --- assemble the package ----------------------------------------------------
OUT_DIR="$PLUGIN_DIR/dist/OsLabExam"
echo "==> Assembling $OUT_DIR"
rm -rf "$OUT_DIR"
mkdir -p "$OUT_DIR/plugin"

cp "$PLUGIN_ZIP" "$OUT_DIR/plugin/oslab-exam-plugin.zip"
cp "$TEMPLATES/install-macos.command" "$OUT_DIR/"
cp "$TEMPLATES/install-windows.ps1"   "$OUT_DIR/"
cp "$TEMPLATES/install-windows.bat"   "$OUT_DIR/"
cp "$TEMPLATES/README-STUDENT.md"     "$OUT_DIR/"
cp "$TEMPLATES/README-STUDENT.he.md"  "$OUT_DIR/"
chmod +x "$OUT_DIR/install-macos.command"

# Stamp the backend URL into exam.conf.
sed "s#__BACKEND_URL__#${BACKEND_URL//#/\\#}#" "$TEMPLATES/exam.conf" > "$OUT_DIR/exam.conf"

# --- zip it ------------------------------------------------------------------
( cd "$PLUGIN_DIR/dist" && rm -f OsLabExam.zip && zip -rqX OsLabExam.zip OsLabExam )

cat <<DONE

==> Package ready.
    Folder: $OUT_DIR
    Zip:    $PLUGIN_DIR/dist/OsLabExam.zip   <-- send this to students

Before the exam, on the backend (.env):
    STUDENT_CLIENT_MODE=ide
    EXAM_MODE=true          # (optional; defaults on in ide mode)
    FULLSCREEN=true         # (optional; defaults on with exam mode)
Then restart the backend and open the dashboard to watch students.

If you change BACKEND_URL later, just edit dist/OsLabExam/exam.conf and re-zip,
or re-run this script with a new --backend-url.
DONE
