#!/bin/sh
# Provenance check for the prebuilt ELF binaries tracked in git
# (docs/maintenance.md, "Prebuilt helper binaries"). Run from CI or by hand.
#   tools/check-helpers.sh                 table and busybox checks
#   BASE=<sha> HEAD=<sha> tools/check-helpers.sh   also compare sources with binaries
# 1. every tracked ELF file is listed in the table, and its sha256 matches;
# 2. busybox is the unmodified Ubuntu package binary (downloaded, pinned by the
#    package sha256);
# 3. with BASE and HEAD: a source and the binary built from it change in the
#    same pull request, or neither does. The C helpers cannot be rebuilt bit for
#    bit (the recorded zig build is not available), so this stands in for a
#    rebuild-and-compare.
cd "$(dirname "$0")/.." || exit 1
fail=0
err() { echo "check-helpers: $*"; fail=1; }
sha() { sha256sum "$1" 2>/dev/null || shasum -a 256 "$1"; }

DOC=docs/maintenance.md
BB_DEB=busybox-static_1.36.1-6ubuntu3.1_arm64.deb
BB_POOL=pool/main/b/busybox/$BB_DEB
# Mirrors of ports.ubuntu.com; the package sha256 below is what is trusted.
BB_HOSTS='ports.ubuntu.com/ubuntu-ports azure.ports.ubuntu.com/ubuntu-ports mirrors.kernel.org/ubuntu-ports'
BB_DEB_SHA=d96535e0402c011e0ee43449799df2f4504d44b842e4f2b3a6cbc845508eaafc

# Table rows: | `path` | ... | `sha256` | ...
table=$(awk -F'|' '
    /^## Prebuilt helper binaries/ { on = 1; next }
    /^## / { on = 0 }
    on && NF > 5 {
        p = $2; gsub(/[` ]/, "", p)
        for (i = 3; i < NF; i++) { s = $i; gsub(/[` ]/, "", s); if (s ~ /^[0-9a-f]{64}$/) { print p, s; break } }
    }' "$DOC")
[ -n "$table" ] || err "no binary table found in $DOC"

# 1. table against the tracked ELF files
elf=
for f in $(git ls-files); do
    [ -f "$f" ] && [ ! -L "$f" ] || continue
    [ "$(head -c 4 "$f" | od -An -c | tr -d ' ')" = '177ELF' ] && elf="$elf $f"
done
n=0
for f in $elf; do
    n=$((n + 1))
    want=$(echo "$table" | awk -v p="$f" '$1 == p { print $2 }')
    [ -n "$want" ] || { err "$f is not in the table"; continue; }
    have=$(sha "$f" | cut -d' ' -f1)
    [ "$have" = "$want" ] || err "$f: sha256 $have, table says $want"
done
echo "$table" | while read -r p _; do
    case " $elf " in *" $p "*) ;; *) echo "check-helpers: the table lists $p, which is not a tracked ELF file"; exit 1 ;; esac
done || fail=1
echo "check-helpers: $n tracked ELF binaries checked against the table"

# 2. busybox is the unmodified Ubuntu binary
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
got=
for h in $BB_HOSTS; do
    curl -fsSL --retry 2 -o "$tmp/$BB_DEB" "http://$h/$BB_POOL" || continue
    [ "$(sha "$tmp/$BB_DEB" | cut -d' ' -f1)" = "$BB_DEB_SHA" ] && { got=1; break; }
    echo "check-helpers: $h served $BB_DEB with another sha256"
done
if [ -n "$got" ]; then
    (cd "$tmp" && ar x "$BB_DEB" && zstd -dc data.tar.zst | tar -x ./usr/bin/busybox) || err "cannot unpack $BB_DEB"
    want=$(sha "$tmp/usr/bin/busybox" | cut -d' ' -f1)
    for f in boot/busybox-static rootfs-overlay/usr/lib/loa/busybox; do
        [ "$(sha "$f" | cut -d' ' -f1)" = "$want" ] || err "$f differs from the busybox in $BB_DEB"
    done
    echo "check-helpers: busybox matches the binary in $BB_DEB"
else
    err "cannot download $BB_DEB from $BB_HOSTS"
fi

# 3. source and binary change together
if [ -n "$BASE" ] && [ -n "$HEAD" ]; then
    changed=$(git diff --name-only "$BASE...$HEAD")
    pair() { # binary source
        b=0; s=0
        echo "$changed" | grep -qxF "$1" && b=1
        echo "$changed" | grep -qxF "$2" && s=1
        [ $b = $s ] || err "$2 and $1 must change in the same pull request (source changed: $s, binary changed: $b)"
    }
    pair boot/initramfs/loa/loa-helper boot/loa-helper.c
    pair rootfs-overlay/usr/lib/loa/loa-helper boot/loa-helper.c
    pair rootfs-overlay/usr/lib/loa/loa-splash-off tools/src/splash-off/loa-splash-off.c
    pair rootfs-overlay/usr/lib/loa/loa-xtouch tools/src/xtouch/loa-xtouch.c
    pair rootfs-overlay/usr/lib/loa/loa-thp-launcher tools/src/thp-launcher/loa-thp-launcher.c
    pair rootfs-overlay/opt/loa-android/loa/bin/loa-bthci tools/src/loa-bthci/loa-bthci.cpp
    pair rootfs-overlay/opt/loa-android/loa/bin/loa-pal tools/src/loa-pal/loa-pal.cpp
    pair rootfs-overlay/opt/loa-android/loa/lib64/libloa_selinux_stub.so tools/src/selinux-stub/libloa_selinux_stub.c
    echo "check-helpers: sources and binaries compared for $BASE...$HEAD"
fi

[ $fail = 0 ] && echo "check-helpers: clean" || { echo "check-helpers: fix the errors above"; exit 1; }
