#!/bin/sh
# PreTransaction for llvm-libs (20-loa-mesa-keep-llvm.hook): copy each
# libLLVM.so.N that the KGSL Mesa needs into its own lib dir before pacman
# removes it. Never fails the transaction.
L=/opt/omarchy-android/mesa/root/usr/lib
[ -d $L ] || exit 0
for f in $L/*.so*; do
    [ -f "$f" ] && readelf -d "$f" 2>/dev/null
done | sed -n 's/.*NEEDED.*\[\(libLLVM\.so[^]]*\)\].*/\1/p' | sort -u | while read -r lib; do
    [ -e "$L/$lib" ] || [ ! -e "/usr/lib/$lib" ] && continue
    cp -a "/usr/lib/$lib" "$L/$lib" && echo "LoA: kept /usr/lib/$lib for the KGSL Mesa"
done
exit 0
