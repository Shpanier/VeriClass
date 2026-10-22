#!/usr/bin/env bash
# Download BusyBox for the VeriExam terminal into veriexam_plugin/busybox/,
# which the Gradle build ships inside the plugin as bin/<os>-<arch>/.
#
#   ./packaging/fetch_busybox.sh          # then: ./gradlew :pycharm:buildPlugin
#
# Students on Windows and Linux then run the SAME BusyBox tools (ls, grep, awk,
# sort, ...), so terminal exercises behave identically on both. macOS has no
# BusyBox build; Macs use the system bash.
#
# Every download is checked against a pinned SHA-256 and the script stops on a
# mismatch. Windows hashes are the publisher's (frippery.org SHA256SUM); the
# Linux one was recorded on first download (busybox.net publishes none).
# To upgrade: change the version + hash below.
set -euo pipefail

HERE=$(cd "$(dirname "$0")/.." && pwd)
OUT="$HERE/busybox"

# busybox-w32 (Windows): https://frippery.org/busybox/
W32=FRP-6075-g169694ebd
# Official static Linux build: https://busybox.net/downloads/binaries/
LINUX=1.35.0

sha256() {
    if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -d' ' -f1
    else shasum -a 256 "$1" | cut -d' ' -f1; fi
}

fetch() {
    local dest="$OUT/$1" url=$2 want=$3
    mkdir -p "$(dirname "$dest")"
    if [ -f "$dest" ] && [ "$(sha256 "$dest")" = "$want" ]; then
        echo "ok    $1 (already here)"
        return
    fi
    echo "get   $1  <- $url"
    curl -fsSL --retry 3 --max-time 180 -o "$dest.part" "$url"
    local got
    got=$(sha256 "$dest.part")
    if [ "$got" != "$want" ]; then
        rm -f "$dest.part"
        echo "ERROR $1: SHA-256 mismatch (expected $want, got $got)" >&2
        exit 1
    fi
    mv "$dest.part" "$dest"
    chmod +x "$dest"
    echo "ok    $1"
}

fetch windows-x86_64/busybox.exe \
    "https://frippery.org/files/busybox/busybox-w64-$W32.exe" \
    07bb1e5b095b00d68a695481f9240879f33c5724b40aa2308f999d54ed78f075
fetch windows-aarch64/busybox.exe \
    "https://frippery.org/files/busybox/busybox-w64a-$W32.exe" \
    e67f873d19d58c535cc9f0c4965ffd622e19b7bab87e3da89cb2185fb54464d7
fetch linux-x86_64/busybox \
    "https://busybox.net/downloads/binaries/$LINUX-x86_64-linux-musl/busybox" \
    6e123e7f3202a8c1e9b1f94d8941580a25135382b99e8d3e34fb858bba311348

# BusyBox is GPLv2: ship the license notice and where its source lives.
cat > "$OUT/BUSYBOX-NOTICE.txt" <<EOF
The VeriExam terminal runs BusyBox, which is free software licensed under the
GNU General Public License, version 2 (https://www.gnu.org/licenses/old-licenses/gpl-2.0.html).
BusyBox is a separate program; VeriExam starts it but does not link to it.

windows-*/busybox.exe  busybox-w32 $W32
                       binaries and source: https://frippery.org/busybox/
                       source repository:   https://github.com/rmyorston/busybox-w32
linux-x86_64/busybox   BusyBox $LINUX (static, musl)
                       binary: https://busybox.net/downloads/binaries/$LINUX-x86_64-linux-musl/
                       source: https://busybox.net/downloads/busybox-$LINUX.tar.bz2
EOF
echo "done  -> $OUT (rebuild the plugin to include it)"
