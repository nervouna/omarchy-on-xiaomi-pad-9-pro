#!/bin/sh
# PostTransaction for packages that ship a Chromium sandbox helper
# (30-loa-chrome-sandbox.hook; paths on stdin, also run by overlay-install.sh).
# This kernel has no user namespaces (CONFIG_USER_NS is off), so Chromium and
# Electron apps fall back to the setuid helper and abort when it isn't root's
# with mode 4755. Builds made for machines with user namespaces don't always set
# it: Omarchy's aarch64 Bitwarden 2026.10.1 ships it 0755, with the whole tree
# owned by its builder's uid 1001. Never fails the transaction.
while read -r t; do
    f=/${t#/}
    [ -f "$f" ] && [ ! -L "$f" ] || continue
    d=$(dirname "$f")
    # Whoever later gets the uid that owns the app's files could swap its
    # binaries, setuid helper or not: hand the tree to root. (An upgrade keeps
    # the directory's owner but extracts the files with the package's.)
    case $d in /opt/?* | /usr/lib/?*)
        u=$(find "$d" ! -user 0 -printf '%U\n' -quit)
        [ -z "$u" ] || { chown -R root:root "$d" && echo "LoA: $d had files owned by uid $u, now root's"; } ;;
    esac
    [ "$(stat -c %u:%a "$f")" = 0:4755 ] && continue
    chown root:root "$f" && chmod 4755 "$f" && echo "LoA: made $f setuid root (no user namespaces on this kernel)"
done
exit 0
