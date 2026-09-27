#!/bin/sh
# Rebuild the small native helpers from tools/src and boot/ (run on the Mac).
#   tools/build.sh [all|c|ndk]
# C helpers: static musl via zig (brew install zig).
# Android-side helpers (run inside /opt/loa-android with Bionic): Android NDK r28c
#   NDK=/path/to/ndk-r28c (default: toolchains/ndk-r28c, git-ignored).
#   They link against the tablet's own libraries, which aren't in git:
#   tools/fetch-device-libs.sh copies them into tools/src/*/lib/.
#   loa-pal also needs CodeLinaro arpal-lx headers (tag lnx.2.0.r10-rel):
#   git clone https://git.codelinaro.org/clo/le/platform/vendor/qcom-opensource/arpal-lx.git src/arpal
# Outputs go straight into rootfs-overlay/ (and boot/initramfs/loa/ for loa-helper).
set -e
D=$(cd "$(dirname "$0")/.." && pwd)
S=$D/tools/src; O=$D/rootfs-overlay
what=${1:-all}
zcc() { zig cc -target aarch64-linux-musl -O2 -static -s "$@"; }

if [ "$what" = all ] || [ "$what" = c ]; then
    zcc -o "$D/boot/initramfs/loa/loa-helper" "$D/boot/loa-helper.c"
    cp "$D/boot/initramfs/loa/loa-helper" "$O/usr/lib/loa/loa-helper"
    zcc -o "$O/usr/lib/loa/loa-splash-off" "$S/splash-off/loa-splash-off.c"
    zcc -o "$O/usr/lib/loa/loa-xtouch" "$S/xtouch/loa-xtouch.c"
    mkdir -p "$D/build"
    zcc -o "$D/build/loa-kmstest" "$S/kmstest/loa-kmstest.c"      # diagnostics only
    zcc -o "$D/build/loa-drmprops" "$S/drmprops/loa-drmprops.c"   # diagnostics only
    echo "C helpers built"
fi

if [ "$what" = all ] || [ "$what" = ndk ]; then
    NDK=${NDK:-$D/toolchains/ndk-r28c}
    B=$NDK/toolchains/llvm/prebuilt/darwin-x86_64/bin
    [ -x "$B/clang" ] || { echo "NDK not found at $NDK (set NDK=...)"; exit 1; }
    L=$O/opt/loa-android/loa
    "$B/aarch64-linux-android31-clang++" -O2 -Wall -std=c++17 -static-libstdc++ \
        -o "$L/bin/loa-bthci" "$S/loa-bthci/loa-bthci.cpp" -L"$S/loa-bthci/lib" -lbinder_ndk
    "$B/aarch64-linux-android35-clang++" -std=c++17 -O2 -I"$D/src/arpal/inc" \
        -o "$L/bin/loa-pal" "$S/loa-pal/loa-pal.cpp" -L"$S/loa-pal/lib" -lpalclient \
        -Wl,--allow-shlib-undefined -static-libstdc++
    # Freestanding LD_PRELOAD stub (no libc NEEDED; strdup/free resolve from Bionic).
    "$B/aarch64-linux-android31-clang" -O2 -fPIC -shared -nostdlib \
        -o "$L/lib64/libloa_selinux_stub.so" "$S/selinux-stub/libloa_selinux_stub.c"
    "$B/llvm-strip" --strip-debug "$L/lib64/libloa_selinux_stub.so"   # no build paths in the blob
    echo "NDK helpers built"
fi
