#!/usr/bin/env bash
# Register the VeriClass MCP server (vericlass_mcp/server.py) with Claude Code, for
# this project only (local scope). Run it once from anywhere; then open Claude
# Code in this folder and /mcp lists "vericlass". The server must be running for
# most tools (scripts/dev_up.sh); validate_exercise works without it.
#
#   VERICLASS_URL       the server (default http://127.0.0.1:8010)
#   VERICLASS_DATA_DIR  the private data folder (default ../VeriClassPrivateData)
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$REPO/.venv/bin/python"
[[ -x "$PY" ]] || { echo "No $PY: create the virtualenv first (see README)." >&2; exit 1; }
command -v claude >/dev/null || { echo "Claude Code (the 'claude' command) isn't installed." >&2; exit 1; }

ENV=(-e "VERICLASS_URL=${VERICLASS_URL:-http://127.0.0.1:8010}")
[[ -n "${VERICLASS_DATA_DIR:-}" ]] && ENV+=(-e "VERICLASS_DATA_DIR=$VERICLASS_DATA_DIR")

cd "$REPO"
claude mcp remove vericlass --scope local >/dev/null 2>&1 || true
claude mcp add vericlass --scope local "${ENV[@]}" -- "$PY" "$REPO/vericlass_mcp/server.py"
echo "Registered the VeriClass MCP server for $REPO."
