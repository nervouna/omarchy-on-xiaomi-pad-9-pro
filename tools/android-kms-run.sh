#!/system/bin/sh
# Stop Android's compositor, run loa-kmstest with the given args, report underruns,
# then ALWAYS restart the compositor (Xiaomi hang_detect panics after ~4 min without SF).
E=/sys/kernel/debug/dri/0/encoder69/status
[ -f $E ] || mount -t debugfs debugfs /sys/kernel/debug
stop surfaceflinger; stop vendor.qti.hardware.display.composer; sleep 1
echo "before:"; cat $E
echo 1500 > /sys/class/backlight/panel0-backlight/brightness
timeout 70 /data/local/tmp/loa-kmstest "$@" 2>&1 | grep -vE '^(MODE\[|PLANE )'
echo "after:"; cat $E
start vendor.qti.hardware.display.composer; start surfaceflinger
