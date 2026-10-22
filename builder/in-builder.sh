#!/bin/bash
# Runs inside the disposable build root (builder/build-image.sh):
#   Mesa with KGSL -> /build/out/mesa (installed as /opt/omarchy-android/mesa)
#   patched Aquamarine -> /build/out/aquamarine-VER-REL-aarch64.pkg.tar.zst
# Args: JOBS AQUAMARINE_VERSION PKGREL
set -Eeuo pipefail
JOBS=$1 AQVER=$2 AQREL=$3
O=/build/out; mkdir -p $O

# Mesa: freedreno (GL) + turnip (Vulkan) on the KGSL kernel interface. No LLVM
# (no llvmpipe): this tree lives outside pacman, and a libLLVM it linked would
# vanish with the next llvm-libs upgrade. Software fallback is the system Mesa.
MESA=/opt/omarchy-android/mesa
meson setup /build/mesa-build /build/mesa --prefix=/usr \
    -Dplatforms=x11,wayland -Dgallium-drivers=freedreno,zink,virgl -Dllvm=disabled \
    -Dgallium-va=disabled -Dgallium-mediafoundation=disabled \
    -Dvulkan-drivers=freedreno -Dvulkan-layers= -Degl=enabled -Dgles2=enabled \
    -Dglvnd=enabled -Dglx=dri -Dlibunwind=disabled -Dintel-rt=disabled \
    -Dmicrosoft-clc=disabled -Dvalgrind=disabled -Dgles1=disabled \
    -Dfreedreno-kmds=kgsl -Dbuildtype=release
meson compile -C /build/mesa-build -j "$JOBS"
DESTDIR=$O/mesa/root meson install -C /build/mesa-build
icd=$(find $O/mesa/root/usr/share/vulkan/icd.d -name '*freedreno*.json' | head -1)
python3 - "$icd" "$O/mesa/freedreno_icd.json" "$MESA/root/usr/lib/libvulkan_freedreno.so" <<'PY'
import json, sys
src, dst, lib = sys.argv[1:]
d = json.load(open(src)); d["ICD"]["library_path"] = lib
json.dump(d, open(dst, "w"), indent=4); open(dst, "a").write("\n")
PY

# Aquamarine, packaged so pacman owns the files (IgnorePkg keeps it). The
# package metadata mirrors Arch Linux ARM's aquamarine. Built without makepkg:
# this kernel may lack SysV IPC, which stock fakeroot needs.
P=/build/aq-pkg; rm -rf $P
cmake -S /build/aquamarine -B /build/aq-build -G Ninja -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_INSTALL_PREFIX=/usr -W no-dev
cmake --build /build/aq-build -j "$JOBS"
DESTDIR=$P cmake --install /build/aq-build
install -Dm644 /build/aquamarine/LICENSE -t $P/usr/share/licenses/aquamarine
# Package a DESTDIR tree without makepkg (this kernel may lack SysV IPC, which
# stock fakeroot needs). mkpkg DIR NAME VERSION-REL DESC URL LICENSE [provides=..|depend=..]...
mkpkg() {
    local dir=$1 name=$2 ver=$3 desc=$4 url=$5 lic=$6; shift 6
    {
        echo "pkgname = $name"; echo "pkgbase = $name"; echo "pkgver = $ver"
        echo "pkgdesc = $desc"; echo "url = $url"; echo "builddate = $(date +%s)"
        echo "packager = omarchy-on-xiaomi-pad-9-pro builder"
        echo "size = $(du -sb "$dir" | cut -f1)"; echo "arch = aarch64"; echo "license = $lic"
        for x in "$@"; do echo "${x%%=*} = ${x#*=}"; done
    } > "$dir/.PKGINFO"
    (cd "$dir" && bsdtar --zstd --uid 0 --gid 0 -cf "$O/$name-$ver-aarch64.pkg.tar.zst" .PKGINFO usr)
}
field() { LC_ALL=C pacman -Si aquamarine | sed -n "s/^$1 *: //p" | head -1; }
list() { field "$1" | tr ' ' '\n' | grep -v -e '^None$' -e '^$' || true; }
meta=()
for x in $(list Provides); do meta+=("provides=$x"); done
for x in $(list 'Depends On'); do meta+=("depend=$x"); done
mkpkg $P aquamarine "$AQVER-$AQREL" "$(field Description) (shuntian SDE split-primary build)" \
    "$(field URL)" BSD-3-Clause "${meta[@]}"

ls -l $O
