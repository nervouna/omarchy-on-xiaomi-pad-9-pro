#!/bin/bash
# Build the Omarchy root filesystem image for the Xiaomi Pad 9 Pro from scratch:
# Arch Linux ARM packages + pinned Omarchy + Mesa (KGSL) + patched Aquamarine +
# this repo's overlay. The image carries no Xiaomi/Qualcomm files: the tablet
# imports its own modules, firmware and touch libraries on first boot
# (loa-vendor-import.service, stage 1).
#
#   builder/build-image.sh [OUTDIR]        (default OUTDIR: images/)
#
# Runs as root on native ARM64 Arch Linux ARM with git, e2fsprogs and zstd: a disposable container, a GitHub ARM runner, or a tablet
# that already runs this port. Work directory: $LOA_BUILD_WORK
# (default /var/tmp/loa-build), removed on success.
# Optional local inputs (git-ignored, never in a public build):
#   keys/*.pub                                  root's SSH key (tools/tssh)
#   rootfs-overlay/usr/lib/loa/android-props.tar.gz   Android property snapshot
#   images/pkgs/*.pkg.tar.zst                   AUR extras (fakeroot-tcp, yay-bin)
set -Eeuo pipefail
# All build mounts live in a private mount namespace: nothing mounted or
# unmounted here can propagate to the host. (Without it, the root's self-bind
# joins the host's shared peer group, and unmounting the build's /sys and /dev
# binds unmounted the host's own cgroup2, /dev/pts, /dev/shm, ... -- 2026-09-29.)
if [ -z "${LOA_BUILD_NS:-}" ]; then
    exec env LOA_BUILD_NS=1 unshare --mount --propagation private "$0" "$@"
fi
D=$(cd "$(dirname "$0")/.." && pwd)
OUT=${1:-$D/images}
W=${LOA_BUILD_WORK:-/var/tmp/loa-build}
JOBS=${JOBS:-$(nproc)}
SIZE=${LOA_IMAGE_SIZE:-16G}          # must fit the 17 GiB ramdump partition
STAMP=$(date +%Y%m%d)
log() { printf '\n== %s\n' "$*"; }

[ "$(uname -m)" = aarch64 ] || { echo "native ARM64 only"; exit 1; }
[ "$EUID" = 0 ] || { echo "run as root"; exit 1; }
for c in pacman git mkfs.ext4 e2fsck zstd sha256sum bsdtar gpg; do
    command -v $c >/dev/null || { echo "missing $c (pacman -S git e2fsprogs zstd libarchive gnupg)"; exit 1; }
done
[ ! -e "$W" ] || { echo "refusing to reuse $W (remove it first)"; exit 1; }
. "$D/builder/pins.conf"
CONF=$D/builder/pacman.conf
mkdir -p "$W/src" "$OUT"

# Minimal pacstrap/arch-chroot: the tablet's GKI kernel has no devtmpfs, which
# those tools require, so bind the host's /dev instead (works in containers too).
MOUNTED=""
root_up() {  # prepare DIR as an installable, chroot-able root
    local r=$1
    install -d -m 755 "$r"/var/cache/pacman/pkg "$r"/var/lib/pacman "$r"/var/log "$r"/dev "$r"/run "$r"/etc/pacman.d
    install -d -m 1777 "$r"/tmp; install -d -m 555 "$r"/proc "$r"/sys
    mount --bind "$r" "$r"   # pacman's CheckSpace needs / to be a mount point
    mount -t proc proc "$r/proc"
    mount --rbind /sys "$r/sys"; mount --make-rslave "$r/sys"
    mount --rbind /dev "$r/dev"; mount --make-rslave "$r/dev"
    mount -t tmpfs -o mode=755 tmpfs "$r/run"
    mount -t tmpfs -o mode=1777 tmpfs "$r/tmp"
    MOUNTED="$r $MOUNTED"
}
root_down() {
    local r=$1
    # Deepest first; lazy, since rbind'ed /dev and /sys hold submounts.
    for _ in 1 2 3; do
        findmnt -rn -o TARGET | grep "^$r" | sort -r | while read -r m; do umount -l "$m" 2>/dev/null || true; done
    done
    MOUNTED=${MOUNTED//"$r "/}
}
trap 'for r in $MOUNTED; do root_down "$r"; done' EXIT
install_pkgs() {  # ROOT PKG...
    local r=$1; shift
    pacman --root "$r" --config "$CONF" --cachedir "$r/var/cache/pacman/pkg" -Sy --noconfirm --needed "$@"
}
in_root() {  # ROOT CMD...: like arch-chroot, with the host's DNS
    local r=$1; shift
    cp -L /etc/resolv.conf "$r/etc/resolv.conf" 2>/dev/null || true
    chroot "$r" /usr/bin/env -i HOME=/root TERM=xterm LANG=C.UTF-8 \
        PATH=/usr/local/sbin:/usr/local/bin:/usr/bin "$@"
}

# The host keyring verifies all packages: it needs Omarchy's key for [omarchy].
if ! pacman-key --list-keys "$OMARCHY_KEY_FPR" >/dev/null 2>&1; then
    got=$(gpg --show-keys --with-colons "$D/rootfs-overlay/usr/share/loa/pacman/omarchy.asc" | awk -F: '$1=="fpr"{print $10; exit}')
    [ "$got" = "$OMARCHY_KEY_FPR" ] || { echo "Omarchy key fingerprint mismatch"; exit 1; }
    pacman-key --add "$D/rootfs-overlay/usr/share/loa/pacman/omarchy.asc"
    pacman-key --lsign-key "$OMARCHY_KEY_FPR"
fi

fetch() {  # dir repo rev: shallow checkout of one exact commit or tag
    git init -q "$1"; git -C "$1" remote add origin "$2"
    git -C "$1" fetch -q --depth 1 origin "$3"; git -C "$1" checkout -q FETCH_HEAD
}
log "sources"
fetch "$W/src/omarchy" "$OMARCHY_REPO" "$OMARCHY_REV"
git -C "$W/src/omarchy" -c user.name=builder -c user.email=builder@invalid am -q "$D"/patches/omarchy/*.patch
fetch "$W/src/mesa" "$MESA_REPO" "$MESA_REV"
fetch "$W/src/aquamarine" "$AQUAMARINE_REPO" "refs/tags/$AQUAMARINE_TAG"
git -C "$W/src/aquamarine" apply "$D"/patches/aquamarine-0001-*.patch
fetch "$W/src/ttfx" "$TTFX_REPO" "$TTFX_REV"

log "build root (disposable)"
mkdir -p "$W/builder"; root_up "$W/builder"
install_pkgs "$W/builder" base base-devel git meson ninja cmake pkgconf \
    python-mako python-packaging python-ply python-pycparser python-yaml \
    clang llvm llvm-libs libclc spirv-llvm-translator glslang spirv-tools \
    rust rust-bindgen cbindgen wayland wayland-protocols libdrm libglvnd \
    vulkan-headers vulkan-icd-loader expat libelf libpng libva libxext libxml2 \
    libxrandr libxshmfence libxxf86vm lm_sensors systemd-libs zlib zstd xorgproto \
    libx11 libxcb byacc flex hyprwayland-scanner hyprutils libdisplay-info libinput \
    seatd pixman hwdata mesa aquamarine
mkdir -p "$W/builder/build"
cp -a "$W/src/mesa" "$W/src/aquamarine" "$W/src/ttfx" "$W/builder/build/"
install -m 755 "$D/builder/in-builder.sh" "$W/builder/build/in-builder.sh"
in_root "$W/builder" /build/in-builder.sh "$JOBS" "${AQUAMARINE_TAG#v}" "$AQUAMARINE_PKGREL" "$TTFX_VER"

log "target root"
mkdir -p "$W/root"; root_up "$W/root"
mapfile -t PKGS < <(sed -e 's/#.*//' -e '/^[[:space:]]*$/d' "$D/builder/packages.txt")
install_pkgs "$W/root" "${PKGS[@]}"
R=$W/root
mkdir -p "$R/var/tmp/loa-build"
cp "$W/builder/build/out/"*.pkg.tar.zst "$R/var/tmp/loa-build/"
ls "$D"/images/pkgs/*.pkg.tar.zst >/dev/null 2>&1 && cp "$D"/images/pkgs/*.pkg.tar.zst "$R/var/tmp/loa-build/"
install -d "$R/opt/omarchy-android"
cp -a "$W/builder/build/out/mesa" "$R/opt/omarchy-android/mesa"
install -d "$R/usr/share/omarchy"
cp -a "$W/src/omarchy/." "$R/usr/share/omarchy/"; rm -rf "$R/usr/share/omarchy/.git"
(cd "$D" && tar -cf "$R/var/tmp/loa-build/loa-overlay.tar" rootfs-overlay user-defaults)
install -m 755 "$D/tools/overlay-install.sh" "$R/var/tmp/loa-build/overlay-install.sh"
install -m 755 "$D/builder/in-target.sh" "$R/var/tmp/loa-build/in-target.sh"
PUB=$(cat "$D"/keys/*.pub 2>/dev/null | head -1 || true)
in_root "$R" /var/tmp/loa-build/in-target.sh "$PUB"
rm -rf "$R/var/tmp/loa-build"
: > "$R/etc/resolv.conf"          # NetworkManager writes the real one
root_down "$R"; root_down "$W/builder"

log "privacy and sanity checks"
fail=0
for p in /root/.bash_history /home/omarchy/.bash_history /home/omarchy/.ssh /etc/NetworkManager/system-connections/* /var/lib/bluetooth/*; do
    compgen -G "$R$p" >/dev/null && { echo "unexpected: $p"; fail=1; }
done
[ -s "$R/etc/machine-id" ] && { echo "machine-id not empty"; fail=1; }
ls "$R"/etc/ssh/ssh_host_* >/dev/null 2>&1 && { echo "ssh host keys present"; fail=1; }
find "$R/var/cache/pacman/pkg" "$R/var/log" -type f -print -quit | grep -q . && { echo "package cache or logs present"; fail=1; }
find "$R/usr/lib/modules" -name '*.ko' -print -quit 2>/dev/null | grep -q . && { echo "vendor modules present"; fail=1; }
[ -e "$R/opt/loa-thp" ] && { echo "vendor touch libs present"; fail=1; }
for f in /usr/bin/Hyprland /opt/omarchy-android/mesa/root/usr/lib/libgallium-*.so /usr/share/omarchy/shell/shell.qml \
         /usr/lib/loa/import-vendor.sh /home/omarchy/.config/hypr/hyprland.lua /etc/systemd/system/sysinit.target.wants/loa-vendor-import.service; do
    compgen -G "$R$f" >/dev/null || { echo "missing: $f"; fail=1; }
done
[ $fail = 0 ] || { echo "checks failed; root left in $R"; exit 1; }

log "image"
IMG=$OUT/omarchy-scratch-$STAMP.img
rm -f "$IMG" "$IMG.zst"
mkfs.ext4 -q -L omarchy -b 4096 -d "$R" "$IMG" "$SIZE"
e2fsck -fy "$IMG" >/dev/null || [ $? -le 1 ]
zstd -q -T0 -3 --rm "$IMG"
(cd "$OUT" && sha256sum "$(basename "$IMG").zst" > "$(basename "$IMG").zst.sha256")
cp "$W/root/var/lib/loa-build-packages.txt" "$OUT/omarchy-scratch-$STAMP.packages.txt" 2>/dev/null || true
if findmnt -rn -o TARGET | grep -q "^$W"; then echo "mounts left under $W; not removing it"; else rm -rf --one-file-system "$W"; fi
log "done: $IMG.zst ($(du -h "$IMG.zst" | cut -f1))"
