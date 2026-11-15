#!/bin/sh
# CPU frequency governor. The stock kernel command line (in the boot image, which
# the port does not replace) sets cpufreq.default_governor=performance, and
# Android's post-boot script, which would switch to walt, never runs here: left
# alone, every core sits at its top frequency. Measured on the 8 GB tablet
# (issue #60): schedutil draws 0.6 W less than performance when idle, screen on
# or off, does the same sustained work, and reaches top frequency in 4-33 ms.
#
# Bus clock floor: the vendor bus DCVS driver starts every device in
# /sys/devices/system/cpu/bus_dcvs (DDR, LLCC, DDRQOS) with boost_freq at hw_max_freq
# "for better boot perf", and Android's post-boot script lowers it to hw_min_freq. That
# script never runs here, so the memory and cache clocks stay at maximum. At minimum the
# 8 GB tablet draws 0.24 W less awake with the screen off (1.11 W -> 0.87 W) and sustained
# memory throughput is unchanged, but a short burst after a pause takes about 1.6 times as
# long (issue #60). Override with BUS_FLOOR=max (keep the boot state) in the same file.
#
# Frequency switching: schedutil at its boot defaults still draws more than walt when
# idle, because the frequency keeps moving. Kernel RT threads carry uclamp.min 1024
# (sched_util_clamp_min_rt_default), so each of their wake-ups takes policy0 from its
# lowest step to its highest, and rate_limit_us 45 lets policy6 switch about 20 times a
# second. With the RT clamp at 0 (Android's post-boot script writes the same) and a rate
# limit of 10 ms the 8 GB tablet draws 0.09 W less with the screen off (0.81 W -> 0.72 W)
# and 0.15 W less with it on, and ramp-up, burst and throughput figures are unchanged
# (issue #60). The two go together: the rate limit alone draws more than the boot
# defaults, so it is written only once the clamp is in place. Override with
# RT_CLAMP_MIN=1024 and RATE_LIMIT_US=45 (the boot state) in the same file.
#
# The policies appear when scmi_cpufreq.ko loads (loa-modules.service), so wait
# for them. Override with GOVERNOR=... in /etc/default/loa-cpufreq (not shipped).
GOVERNOR=schedutil
BUS_FLOOR=min
RT_CLAMP_MIN=0
RATE_LIMIT_US=10000
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

# RT clamp first, then the schedutil rate limit (other governors have no such file)
K=/proc/sys/kernel/sched_util_clamp_min_rt_default
case "$RT_CLAMP_MIN$RATE_LIMIT_US" in
    *[!0-9]*) echo "RT_CLAMP_MIN and RATE_LIMIT_US must be numbers, not '$RT_CLAMP_MIN' and '$RATE_LIMIT_US'"; rc=1 ;;
    *)
        if echo "$RT_CLAMP_MIN" > $K 2>/dev/null; then
            echo "rt clamp min: $(cat $K)"
            for p in $C/policy*; do
                [ -w $p/schedutil/rate_limit_us ] || continue
                echo "$RATE_LIMIT_US" > $p/schedutil/rate_limit_us 2>/dev/null || { echo "$(basename $p): rate_limit_us $RATE_LIMIT_US not accepted"; continue; }
                echo "$(basename $p): rate_limit_us $(cat $p/schedutil/rate_limit_us)"
            done
        else
            echo "rt clamp min $RT_CLAMP_MIN not accepted, rate limit left alone"
        fi ;;
esac

# bus floor; a missing driver or a refused write is not worth failing the unit over
case "$BUS_FLOOR" in
    min) F=hw_min_freq ;;
    max) F=hw_max_freq ;;
    *) echo "BUS_FLOOR must be min or max, not '$BUS_FLOOR'"; F=; rc=1 ;;
esac
if [ -n "$F" ]; then
    B=/sys/devices/system/cpu/bus_dcvs
    for i in $(seq 1 25); do [ -d $B ] && break; sleep 0.2; done
    [ -d $B ] || echo "no bus_dcvs"
    for d in $B/*; do
        [ -w $d/boost_freq ] && [ -r $d/hw_min_freq ] && [ -r $d/hw_max_freq ] || continue
        v=$(cat $d/$F)
        echo "$v" > $d/boost_freq 2>/dev/null || { echo "$(basename $d): boost_freq $v not accepted"; continue; }
        echo "$(basename $d): boost_freq $(cat $d/boost_freq)"
    done
fi
exit $rc
