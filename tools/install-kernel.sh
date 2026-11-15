#!/bin/sh
# Install this project's rebuilt kernel (user, PID and IPC namespaces) on the
# tablet over USB, or put the stock kernel back. Run from the Mac; the tablet
# runs Omarchy with the current overlay (it needs /usr/local/bin/loa-kernel).
#   tools/install-kernel.sh             the newest kernel-* release
#   tools/install-kernel.sh TAG         that release
#   tools/install-kernel.sh DIR         a local build: boot-gz.img and
#                                       system_dlkm_staging_archive.tar.gz
#   tools/install-kernel.sh --restore   write the stock kernel back
#
# Writes boot_<active slot> and nothing else. The slot's stock boot image is
# copied to backups/ on the Mac first: if the tablet stops booting, hold
# Power + Volume Down for Fastboot and flash that file back.
set -e
D=$(cd "$(dirname "$0")/.." && pwd)
T="$D/tools/tssh"
if [ "$1" = --restore ]; then
    "$T" loa-kernel restore
    exit
fi
SRC=$1
if [ -z "$SRC" ]; then
    SRC=$(gh release list --limit 100 --json tagName -q '[.[].tagName | select(startswith("kernel-"))][0]')
    [ -n "$SRC" ] || { echo "no kernel-* release"; exit 1; }
fi
if [ ! -d "$SRC" ]; then
    DIR="$D/build/kernel/$SRC"
    mkdir -p "$DIR"
    gh release download "$SRC" --dir "$DIR" --clobber \
        -p boot-gz.img -p system_dlkm_staging_archive.tar.gz -p SHA256SUMS
    (cd "$DIR" && grep -E '  (boot-gz\.img|system_dlkm_staging_archive\.tar\.gz)$' SHA256SUMS | shasum -a 256 -c -)
    SRC=$DIR
fi
[ -f "$SRC/boot-gz.img" ] && [ -f "$SRC/system_dlkm_staging_archive.tar.gz" ] || { echo "$SRC: no kernel build"; exit 1; }

# The stock image, on the Mac, before anything is written.
set -- $("$T" loa-kernel backup)
[ -n "$2" ] || { echo "no stock boot image on the tablet"; exit 1; }
B="$D/backups/boot-stock-$(echo "$2" | cut -c1-12).img"
mkdir -p "$D/backups"
if [ "$(shasum -a 256 "$B" 2>/dev/null | cut -d' ' -f1)" != "$2" ]; then
    "$T" "cat $1" > "$B"
    [ "$(shasum -a 256 "$B" | cut -d' ' -f1)" = "$2" ] || { echo "the copy of the stock image differs"; exit 1; }
fi
echo "stock boot image: $B"

(cd "$SRC" && COPYFILE_DISABLE=1 tar -cf - boot-gz.img system_dlkm_staging_archive.tar.gz) |
    "$T" 'rm -rf /run/loa-kernel && mkdir /run/loa-kernel && tar -xf - -C /run/loa-kernel && loa-kernel install /run/loa-kernel; r=$?; rm -rf /run/loa-kernel; exit $r'
echo "Restart the tablet to use the new kernel. If it does not come up: Fastboot, then"
echo "  fastboot flash boot_<slot> $B"
