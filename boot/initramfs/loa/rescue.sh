#!/bin/sh
# Stage-1 rescue: expose a USB ACM serial shell + ECM network for up to
# RESCUE_SECS, then return (the caller reboots to Fastboot).
RESCUE_SECS=300
echo "<3>loa-rescue: $* -- USB serial shell for ${RESCUE_SECS}s" > /dev/kmsg
/loa/usb-gadget.sh
if [ -c /dev/ttyGS0 ]; then
    ( setsid sh -c 'exec sh -i </dev/ttyGS0 >/dev/ttyGS0 2>&1' ) &
fi
ip link set usb0 up 2>/dev/null; ip addr add 192.168.77.2/30 dev usb0 2>/dev/null
i=0
while [ $i -lt $RESCUE_SECS ] && [ ! -e /run/loa-rescue-done ]; do sleep 1; i=$((i+1)); done
