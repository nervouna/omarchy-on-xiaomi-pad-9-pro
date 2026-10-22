#!/bin/bash
# Runs inside the new root (builder/build-image.sh, via arch-chroot). Configures
# the system the way the working tablets are: user, locale, pacman, Omarchy
# (installed from its packages), the LoA overlay. Arg: optional SSH public key
# for root.
set -Eeuo pipefail
PUB=${1:-}
B=/var/tmp/loa-build
H=/home/omarchy

# pacman: keyring, patched Aquamarine (held back by IgnorePkg), AUR extras.
pacman-key --init >/dev/null 2>&1
pacman-key --populate >/dev/null 2>&1
sed -i 's/^#\?IgnorePkg *=.*/IgnorePkg = aquamarine/' /etc/pacman.conf
LOA_AQUAMARINE=1 pacman -U --noconfirm $B/aquamarine-*.pkg.tar.zst
if ls $B/fakeroot-tcp-*.pkg.tar.zst >/dev/null 2>&1; then
    pacman -Rdd --noconfirm fakeroot     # the kernel has no SysV IPC
    pacman -U --noconfirm $B/fakeroot-tcp-*.pkg.tar.zst
fi
ls $B/yay-bin-*.pkg.tar.zst >/dev/null 2>&1 && pacman -U --noconfirm $B/yay-bin-*.pkg.tar.zst

# Base system.
sed -i 's/^#en_US.UTF-8 UTF-8/en_US.UTF-8 UTF-8/' /etc/locale.gen
locale-gen >/dev/null
echo LANG=en_US.UTF-8 > /etc/locale.conf
ln -sfn /usr/share/zoneinfo/UTC /etc/localtime
echo shuntian > /etc/hostname
systemctl set-default graphical.target
useradd --create-home --uid 1000 --user-group --shell /bin/bash --comment Omarchy omarchy
usermod -aG wheel,audio,input,render,video,seat omarchy
passwd -l omarchy >/dev/null     # the owner sets one: tools/tssh -t passwd omarchy

# Omarchy: its packages put the commands in /usr/bin and the user's starting
# config in /etc/skel, which useradd copied above (its migrations marked done,
# as on a fresh Omarchy install). Then the default theme.
install -d -m 755 $H/.local/state/omarchy/current $H/.config/omarchy/themes \
    $H/Downloads $H/Pictures $H/Videos $H/Projects
install -D -m 644 /usr/share/omarchy/default/voxtype/config.toml $H/.config/voxtype/config.toml
fc-cache -f >/dev/null
chown -R 1000:1000 $H
runuser -u omarchy -- env HOME=$H USER=omarchy LOGNAME=omarchy \
    PATH=/usr/local/sbin:/usr/local/bin:/usr/bin \
    OMARCHY_PATH=/usr/share/omarchy OMARCHY_THEME_HEADLESS=1 OMARCHY_THEME_SKIP_BACKGROUND=1 \
    omarchy-theme-set tokyo-night
[ -s $H/.local/state/omarchy/current/theme.name ] || { echo "theme init failed"; exit 1; }
for bg in $H/.local/state/omarchy/current/theme/backgrounds/*; do
    [ -f "$bg" ] && { ln -sfn "$bg" $H/.local/state/omarchy/current/background; break; }
done
ln -sfn $H/.local/state/omarchy/current $H/.config/omarchy/current
: > $H/.config/gtk-3.0/bookmarks 2>/dev/null || { install -d $H/.config/gtk-3.0; : > $H/.config/gtk-3.0/bookmarks; }
for d in Downloads Projects Pictures Videos; do echo "file://$H/$d $d" >> $H/.config/gtk-3.0/bookmarks; done
chown -R 1000:1000 $H; chmod 700 $H

# The LoA overlay, exactly as tools/apply-overlay.sh installs it on a tablet.
cp $B/loa-overlay.tar /run/loa-overlay.tar   # the build mounts a fresh /run
sh $B/overlay-install.sh apply "$PUB"
/usr/lib/loa/omarchy-post-upgrade.sh   # our Omarchy patches (the pacman hook came with the overlay)

# Identity and leftovers: each tablet generates its own (tools/personalize.sh).
pacman -Q > /var/lib/loa-build-packages.txt
rm -rf /var/cache/pacman/pkg/* /var/log/* /var/backups/loa-overlay /root/.cache /root/.gnupg \
    $H/.cache $H/.bash_history /etc/ssh/ssh_host_*
: > /etc/machine-id
echo "target configured"
