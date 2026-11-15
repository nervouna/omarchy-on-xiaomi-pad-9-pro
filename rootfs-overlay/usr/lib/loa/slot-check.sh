#!/bin/sh
# The bootloader keeps A/B state in the GPT attributes of boot_<slot>: bits 51-53 retry
# count, bit 54 successful, bit 55 unbootable. Until the slot is marked successful it
# takes one retry off on every boot and refuses the slot at 0: the tablet then stops in
# Fastboot (issue #74). Stock Android sets the bit once it has booted; nothing here
# does, and this script only reads: abl sits in the same partition table.
SLOT=$(sed -n 's/^androidboot.slot_suffix = "\(_[ab]\)"$/\1/p' /proc/bootconfig 2>/dev/null)
[ -n "$SLOT" ] || SLOT=$(tr ' ' '\n' < /proc/cmdline | sed -n 's/^androidboot.slot_suffix=//p')
F=$(lsblk -rno PARTLABEL,PARTFLAGS 2>/dev/null | sed -n "s/^boot$SLOT //p" | head -1)
case "$SLOT$F" in
    _[ab]0x*) ;;
    *) echo "slot check: no flags for boot$SLOT"; exit 0 ;;
esac
B=$(( (F >> 48) & 0xff ))
if [ $(( B & 0x40 )) -ne 0 ]; then
    echo "slot $SLOT is marked successful"
else
    echo "<4>slot $SLOT is not marked successful: $(( (B >> 3) & 7 )) boots left before the bootloader stops in Fastboot. Run reboot-to-android, let Android reach its first screen, then restart. From Fastboot: fastboot set_active ${SLOT#_}, then fastboot reboot."
fi
exit 0
