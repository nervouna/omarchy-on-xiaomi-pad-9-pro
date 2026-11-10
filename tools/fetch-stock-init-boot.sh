#!/bin/sh
# Extract the stock init_boot.img from an official fastboot ROM archive (run on the Mac).
#   tools/fetch-stock-init-boot.sh ~/Downloads/OS4.0.5.0.XFPCNXM.tgz [SHA256]
# Writes ONLY images/init_boot-stock-OS4.0.5.0.img (the restore image that
# boot/build-init-boot.py reads). The archive is never unpacked as a whole: only
# the init_boot.img member is streamed out of it. SHA256 (or LOA_STOCK_SHA256)
# may be a full digest or a prefix such as the truncated one in images/README.md.
set -e
D=$(cd "$(dirname "$0")/.." && pwd)
ARCH=$1
EXPECTED=${2:-$LOA_STOCK_SHA256}
[ -f "$ARCH" ] || { sed -n '2,6p' "$0"; exit 2; }
DST=$D/images/init_boot-stock-OS4.0.5.0.img

members=$(tar -tzf "$ARCH" | grep -E '(^|/)images/init_boot\.img$' || true)
count=$(printf '%s\n' "$members" | grep -c . || true)
case $count in
    1) ;;
    0) echo "no images/init_boot.img in $ARCH"; exit 1 ;;
    *) echo "more than one images/init_boot.img in $ARCH:"; printf '%s\n' "$members"; exit 1 ;;
esac

mkdir -p "$D/images"
tar -xzOf "$ARCH" "$members" > "$DST.part"
mv "$DST.part" "$DST"

if command -v sha256sum >/dev/null 2>&1; then SHA=$(sha256sum "$DST" | cut -d' ' -f1)
else SHA=$(shasum -a 256 "$DST" | cut -d' ' -f1); fi
echo "$DST: $(wc -c < "$DST" | tr -d ' ') bytes, sha256 $SHA"

if [ -n "$EXPECTED" ]; then
    EXPECTED=$(printf '%s' "$EXPECTED" | tr 'A-F' 'a-f')
    [ ${#EXPECTED} -ge 8 ] || { echo "expected digest too short: $EXPECTED"; exit 2; }
    case $SHA in
        "$EXPECTED"*) echo "digest matches ${EXPECTED}" ;;
        *) echo "digest does NOT match $EXPECTED; removing $DST"; rm -f "$DST"; exit 1 ;;
    esac
else
    echo "no expected digest given (2nd argument or LOA_STOCK_SHA256); not verified"
fi
