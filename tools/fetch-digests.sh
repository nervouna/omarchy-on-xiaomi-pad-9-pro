#!/bin/sh
# Copy new usage digests (loa-digest.timer, /var/lib/loa-digest) from the tablet
# on the USB cable to this Mac, then print the newest digest's date and age for
# every tablet fetched so far. Read-only on the tablet.
#   tools/fetch-digests.sh
#   TSSH=<main checkout>/tools/tssh tools/fetch-digests.sh    (from a worktree)
# Digests land in ${XDG_STATE_HOME:-~/.local/state}/loa-digest/<hostname>-<RAM>g/;
# both tablets are called shuntian, so the nominal RAM size (8 or 12) tells them
# apart. No tablet reachable is not an error: the ages are printed all the same.
D=$(cd "$(dirname "$0")/.." && pwd)
TSSH=${TSSH:-$D/tools/tssh}
STATE=${XDG_STATE_HOME:-$HOME/.local/state}/loa-digest
SRC=/var/lib/loa-digest

if id=$("$TSSH" 'hostname; sed -n "s/^MemTotal: *\([0-9]*\) kB/\1/p" /proc/meminfo' 2>/dev/null); then
    host=$(echo "$id" | sed -n 1p | tr -cd 'A-Za-z0-9-')
    kb=$(echo "$id" | sed -n 2p | tr -cd 0-9)
    gb=""
    for n in 4 6 8 12 16 24 32 64; do
        [ "${kb:-0}" -le $((n * 1048576)) ] && { gb=$n; break; }
    done
    [ -n "$host" ] && [ -n "$gb" ] || { echo "fetch-digests: could not identify the tablet" >&2; exit 1; }
    dest=$STATE/$host-${gb}g
    mkdir -p "$dest"
    # name and size of each digest on the tablet; fetch what is missing or changed
    want=""
    for line in $("$TSSH" "cd $SRC 2>/dev/null && for f in *.json *.txt; do [ -f \"\$f\" ] && echo \"\$f:\$(wc -c < \"\$f\")\"; done"); do
        f=${line%%:*}; size=${line#*:}
        echo "$f" | grep -qE '^[0-9]{4}-[0-9]{2}-[0-9]{2}\.(json|txt)$' || continue
        [ -f "$dest/$f" ] && [ "$(wc -c < "$dest/$f" | tr -d ' ')" = "$size" ] && continue
        want="$want $f"
    done
    if [ -n "$want" ]; then
        # shellcheck disable=SC2086  # $want: validated file names, split on purpose
        "$TSSH" "cd $SRC && tar -cf - $want" | (cd "$dest" && tar -xf -) || { echo "fetch-digests: copy failed" >&2; exit 1; }
        echo "$host-${gb}g: fetched$(echo "$want" | wc -w | tr -s ' ') file(s)"
    else
        echo "$host-${gb}g: nothing new"
    fi
else
    echo "no tablet reachable"
fi

now=$(date +%s)
found=0
for dir in "$STATE"/*/; do
    [ -d "$dir" ] || continue
    newest=$(ls "$dir" 2>/dev/null | grep -E '^[0-9]{4}-[0-9]{2}-[0-9]{2}\.json$' | sort | tail -1)
    [ -n "$newest" ] || continue
    found=1
    until=$(sed -n 's/^ *"until": *\([0-9]*\).*/\1/p' "$dir$newest" | head -1)
    if [ -n "$until" ]; then
        age=$(( (now - until) / 3600 ))
        echo "$(basename "$dir"): newest digest ${newest%.json}, period ended ${age} h ago ($((age / 24)) d)"
    else
        echo "$(basename "$dir"): newest digest ${newest%.json}, age unknown (no \"until\" field)"
    fi
done
[ $found = 1 ] || echo "no digest was ever fetched (looked in $STATE)"
exit 0
