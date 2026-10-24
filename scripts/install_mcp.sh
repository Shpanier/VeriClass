#!/usr/bin/env bash
# Register the VeriExam MCP server (veriexam_mcp/server.py) with Claude Code, for
# this project only (local scope). Run it once from anywhere; then open Claude
# Code in this folder and /mcp lists "veriexam". The server must be running for
# most tools (scripts/dev_up.sh); validate_exercise works without it.
#
#   VERIEXAM_URL       the server (default http://127.0.0.1:8010)
#   VERIEXAM_DATA_DIR  the private data folder (default ../VeriExPrivateData)
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$REPO/.venv/bin/python"
[[ -x "$PY" ]] || { echo "No $PY: create the virtualenv first (see README)." >&2; exit 1; }
command -v claude >/dev/null || { echo "Claude Code (the 'claude' command) isn't installed." >&2; exit 1; }

ENV=(-e "VERIEXAM_URL=${VERIEXAM_URL:-http://127.0.0.1:8010}")
[[ -n "${VERIEXAM_DATA_DIR:-}" ]] && ENV+=(-e "VERIEXAM_DATA_DIR=$VERIEXAM_DATA_DIR")

cd "$REPO"
claude mcp remove veriexam --scope local >/dev/null 2>&1 || true
claude mcp add veriexam --scope local "${ENV[@]}" -- "$PY" "$REPO/veriexam_mcp/server.py"
echo "Registered the VeriExam MCP server for $REPO."
