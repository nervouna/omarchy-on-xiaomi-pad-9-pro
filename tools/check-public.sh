#!/bin/sh
# Pre-publish check: scan every file git would publish for things that must not
# leave your machine (keys, device identifiers, personal names/paths).
#   tools/check-public.sh            scan tracked + staged files
#   EXTRA='\b(name|other)\b' tools/check-public.sh   add your own patterns
cd "$(dirname "$0")/.."
PAT='BEGIN [A-Z ]*PRIVATE KEY|ssh-(ed25519|rsa) AAAA|/Users/[a-z]|/home/[a-z]+/(Library|Develop)'
PAT="$PAT|([0-9a-f]{2}:){5}[0-9a-f]{2}"                 # full MAC addresses
PAT="$PAT|serialno=[0-9A-Za-z]{6,}|ro\.serialno|androidboot\.serialno=[0-9a-z]"
PAT="$PAT|Confidential and Proprietary"
[ -n "$EXTRA" ] && PAT="$PAT|$EXTRA"
fail=0
for f in $(git ls-files --cached); do
    [ -f "$f" ] || continue
    case "$f" in tools/check-public.sh) continue ;; esac
    if hits=$(grep -anIiE "$PAT" "$f" | grep -viE '00:00:00:00:00:00|ff:ff:ff:ff:ff:ff|xx:xx|02:00:00:77:00:0[12]' | head -3) && [ -n "$hits" ]; then
        echo "== $f"; echo "$hits" | cut -c1-160; fail=1
    fi
    # binaries: build paths / home dirs baked in
    if ! grep -qI . "$f" 2>/dev/null && strings -a "$f" | grep -qE '/Users/|/home/[a-z]+/'; then
        echo "== $f: binary contains a home path"; fail=1
    fi
done
for f in rootfs-overlay/usr/lib/loa/android-props.tar.gz rootfs-overlay/root/.ssh/authorized_keys; do
    git ls-files --error-unmatch "$f" >/dev/null 2>&1 && { echo "== $f must not be tracked"; fail=1; }
done
[ $fail = 0 ] && echo "check-public: clean" || { echo "check-public: review the hits above"; exit 1; }
