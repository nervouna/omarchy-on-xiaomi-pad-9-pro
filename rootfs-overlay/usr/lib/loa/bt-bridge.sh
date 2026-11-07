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
# Unblock the chip's power switch (bt_power) only: blocking it kills the stock
# HAL. hci0's own switch is the user's on/off (Omarchy patch 0009); systemd-rfkill
# restores it when btattach creates hci0, so leave it alone.
for id in $(rfkill -n -o ID,DEVICE list bluetooth 2>/dev/null | awk '$2 !~ /^hci/ { print $1 }'); do
    rfkill unblock "$id"
done
btattach -B "$(cat $R/data/bthci.path)" -P h4 &
ATTACH=$!
# hci0 appears after the Omarchy shell has started (boot, and every resume:
# loa-sleepd restarts the BT units). quickshell takes the adapter's properties
# from the InterfacesAdded snapshot, which still says Powered: no while BlueZ
# powers it up, and subscribes to PropertiesChanged only afterwards: it misses
# the power-up and the panel shows Bluetooth off, its switch doing nothing.
# Once the adapter has settled, cycle its power once so every BlueZ client sees
# a fresh change. Skipped when it is off (blocked) or already has a connection.
(
    for i in $(seq 40); do
        case $(timeout 2 bluetoothctl show 2>/dev/null) in
            *"PowerState: on"*|*"PowerState: off-blocked"*) break ;;
        esac
        sleep 0.5
    done
    sleep 2
    case $(timeout 2 bluetoothctl show 2>/dev/null) in *"PowerState: on"*) ;; *) exit 0 ;; esac
    [ -z "$(timeout 2 bluetoothctl devices Connected 2>/dev/null)" ] || exit 0
    timeout 5 bluetoothctl power off >/dev/null 2>&1
    timeout 5 bluetoothctl power on >/dev/null 2>&1
) &
wait -n $BRIDGE $ATTACH 2>/dev/null || wait $ATTACH
kill $BRIDGE $ATTACH 2>/dev/null
exit 1
