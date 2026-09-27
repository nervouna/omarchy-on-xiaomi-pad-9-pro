#!/bin/bash
# Load the stock Android second-stage modules (system_dlkm, then vendor_dlkm) in
# Android's order, minus Android's blocklists and ours. Stage-1 already loaded
# the first-stage set from the vendor ramdisk.
D=/usr/lib/loa/modules
mapfile -t block < <(sed -n 's/^blocklist //p' $D/*blocklist* 2>/dev/null | tr - _)
declare -A skip; for b in "${block[@]}"; do skip[$b]=1; done
ok=0; fail=0
load_list() {
    while read -r m; do
        [ -n "$m" ] || continue
        n=$(basename "$m" .ko | tr - _)
        [ -n "${skip[$n]}" ] && continue
        [ -d /sys/module/$n ] && continue
        if modprobe -b "$n" 2>/tmp/modprobe.err; then ok=$((ok+1)); else fail=$((fail+1)); echo "loa-modules: $n failed: $(head -c 200 /tmp/modprobe.err)"; fi
    done < "$1"
}
load_list $D/system_dlkm.load
load_list $D/vendor_dlkm.load
echo "loa-modules: loaded=$ok failed=$fail"
/usr/lib/loa/busybox mdev -s
exit 0
