#!/bin/sh
# loa-bthci (in the Android island) initializes the stock BT HAL and exposes the
# controller on a PTY; btattach puts the hci_uart H4 line discipline on it -> hci0.
# The GKI kernel has no hci_vhci. If either side exits, stop both (systemd restarts).
R=/opt/loa-android
rm -f $R/data/bthci.path
/usr/lib/loa/android-run /loa/bin/loa-bthci /data/bthci.path &
BRIDGE=$!
for i in $(seq 120); do
    [ -s $R/data/bthci.path ] && break
    kill -0 $BRIDGE 2>/dev/null || exit 1
    sleep 0.5
done
[ -s $R/data/bthci.path ] || { kill $BRIDGE; exit 1; }
rfkill unblock bluetooth 2>/dev/null
btattach -B "$(cat $R/data/bthci.path)" -P h4 &
ATTACH=$!
wait -n $BRIDGE $ATTACH 2>/dev/null || wait $ATTACH
kill $BRIDGE $ATTACH 2>/dev/null
exit 1
