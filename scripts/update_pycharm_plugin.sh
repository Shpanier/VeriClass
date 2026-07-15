#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────
#  update_pycharm_plugin.sh — install/update the VeriExam PyCharm plugin.
#
#  Thin wrapper around update_plugin.sh, pinned to the PyCharm product. It pulls
#  the PyCharm zip the build machine published and installs it into PyCharm only.
#
#    ./update_pycharm_plugin.sh                     # built-in server URL
#    ./update_pycharm_plugin.sh https://my.server   # override the server
# ─────────────────────────────────────────────────────────────────────────
exec "$(dirname "${BASH_SOURCE[0]}")/update_plugin.sh" --product pycharm "$@"
