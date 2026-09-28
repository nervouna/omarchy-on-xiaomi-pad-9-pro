#!/bin/sh
# Give a freshly installed tablet its own identity (run on the Mac, once, after the
# first native boot of an image made by tools/make-image.sh). Idempotent.
#   tools/personalize.sh [HOSTNAME]        default hostname: shuntian
# - Wi-Fi MAC: copies this tablet's persist/wlan/wlan_mac.bin into the firmware dir
#   (the image carries none; a copied one would clash on the network).
# - machine-id, SSH host keys, pacman keyring: regenerated (never shared).
# - hostname.
# Afterwards: set the user's password (tools/tssh -t passwd omarchy), reboot.
set -e
D=$(cd "$(dirname "$0")/.." && pwd)
H=${1:-shuntian}
"$D/tools/tssh" "sh -s $H" <<'EOF'
set -e
H=$1
part() { for u in /sys/class/block/*/uevent; do grep -q "^PARTNAME=$1\$" "$u" && { echo /dev/$(sed -n 's/^DEVNAME=//p' "$u"); return; }; done; }
F=/usr/lib/firmware/wlan/qca_cld/wcn7750
# Wi-Fi MAC from persist (strictly read-only; loa-android may already have it mounted).
if mountpoint -q /android/persist; then P=/android/persist; else
    P=/run/loa-persist; mkdir -p $P; mount -t ext4 -o ro,noload "$(part persist)" $P; fi
install -m 644 $P/wlan/wlan_mac.bin $F/wlan_mac.bin
[ $P = /run/loa-persist ] && umount $P
echo "wlan MAC: $(head -1 $F/wlan_mac.bin)"
# machine-id
if [ ! -s /etc/machine-id ] || [ "$(cat /etc/machine-id)" = uninitialized ]; then
    systemd-machine-id-setup >/dev/null; fi
echo "machine-id: $(cat /etc/machine-id)"
# SSH host keys (the running session keeps working; reconnect afterwards)
rm -f /etc/ssh/ssh_host_*; ssh-keygen -A >/dev/null; echo "ssh host keys regenerated"
# pacman keyring: new local master key, then trust the distribution keys again.
# `--populate` without names loads every keyring in /usr/share/pacman/keyrings
# (this system has archlinux-keyring and, since 2026-09-27, archlinuxarm-keyring).
[ -e /usr/share/pacman/keyrings/archlinuxarm.gpg ] || { echo "archlinuxarm-keyring missing: not touching the pacman keyring"; exit 1; }
rm -rf /etc/pacman.d/gnupg
pacman-key --init >/dev/null 2>&1
pacman-key --populate >/dev/null 2>&1
echo "pacman keyring re-initialised: $(pacman-key --list-keys 2>/dev/null | grep -c '^pub') keys"
/usr/lib/loa/setup-omarchy-repo.sh   # the keyring reset dropped Omarchy's key
echo "$H" > /etc/hostname; hostname "$H"; echo "hostname: $H"
echo "done: set a password (tools/tssh -t passwd omarchy), then reboot"
EOF
