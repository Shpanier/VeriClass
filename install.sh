#!/usr/bin/env bash
# Install (or update) VeriClass on macOS or Linux and start it:
#
#   curl -fsSL https://raw.githubusercontent.com/Shpanier/VeriClass/main/install.sh | bash
#
# It puts VeriClass in ~/VeriClass (set VERICLASS_DIR for another folder). Run
# the same line again later to update: your settings (.env), your database
# (vericlass.db) and your exercises (data/) are kept.
set -euo pipefail
REPO="${VERICLASS_REPO:-https://github.com/Shpanier/VeriClass}"
BRANCH="${VERICLASS_BRANCH:-main}"
DIR="${VERICLASS_DIR:-$HOME/VeriClass}"

if [ -d "$DIR/.git" ]; then
  echo "==> Updating VeriClass in $DIR"
  git -C "$DIR" pull --ff-only
elif command -v git >/dev/null 2>&1 && [ ! -e "$DIR" ]; then
  echo "==> Downloading VeriClass to $DIR"
  git clone --depth 1 --branch "$BRANCH" "$REPO" "$DIR"
else
  echo "==> Downloading VeriClass to $DIR"
  mkdir -p "$DIR"
  # Only the files of the release are written: .env, vericlass.db and data/ stay.
  curl -fsSL "$REPO/archive/refs/heads/$BRANCH.tar.gz" | tar -xz -C "$DIR" --strip-components=1
fi
chmod +x "$DIR/start.sh" "$DIR/start.command" 2>/dev/null || true
echo "==> Starting. Next time: $DIR/start.sh  (on a Mac you can double-click start.command)"
exec "$DIR/start.sh" "$@"
