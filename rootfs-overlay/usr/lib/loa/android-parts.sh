#!/bin/sh
# Map the stock Android dynamic partitions of the *active* slot READ-ONLY out of
# `super` with dm-linear and mount them under /android/{system,vendor,odm}.
# Nothing is written to super. Extents are read from super's own liblp
# metadata (loa-lpmap.py), so OTAs and freshly flashed tablets work; the
# original tablet's table (OS4.0.5.0.XFPCNXM, slot b) is kept as a fallback.
set -e
part() {  # PARTNAME -> /dev/sdXN
    for u in /sys/class/block/*/uevent; do
        grep -q "^PARTNAME=$1\$" "$u" && { echo /dev/$(sed -n 's/^DEVNAME=//p' "$u"); return; }
    done
}
SLOT=$(sed -n 's/^androidboot.slot_suffix = "\(_[ab]\)"$/\1/p' /proc/bootconfig 2>/dev/null)
[ -n "$SLOT" ] || SLOT=$(tr ' ' '\n' < /proc/cmdline | sed -n 's/^androidboot.slot_suffix=//p')
[ -n "$SLOT" ] || SLOT=_b
S=$(part super)
[ -b "$S" ] || { echo "super not found"; exit 1; }
echo "active slot $SLOT, super $S"

map() {  # name then "len start" pairs (512-byte sectors)
    n=$1; shift; t=""; off=0
    while [ $# -gt 1 ]; do t="${t}${off} $1 linear $S $2\n"; off=$((off + $1)); shift 2; done
    dmsetup info "loa-$n" >/dev/null 2>&1 || printf "$t" | dmsetup create --readonly "loa-$n"
}
if tbl=$(python3 /usr/lib/loa/loa-lpmap.py "$S" "$SLOT" system vendor odm); then
    echo "$tbl" | while IFS='	' read -r n segs; do map "$n" $segs; done
else
    echo "loa-lpmap failed; using the built-in table of the original tablet (slot b)"
    [ "$SLOT" = _b ] || exit 1
    map system_b 1909120 15149056  136 21748056
    map vendor_b 1927096 18704384  8 21748192
    map odm_b    3155968 2048      1560 15147496  48 17058176
fi
dmsetup mknodes 2>/dev/null  # no devtmpfs/udev sync on the GKI kernel
for p in system vendor odm; do
    mkdir -p /android/$p
    mountpoint -q /android/$p || mount -o ro /dev/mapper/loa-${p}${SLOT} /android/$p
done
# DSP dynamic modules (Android: /vendor/dsp) from the dsp partition.
D=$(part dsp$SLOT)
mkdir -p /android/dsp
mountpoint -q /android/dsp || mount -o ro "$D" /android/dsp
# Bluetooth firmware (Android: /vendor/bt_firmware, vfat) from the bluetooth partition.
B=$(part bluetooth$SLOT)
mkdir -p /android/bt_firmware
mountpoint -q /android/bt_firmware || mount -t vfat -o ro,shortname=lower,uid=1002,gid=3002,dmask=227,fmask=337 "$B" /android/bt_firmware
# persist (BT address .bt_nv.bin etc.): strictly read-only, noload = no journal replay.
P=$(part persist)
mkdir -p /android/persist
mountpoint -q /android/persist || mount -t ext4 -o ro,noload "$P" /android/persist
echo "android partitions mounted read-only"
