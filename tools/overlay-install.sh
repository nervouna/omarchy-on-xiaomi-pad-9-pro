#!/bin/sh
# Target side of tools/apply-overlay.sh: installs /run/loa-overlay.tar (a tar of
# rootfs-overlay/ + user-defaults/) into the running root. Also run inside a
# fresh root by builder/build-image.sh (via chroot). Args: MODE (apply|diff),
# optional SSH public key for root. Env: LOA_OVERLAY_BACKUP (optional) is the
# backup directory instead of /var/backups/loa-overlay/<time>.
set -e
MODE=$1; PUB=$2
S=/run/loa-overlay; rm -rf $S; mkdir -p $S
tar --warning=no-timestamp --warning=no-unknown-keyword -xf /run/loa-overlay.tar -C $S --no-same-owner
rm -f /run/loa-overlay.tar
# loa-update names the backup directory itself (LOA_OVERLAY_BACKUP), recorded
# before anything is replaced; otherwise it is the time.
BK=${LOA_OVERLAY_BACKUP:-/var/backups/loa-overlay/$(date +%Y%m%d-%H%M%S)}
# Under loa-update, each backup is on disk before its original is replaced: a
# rollback after a crash mid-install must not copy back an empty file.
backup() {
    [ -e "$1" ] || [ -L "$1" ] || return 0
    mkdir -p "$BK$(dirname "$1")"; cp -a "$1" "$BK$1"
    [ -z "${LOA_OVERLAY_BACKUP:-}" ] || sync
}
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

# 2b. Omarchy's branding defaults (its full installer seeds them; ours doesn't
# run it): the screensaver and About logos, as `omarchy branding ... reset` does.
for pair in screensaver.txt:logo.txt about.txt:icon.txt; do
    t=/home/omarchy/.config/omarchy/branding/${pair%%:*}; src=/usr/share/omarchy/${pair#*:}
    [ -e "$t" ] || [ ! -f "$src" ] && continue
    n=$((n + 1)); echo "seed $t"
    [ $MODE = diff ] && continue
    $U sh -c "mkdir -p '$(dirname "$t")' && cp '$src' '$t'"
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

# 3b. Omarchy's idle lock off, once. Its shell locks after idle.lock seconds
# (default 300, the same moment hypridle switches the screen off); the lock ends
# the screensaver, the shell takes that for activity and runs omarchy-system-wake,
# which lights the screen again, every 5 minutes for as long as the tablet is
# idle. The tablet has no lock to speak of (no password, no on-screen keyboard at
# the lock screen), so the default goes to 0 = disabled. Only the untouched
# default is changed, and only once (marker): a lock the user sets later stays.
J=/home/omarchy/.config/omarchy/shell.json
M=/var/lib/loa/idle-lock-default-off
if [ -f $J ] && [ ! -e $M ] && [ "$(jq -r '.idle.lock // 300' $J 2>/dev/null)" = 300 ]; then
    n=$((n + 1)); echo "shell.json: idle.lock 300 -> 0 (Omarchy's idle lock relights the screen)"
    if [ $MODE = apply ]; then
        backup $J
        $U sh -c "jq '.idle.lock = 0' $J > $J.loa && mv $J.loa $J"
        mkdir -p /var/lib/loa; : > $M
    fi
fi

# 3c. btop's CPU temperature sensor. With cpu_sensor = "Auto" btop takes any
# thermal zone with "cpu" in its name, and here that can be cpu-hw-trip-0/1,
# which always read 95 C (a trip threshold, not a temperature). Point it at the
# first prime core instead. Only an untouched "Auto" is changed.
B=/home/omarchy/.config/btop/btop.conf
if [ -f $B ] && grep -q '^cpu_sensor = "Auto"' $B; then
    z=$(grep -lx cpu-1-0-0 /sys/class/thermal/thermal_zone*/type 2>/dev/null | head -1 | sed 's|.*thermal_zone\([0-9]*\)/type|\1|')
    n=$((n + 1)); echo "btop.conf: cpu_sensor Auto -> thermal${z:-33}/cpu-1-0-0"
    if [ $MODE = apply ]; then
        backup $B
        $U sed -i "s|^cpu_sensor = \"Auto\"|cpu_sensor = \"thermal${z:-33}/cpu-1-0-0\"|" $B
    fi
fi

# 4c. Omarchy patches dropped from the overlay (fixed in Omarchy 4.5). A dropped
# patch that is still applied is taken out again first, or the installed file
# would keep our change until the next Omarchy package update. An install older
# than 4.5 (or the copied tree, which has no package) still needs them: there
# they stay until it is updated.
ov=$(pacman -Q omarchy 2>/dev/null | cut -d' ' -f2)
for t in /usr/share/loa/omarchy/patches/0006-shell-let-cloned-menus-see-their-kinds-through-the-panel-model.patch \
         /usr/share/loa/omarchy/patches/0007-font-set-restore-the-notification-glyph-and-keep-pgrep-quiet.patch \
         /usr/share/loa/omarchy/patches/0008-restart-shell-wait-for-the-notification-service.patch; do
    [ -e $t ] || continue
    if [ -z "$ov" ] || [ "$(vercmp "$ov" 4.5.0)" -lt 0 ]; then
        echo "kept $t (Omarchy ${ov:-without a package} still needs it; update to 4.5 first)"; continue
    fi
    n=$((n + 1)); echo "remove dropped $t"
    [ $MODE = apply ] || continue
    for base in /usr/share/omarchy /usr; do
        if patch -d $base -p1 -s -f --fuzz=0 -R --dry-run < $t >/dev/null 2>&1; then
            patch -d $base -p1 -s -f --fuzz=0 -R --no-backup-if-mismatch -r - < $t >/dev/null 2>&1 &&
                echo "reverted $(basename $t) in $base"
            break
        fi
    done
    backup $t; rm -f $t
done

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

# 4b. Legacy: hand-made links for Omarchy's user units from the copied-tree days.
# The packaged units live in /usr/lib/systemd/user and the overlay now enables
# them for every user (/etc/systemd/user/default.target.wants), so the old
# /etc/systemd/user/<unit> links into /usr/share/omarchy/default (which shadow
# the packaged unit) and the per-user enables go. Left alone on a tablet still
# on the copied tree, where the packaged units don't exist.
for u in bt-agent.service omarchy-fcitx5.service; do
    [ -f /usr/lib/systemd/user/$u ] || continue
    t=/etc/systemd/user/$u
    if [ -L $t ]; then case $(readlink $t) in /usr/share/omarchy/default/systemd/user/*)
        n=$((n + 1)); echo "remove legacy $t (packaged unit in /usr/lib/systemd/user)"
        [ $MODE = apply ] && { backup $t; rm -f $t; } ;; esac; fi
    t=/home/omarchy/.config/systemd/user/default.target.wants/$u
    [ -L $t ] && [ "$(readlink $t)" = /etc/systemd/user/$u ] || continue
    n=$((n + 1)); echo "remove legacy $t (enabled for every user in /etc)"
    [ $MODE = apply ] && { backup $t; rm -f $t; }
done
cd /; rm -rf $S

if [ $MODE = diff ]; then echo "$n change(s) pending (nothing written)"; exit 0; fi
[ -d $BK ] && echo "backups of replaced files: $BK"

# 5. Modes, accounts, units.
chmod 755 /usr/lib/loa/*.sh /usr/lib/loa/busybox /usr/lib/loa/loa-helper /usr/lib/loa/loa-thp-launcher /usr/lib/loa/loa-xtouch /usr/lib/loa/android-run /usr/lib/loa/loa-splash-off
mkdir -p /root/.ssh; chmod 700 /root/.ssh
if [ -n "$PUB" ] && ! grep -qF "$PUB" /root/.ssh/authorized_keys 2>/dev/null; then
    echo "$PUB" >> /root/.ssh/authorized_keys; echo "added your SSH key"
fi
chmod 600 /root/.ssh/authorized_keys 2>/dev/null || true
/usr/lib/loa/setup-wlan-files.sh
# Tablets installed from a cloned image already carry their vendor files: mark
# them imported so loa-vendor-import.service doesn't redo it. (A from-scratch
# image has no modules yet, so it gets the first-boot import.)
K=$(uname -r)
[ -e /usr/lib/loa/vendor-imported ] || [ ! -d /usr/lib/modules/$K/vendor ] || echo "pre-existing" > /usr/lib/loa/vendor-imported
/usr/lib/loa/setup-omarchy-repo.sh
# What the pacman hooks do for later installs, for what is already installed:
# setuid sandbox helpers, the menu's install entries that can't work here.
pacman -Qlq | grep '/chrome-sandbox$' | /usr/lib/loa/chrome-sandbox.sh
python3 /usr/lib/loa/omarchy-menu-audit.py --apply || echo "the menu audit failed"
# Warm reset after a panic (keeps the pstore log); the tmpfiles rule does it at boot.
echo warm > /sys/kernel/reboot/mode 2>/dev/null || true
systemctl restart systemd-journald
chown root:root /etc/sudoers.d/10-loa-wheel; chmod 0440 /etc/sudoers.d/10-loa-wheel; visudo -c >/dev/null
# rfkill: /dev/rfkill gets no seat ACL here (sessions have no seat), and
# omarchy-bluetooth-power switches Bluetooth with rfkill as the user.
usermod -aG wheel,rfkill omarchy
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
    loa-autobrightness loa-sleepd earlyoom loa-zram loa-cpufreq loa-batterysecret loa-pen systemd-pstore loa-crashdump loa-vendor-import >/dev/null 2>&1
# avahi-daemon (mDNS, <hostname>.local): Omarchy's installer enables it; ours
# doesn't run that installer. On its own: a missing unit fails the whole enable.
systemctl enable avahi-daemon >/dev/null 2>&1 || echo "avahi-daemon not installed: no <hostname>.local"
echo "overlay applied ($n change(s))"
