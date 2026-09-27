#!/bin/sh
# Start the ADSP/CDSP remote processors like Android's /vendor/bin/start_subsys.sh.
# ADSP carries the battery/charger glink services and sensors; WPSS runs the
# WCN7750 Wi-Fi firmware (icnss2 then probes qca_cld3 -> wlan0).
for i in $(seq 1 20); do ls /sys/class/remoteproc/remoteproc* >/dev/null 2>&1 && break; sleep 0.5; done
for name in soccp adsp cdsp wpss; do
    for r in /sys/class/remoteproc/remoteproc*; do
        grep -q "$name" "$r/name" 2>/dev/null || continue
        state=$(cat "$r/state")
        case "$state" in running|attached) echo "loa-subsys: $name already $state";;
            *) echo "loa-subsys: starting $name ($(cat $r/firmware))"; echo start > "$r/state" || echo "loa-subsys: $name start failed";;
        esac
    done
done
exit 0
