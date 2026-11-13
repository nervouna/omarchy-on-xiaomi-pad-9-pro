#!/bin/sh
# usage: ramboot.sh BOOT_IMG  (run from the repo root); RAM-boots it, writes nothing
tools/tssh 'echo 300 > /loa/dev-watchdog; sync; systemd-run --on-active=2 /usr/lib/loa/loa-helper bootloader' || exit 1
for i in $(seq 1 40); do [ -n "$(fastboot devices 2>/dev/null)" ] && break; /bin/sleep 2; done
[ "$(fastboot getvar product 2>&1 | head -1)" = "product: shuntian" ] || { echo "not shuntian"; exit 1; }
fastboot boot "$1" 2>&1 | tail -3
for i in $(seq 1 60); do
  tools/tssh 'rm -f /loa/dev-watchdog; touch /run/loa-watchdog-disarm; uname -r; cat /proc/uptime' 2>/dev/null && exit 0
  [ $i -gt 12 ] && [ -n "$(fastboot devices 2>/dev/null)" ] && { echo "back in fastboot"; exit 2; }
  /bin/sleep 4
done
echo "no ssh, no fastboot"; exit 3
