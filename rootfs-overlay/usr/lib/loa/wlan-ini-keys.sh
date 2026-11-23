#!/bin/sh
# Add this port's keys to the Wi-Fi driver's WCNSS_qcom_cfg.ini (arg: the file).
# The file stays the vendor's, plus one marked block above its END line (the
# driver ignores everything after END). Idempotent: the old block is dropped and
# written again, a vendor line that sets one of the keys is commented out (the
# port's value wins, once), and the file is only rewritten when it changes.
# Called by setup-wlan-files.sh (every overlay update) and import-vendor.sh.
# Keys (issue 103): the driver multicasts its firmware log (app id 27) and host
# log (app id 28) on the cld80211 netlink family for Android's cnss_diag; nobody
# listens here, so every send fails with an err-level kernel line, about once a
# second. Measured on the 8 GB tablet (docs/maintenance.md):
#   gMulticastHostFwMsgs=0  silences app ids 27 and 17
#   wlanLoggingEnable=0     silences app id 28 (the wlan_logging_thread)
# Either key alone makes the other ids louder; gEnablefwlog=0 is not needed.
# Never add gEnableWoW here: the WPSS firmware crashes (engineering log).
F=$1
KEYS="gMulticastHostFwMsgs=0 wlanLoggingEnable=0"
B='# loa: begin port keys (wlan-ini-keys.sh)'
E='# loa: end port keys'
[ -f "$F" ] || { echo "wlan-ini-keys: no $F"; exit 0; }
awk -v keys="$KEYS" -v b="$B" -v e="$E" '
    BEGIN { n = split(keys, kv, " "); for (i = 1; i <= n; i++) { k = kv[i]; sub(/=.*/, "", k); name[k] = 1 } }
    function block() { print b; for (i = 1; i <= n; i++) print kv[i]; print e; done = 1 }
    $0 == b { skip = 1; next }
    skip { if ($0 == e) skip = 0; next }
    /^END[ \t\r]*$/ && !done { block() }
    { k = $0; sub(/^[ \t]+/, "", k); sub(/[ \t]*=.*/, "", k)
      if ((k in name) && $0 ~ /=/) { print "#loa: " $0; next } }
    { print }
    END { if (!done) block() }
' "$F" > "$F.loa" || { rm -f "$F.loa"; echo "wlan-ini-keys: could not write $F"; exit 0; }
if cmp -s "$F.loa" "$F"; then rm -f "$F.loa"; else
    chmod 644 "$F.loa"; mv "$F.loa" "$F"; echo "wlan-ini-keys: port keys written to $F"
fi
