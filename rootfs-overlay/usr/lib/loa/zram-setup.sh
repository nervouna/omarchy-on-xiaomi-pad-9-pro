#!/bin/sh
# zram swap without systemd device units: on this port PID 1 never sees udev
# device events (device units stay "tentative"), so zram-generator's
# dev-zram0.swap waits forever. Half of RAM, zstd, priority 100.
set -e
swapon --show=NAME --noheadings | grep -q '^/dev/zram0$' && exit 0
modprobe zram
for i in $(seq 1 50); do [ -b /dev/zram0 ] && break; sleep 0.1; done
[ -b /dev/zram0 ] || { echo "no /dev/zram0"; exit 1; }
if [ "$(cat /sys/block/zram0/disksize)" = 0 ]; then
    echo zstd > /sys/block/zram0/comp_algorithm
    echo "$(( $(sed -n 's/^MemTotal: *\([0-9]*\) kB/\1/p' /proc/meminfo) / 2 ))K" > /sys/block/zram0/disksize
fi
mkswap -q /dev/zram0
swapon -p 100 /dev/zram0
echo "zram swap: $(swapon --show=SIZE --noheadings /dev/zram0)"
