#!/bin/sh
# CPU frequency governor. The stock kernel command line (in the boot image, which
# the port does not replace) sets cpufreq.default_governor=performance, and
# Android's post-boot script, which would switch to walt, never runs here: left
# alone, every core sits at its top frequency. Measured on the 8 GB tablet
# (issue #60): schedutil draws 0.6 W less than performance when idle, screen on
# or off, does the same sustained work, and reaches top frequency in 4-33 ms.
#
# The policies appear when scmi_cpufreq.ko loads (loa-modules.service), so wait
# for them. Override with GOVERNOR=... in /etc/default/loa-cpufreq (not shipped).
GOVERNOR=schedutil
[ -r /etc/default/loa-cpufreq ] && . /etc/default/loa-cpufreq
C=/sys/devices/system/cpu/cpufreq
for i in $(seq 1 100); do ls $C/policy*/scaling_governor >/dev/null 2>&1 && break; sleep 0.2; done
rc=0
for p in $C/policy*; do
    [ -w $p/scaling_governor ] || { echo "no cpufreq policy"; exit 1; }
    echo "$GOVERNOR" > $p/scaling_governor 2>/dev/null || rc=1
    echo "$(basename $p): $(cat $p/scaling_governor)"
done
[ $rc = 0 ] || echo "governor $GOVERNOR not accepted (available: $(cat $C/policy0/scaling_available_governors))"
exit $rc
