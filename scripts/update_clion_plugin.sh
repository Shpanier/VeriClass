#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────
#  update_clion_plugin.sh — install/update the VeriExam CLion plugin.
#
#  Thin wrapper around update_plugin.sh, pinned to the CLion product. It pulls
#  the CLion zip the build machine published and installs it into CLion only.
#
#    ./update_clion_plugin.sh                     # built-in server URL
#    ./update_clion_plugin.sh https://my.server   # override the server
# ─────────────────────────────────────────────────────────────────────────
exec "$(dirname "${BASH_SOURCE[0]}")/update_plugin.sh" --product clion "$@"
