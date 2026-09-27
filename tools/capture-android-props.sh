#!/bin/sh
# Capture the Android property area from YOUR tablet running stock Android, rooted
# (Magisk), USB debugging on. The Android service island (/opt/loa-android) needs it:
# the stock vendor daemons read build/device properties from /dev/__properties__.
# It contains device identifiers (serial numbers), so it is git-ignored.
#   tools/capture-android-props.sh   -> rootfs-overlay/usr/lib/loa/android-props.tar.gz
set -e
D=$(cd "$(dirname "$0")/.." && pwd)
OUT=$D/rootfs-overlay/usr/lib/loa/android-props.tar.gz
[ "$(adb shell getprop ro.product.device | tr -d '\r')" = shuntian ] || { echo "no Xiaomi Pad 9 Pro on adb"; exit 1; }
adb shell su -c "'tar -czf - -C /dev __properties__'" > "$OUT.tmp"
tar -tzf "$OUT.tmp" >/dev/null && mv "$OUT.tmp" "$OUT"
echo "captured $(tar -tzf "$OUT" | wc -l | tr -d ' ') entries -> $OUT (git-ignored; apply-overlay installs it)"
