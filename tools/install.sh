#!/bin/sh
# Install native Omarchy on a tablet that is in Fastboot (run on the Mac).
#   tools/install.sh images/omarchy-clean-YYYYMMDD.img.zst
# Writes ONLY two partitions: `ramdump` (the root filesystem image) and
# `init_boot` of the active slot (our stage 1). Nothing else is touched; the
# Fastboot bootloader lives on other storage units and is never written.
# Prerequisites (docs/runbook.md): unlocked bootloader, stock firmware
# OS4.0.5.0.XFPCNXM on the active slot, images/init_boot-omarchy.img built by
# boot/build-init-boot.py.
set -e
D=$(cd "$(dirname "$0")/.." && pwd)
IMG=$1
[ -f "$IMG" ] || { sed -n '2,10p' "$0"; exit 2; }
BOOT=$D/images/init_boot-omarchy.img
[ -f "$BOOT" ] || { echo "missing $BOOT (python3 boot/build-init-boot.py)"; exit 1; }

gv() { fastboot getvar "$1" 2>&1 | sed -n "s/^$1: *//p" | head -1; }
PRODUCT=$(gv product); UNLOCKED=$(gv unlocked); SLOT=$(gv current-slot)
echo "product=$PRODUCT unlocked=$UNLOCKED current-slot=$SLOT"
[ "$PRODUCT" = shuntian ] || { echo "not a shuntian in Fastboot"; exit 1; }
[ "$UNLOCKED" = yes ] || { echo "bootloader is locked"; exit 1; }
case $SLOT in a|b) ;; *) echo "unknown slot '$SLOT'"; exit 1;; esac

[ -f "$IMG.sha256" ] && { echo "checking image digest"; (cd "$(dirname "$IMG")" && shasum -a 256 -c "$(basename "$IMG").sha256"); }
RAW=${IMG%.zst}
[ -f "$RAW" ] || { echo "decompressing to $RAW"; zstd -d -q -o "$RAW" "$IMG"; }

printf "Flash %s -> ramdump and %s -> init_boot_%s ? [yes/N] " "$(basename "$RAW")" "$(basename "$BOOT")" "$SLOT"
read ans; [ "$ans" = yes ] || { echo "aborted"; exit 1; }
# fastboot converts a large raw image to sparse chunks by itself.
fastboot flash ramdump "$RAW"
fastboot flash init_boot_$SLOT "$BOOT"
echo "flashed. Rebooting; the first boot takes ~1 min to the desktop."
echo "If 'flash ramdump' is refused by this bootloader, see docs/runbook.md (Magisk route)."
fastboot reboot
