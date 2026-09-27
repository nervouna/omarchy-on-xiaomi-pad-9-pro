#!/bin/sh
# Copy the tablet's own Android libraries that the NDK helpers link against
# (Xiaomi/Qualcomm binaries: kept out of git). Needs native Omarchy running.
set -e
D=$(cd "$(dirname "$0")/.." && pwd)
mkdir -p "$D/tools/src/loa-bthci/lib" "$D/tools/src/loa-pal/lib"
"$D/tools/tssh" 'cat /android/system/system/lib64/libbinder_ndk.so' > "$D/tools/src/loa-bthci/lib/libbinder_ndk.so"
"$D/tools/tssh" 'cat /android/vendor/lib64/libpalclient.so' > "$D/tools/src/loa-pal/lib/libpalclient.so"
ls -l "$D/tools/src/loa-bthci/lib" "$D/tools/src/loa-pal/lib"
