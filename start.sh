#!/usr/bin/env bash
# Start VeriClass on macOS or Linux:   ./start.sh
#
# The first start installs what VeriClass needs into this folder (Python
# included, through the tool "uv"); later starts take a few seconds. Then the
# lecturer's dashboard opens in the browser.
#
#   ./start.sh --port 8020     another port (default 8010)
#   ./start.sh --lan           also reachable from the local network
#   ./start.sh --no-browser    don't open the browser
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH:/opt/homebrew/bin:/usr/local/bin"

if ! command -v uv >/dev/null 2>&1; then
  echo "==> Installing uv (it installs Python and the packages VeriClass needs)..."
  if command -v curl >/dev/null 2>&1; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
  elif command -v wget >/dev/null 2>&1; then
    wget -qO- https://astral.sh/uv/install.sh | sh
  else
    echo "Neither curl nor wget is installed. Install uv yourself: https://docs.astral.sh/uv/" >&2
    exit 1
  fi
  export PATH="$HOME/.local/bin:$PATH"
fi
if ! command -v uv >/dev/null 2>&1; then
  echo "uv was installed but isn't on the PATH. Open a new terminal and run ./start.sh again." >&2
  exit 1
fi

if [ ! -d .venv ]; then
  echo "==> First start: downloading the packages (about 350 MB, a few minutes)..."
fi
exec uv run --frozen python -m backend.cli "$@"
