#!/bin/bash
# macOS: double-click this file to start VeriClass. (The first time, macOS may
# ask you to confirm: right-click the file, choose Open, then Open again.)
cd "$(dirname "$0")" || exit 1
./start.sh "$@"
status=$?
if [ $status -ne 0 ]; then
  echo
  read -r -p "VeriClass stopped with an error (see above). Press Enter to close this window."
fi
exit $status
