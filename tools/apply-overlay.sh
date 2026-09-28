#!/bin/sh
# Apply the LoA files to the Omarchy root on the tablet over SSH. Idempotent.
#   tools/apply-overlay.sh          apply
#   tools/apply-overlay.sh --diff   show what would change, change nothing
#
# rootfs-overlay/  system files the port OWNS: installed/updated; a file that
#                  differs is backed up to /var/backups/loa-overlay/<time>/ first.
# user-defaults/   files the user may customise: installed only if MISSING,
#                  never overwritten.
# Personal Hyprland config is never touched: device settings live in
# /usr/share/loa/hypr/loa.lua, loaded by one line in ~/.config/hypr/hyprland.lua
# (added if missing).
set -e
D=$(cd "$(dirname "$0")/.." && pwd)
MODE=apply; [ "$1" = --diff ] && MODE=diff
(cd "$D" && COPYFILE_DISABLE=1 tar -cf - rootfs-overlay user-defaults) | "$D/tools/tssh" 'cat > /run/loa-overlay.tar'
# Your SSH public key (keys/*.pub, git-ignored) is added to root's authorized_keys;
# the repo ships no key.
PUB=$(cat "$D"/keys/*.pub 2>/dev/null | head -1)
"$D/tools/tssh" "sh -s $MODE '$PUB'" <<'EOF'
set -e
MODE=$1; PUB=$2
S=/run/loa-overlay; rm -rf $S; mkdir -p $S
tar --warning=no-timestamp --warning=no-unknown-keyword -xf /run/loa-overlay.tar -C $S --no-same-owner
rm -f /run/loa-overlay.tar
BK=/var/backups/loa-overlay/$(date +%Y%m%d-%H%M%S)
backup() { [ -e "$1" ] || [ -L "$1" ] || return 0; mkdir -p "$BK$(dirname "$1")"; cp -a "$1" "$BK$1"; }
U="setpriv --reuid=1000 --regid=1000 --init-groups"
n=0

# 1. System files (owned by the port).
cd $S/rootfs-overlay
for f in $(find . \( -type f -o -type l \) | sed 's|^\.||' | sort); do
    if [ -L ".$f" ]; then
        [ -L "$f" ] && [ "$(readlink "$f")" = "$(readlink ".$f")" ] && continue
    else
        [ -f "$f" ] && [ ! -L "$f" ] && cmp -s ".$f" "$f" && continue
    fi
    n=$((n + 1))
    if [ $MODE = diff ]; then
        if [ -f "$f" ] && [ ! -L ".$f" ]; then echo "~ $f"; diff -u "$f" ".$f" | sed -n '3,40p'; else echo "+ $f"; fi
        continue
    fi
    backup "$f"; mkdir -p "$(dirname "$f")"; rm -f "$f"; cp -a ".$f" "$f"; echo "updated $f"
done

# 2. User defaults: seed only if missing, as the user (no root-owned dirs in $HOME).
cd $S/user-defaults
for f in $(find . -type f | sed 's|^\.||' | sort); do
    [ -e "$f" ] && continue
    n=$((n + 1)); echo "seed $f"
    [ $MODE = diff ] && continue
    $U sh -c "mkdir -p '$(dirname "$f")' && cp '.$f' '$f'"
done

# 3. One line in the user's hyprland.lua loads the device settings.
H=/home/omarchy/.config/hypr/hyprland.lua
L='dofile("/usr/share/loa/hypr/loa.lua")'
if [ -f $H ] && ! grep -qF "$L" $H; then
    n=$((n + 1)); echo "hyprland.lua: add $L after Omarchy's defaults"
    if [ $MODE = apply ]; then
        backup $H
        $U python3 - "$H" "$L" <<'PY'
import sys
p, line = sys.argv[1], sys.argv[2]
s = open(p).read()
anchor = 'require("default.hypr.omarchy")'
block = "\n-- LoA device settings (tablet panel, touch, keys, session); personal files below win.\n" + line + "\n"
s = s.replace(anchor, anchor + block, 1) if anchor in s else s + block
open(p, "w").write(s)
PY
    fi
fi

# 4a. Legacy system files dropped from the overlay.
for t in /usr/share/loa/X11/Xresources /usr/lib/loa/loa-xresources.sh; do
    [ -e $t ] || continue
    n=$((n + 1)); echo "remove dropped $t"
    [ $MODE = apply ] && { backup $t; rm -f $t; rmdir "$(dirname $t)" 2>/dev/null || true; }
done

# 4. Legacy: LoA drop-ins that used to live in the home dir (now in /etc).
for f in .config/pipewire/pipewire.conf.d/50-loa-speakers.conf .config/pipewire/pipewire.conf.d/51-loa-mic.conf \
         .config/pipewire/client.conf.d/60-loa-no-client-rt.conf \
         .config/wireplumber/wireplumber.conf.d/50-loa-disable-asoc.conf \
         .config/wireplumber/wireplumber.conf.d/51-loa-no-v4l2.conf \
         .config/wireplumber/wireplumber.conf.d/52-loa-bluez-no-seat.conf; do
    t=/home/omarchy/$f; [ -e $t ] || continue
    n=$((n + 1)); echo "remove legacy $t (now in /etc)"
    [ $MODE = apply ] && { backup $t; rm -f $t; }
done
cd /; rm -rf $S

if [ $MODE = diff ]; then echo "$n change(s) pending (nothing written)"; exit 0; fi
[ -d $BK ] && echo "backups of replaced files: $BK"

# 5. Modes, accounts, units.
chmod 755 /usr/lib/loa/*.sh /usr/lib/loa/busybox /usr/lib/loa/loa-helper /usr/lib/loa/loa-xtouch /usr/lib/loa/android-run /usr/lib/loa/loa-splash-off
mkdir -p /root/.ssh; chmod 700 /root/.ssh
if [ -n "$PUB" ] && ! grep -qF "$PUB" /root/.ssh/authorized_keys 2>/dev/null; then
    echo "$PUB" >> /root/.ssh/authorized_keys; echo "added your SSH key"
fi
chmod 600 /root/.ssh/authorized_keys 2>/dev/null || true
/usr/lib/loa/setup-wlan-files.sh
/usr/lib/loa/setup-omarchy-repo.sh
# Warm reset after a panic (keeps the pstore log); the tmpfiles rule does it at boot.
echo warm > /sys/kernel/reboot/mode 2>/dev/null || true
systemctl restart systemd-journald
chown root:root /etc/sudoers.d/10-loa-wheel; chmod 0440 /etc/sudoers.d/10-loa-wheel; visudo -c >/dev/null
usermod -aG wheel omarchy
rm -f /etc/systemd/zram-generator.conf
/usr/lib/loa/install-omarchy-icons.sh >/dev/null
/usr/lib/loa/install-omarchy-font.sh
systemd-hwdb update
systemctl daemon-reload
systemctl unmask NetworkManager >/dev/null 2>&1 || true
systemctl disable iwd >/dev/null 2>&1 || true
systemctl enable loa-mdev loa-modules loa-subsys loa-usb-gadget loa-thp loa-boot-ok loa-desktop seatd sshd \
    systemd-timesyncd serial-getty@ttyGS0 NetworkManager loa-logd loa-android loa-pd-mapper loa-audiopd \
    loa-binder loa-servicemanager loa-suspend loa-audiohal loa-audio-relay loa-mic-relay loa-power-key \
    loa-splash-off loa-thermalhal loa-bthal loa-bluetooth bluetooth loa-sscrpcd loa-keyboard \
    loa-autobrightness loa-sleepd earlyoom loa-zram loa-batterysecret loa-pen systemd-pstore loa-crashdump >/dev/null 2>&1
echo "overlay applied ($n change(s))"
EOF
