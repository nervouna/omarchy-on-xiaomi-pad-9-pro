#!/bin/sh
# Build an installable root filesystem image from a working tablet (run on the Mac,
# tablet booted into native Omarchy from the `omarchy` partition, USB connected).
#
#   tools/make-image.sh --clean    [--apply]   golden image: no personal data/secrets
#   tools/make-image.sh --personal [--apply]   full clone minus per-device identity
#   --reset-hypr (with --clean): personal Hyprland files (input, bindings, looknfeel,
#   monitors, autostart) become Omarchy's stock templates, for someone else's tablet.
#   hyprland.lua keeps the loa.lua loader line, so the device settings still load.
#
# Without --apply it only reports what would be copied/scrubbed (sizes).
# The image is staged on the tablet's `ramdump` partition (17 GiB): its current
# contents (the old pre-move root, `omarchy-old`) are DESTROYED. The result is
# streamed to images/omarchy-<mode>-<date>.img.zst (e2image: only used blocks
# carry data, so stale blocks never leak into the image).
# Install it on another tablet with tools/install.sh.
set -e
D=$(cd "$(dirname "$0")/.." && pwd)
MODE=""; APPLY=0; RESET=0
for a in "$@"; do case $a in
    --clean) MODE=clean;; --personal) MODE=personal;; --apply) APPLY=1;; --reset-hypr) RESET=1;;
    *) echo "unknown argument $a"; exit 2;; esac; done
[ "$RESET" = 1 ] && [ "$MODE" != clean ] && { echo "--reset-hypr needs --clean"; exit 2; }
[ -n "$MODE" ] || { sed -n '2,15p' "$0"; exit 2; }
OUT=$D/images/omarchy-$MODE-$(date +%Y%m%d).img.zst

REMOTE=$(cat <<'EOF'
set -e
MODE=$1; APPLY=$2; RESET=${3:-0}
part() { for u in /sys/class/block/*/uevent; do grep -q "^PARTNAME=$1\$" "$u" && { echo /dev/$(sed -n 's/^DEVNAME=//p' "$u"); return; }; done; }
ROOT=$(findmnt -no SOURCE /); STAGE=$(part ramdump)
[ "$ROOT" = "$(part omarchy)" ] || { echo "refusing: / must be the omarchy partition (is $ROOT)"; exit 1; }
[ -b "$STAGE" ] && [ "$STAGE" != "$ROOT" ] || { echo "no usable ramdump partition"; exit 1; }
findmnt "$STAGE" >/dev/null && { echo "$STAGE is mounted"; exit 1; }

# Always excluded: per-device identity, logs, caches, transient state.
# (SSH host keys and the pacman keyring stay so SSH works on first boot;
#  tools/personalize.sh regenerates both on the new tablet.)
EXCL="./etc/machine-id ./var/log/journal/* ./var/cache/pacman/pkg/*
./var/lib/systemd/random-seed ./usr/lib/firmware/wlan/qca_cld/wcn7750/wlan_mac.bin
./tmp/* ./var/tmp/* ./swapfile ./lost+found/*"
if [ "$MODE" = clean ]; then
    # Secrets and personal data. /home/omarchy is copied by whitelist below.
    EXCL="$EXCL ./home/* ./root/* ./etc/NetworkManager/system-connections/*
./var/lib/bluetooth/* ./var/lib/NetworkManager/*
./var/lib/upower/* ./var/lib/systemd/coredump/*"
fi
set -f   # exclude patterns contain *: no pathname expansion while building/using them
X=""; for e in $EXCL; do X="$X --exclude=$e"; done
set +f
# Omarchy user config whitelist (clean mode): what makes the desktop work,
# nothing that holds logins, messages, browser profiles or keys.
HOMEKEEP=".bashrc .bash_profile .XCompose .config/hypr .config/omarchy .config/pipewire
.config/wireplumber .config/fcitx5 .config/systemd .config/chromium-flags.conf .config/uwsm
.config/foot .config/alacritty .config/ghostty .config/kitty .config/btop .config/fastfetch
.config/mako .config/walker .config/elephant .config/environment.d .config/fontconfig
.config/gtk-3.0 .config/gtk-4.0 .config/xdg-terminals.list .config/mimeapps.list
.config/mise/config.toml .config/starship.toml .config/git/config .config/nvim
.config/user-dirs.dirs .config/dconf .config/tmux .config/imv .config/voxtype .config/xournalpp
.local/share/applications .local/share/icons .local/share/fonts .local/state/omarchy"

if [ "$APPLY" != 1 ]; then
    echo "== dry run ($MODE): root usage"; df -h / | tail -1
    [ "$RESET" = 1 ] && echo "== --reset-hypr: input/bindings/looknfeel/monitors/autostart.lua -> Omarchy templates"
    echo "== excluded patterns:"; echo "$EXCL" | tr ' ' '\n' | sed 's/^/   /'
    if [ "$MODE" = clean ]; then
        echo "== /home/omarchy kept (whitelist):"
        cd /home/omarchy && for k in $HOMEKEEP; do [ -e "$k" ] && du -sh "$k"; done 2>/dev/null | sed 's/^/   /'
        echo "== /home/omarchy NOT kept (top level):"
        du -sh .[!.]* * 2>/dev/null | sort -h | tail -25 | sed 's/^/   /'
    fi
    exit 0
fi

echo "staging on $STAGE (ramdump): wiping it"
mkfs.ext4 -q -F -L omarchy -b 4096 "$STAGE"
M=/run/loa-stage; mkdir -p $M; mount "$STAGE" $M
trap 'umount $M 2>/dev/null || true' EXIT
sync
set -f; eval "tar --one-file-system --xattrs --acls --numeric-owner $X -cpf - -C / ." | tar --xattrs --acls --numeric-owner -xpf - -C $M; set +f
if [ "$MODE" = clean ]; then
    mkdir -p $M/home/omarchy $M/root/.ssh; chmod 700 $M/home/omarchy $M/root $M/root/.ssh
    chown 1000:1000 $M/home/omarchy
    (cd /home/omarchy && for k in $HOMEKEEP; do [ -e "$k" ] && echo "$k"; done | tar --xattrs --numeric-owner -cpf - -T -) | tar --xattrs --numeric-owner -xpf - -C $M/home/omarchy
    # tar -T creates missing parent dirs (.config, .local, .local/share ...) as root:
    # hand everything under the home back to the user, or apps can't create
    # their data dirs (create_dir_all / singleton lock failures).
    find $M/home/omarchy -xdev -user 0 -exec chown -h 1000:1000 {} +
    if [ "$RESET" = 1 ]; then
        for f in input bindings looknfeel monitors autostart; do
            install -o 1000 -g 1000 -m 644 /usr/share/omarchy/config/hypr/$f.lua $M/home/omarchy/.config/hypr/$f.lua
        done
        rm -f $M/home/omarchy/.config/hypr/*.bak.* $M/home/omarchy/.config/hypr/*.before-*
        echo "reset personal Hyprland files to Omarchy templates"
    fi
    # Omarchy state: keep theme/toggles, drop clipboard history and notifications.
    rm -rf $M/home/omarchy/.local/state/omarchy/clipboard-images $M/home/omarchy/.local/state/omarchy/notifications
    cp -p /root/.ssh/authorized_keys $M/root/.ssh/ 2>/dev/null || true
    # Lock the user's password (the new owner sets one: tools/tssh -t passwd omarchy).
    sed -i 's/^\(omarchy\):[^:]*:/\1:!:/' $M/etc/shadow
fi
: > $M/etc/machine-id                      # systemd generates it on first boot
mkdir -p $M/loa && echo 0 > $M/loa/boot-attempts
rm -f $M/loa/next-boot-android
sync; umount $M; trap - EXIT
e2fsck -fy "$STAGE" >/dev/null || [ $? -le 1 ]
dumpe2fs -h "$STAGE" 2>/dev/null | grep -E "^(Block count|Free blocks)"
echo "STREAM $(blkid -s UUID -o value "$STAGE")"
EOF
)

if [ $APPLY != 1 ]; then
    "$D/tools/tssh" "sh -s $MODE 0 $RESET" <<EOF
$REMOTE
EOF
    exit 0
fi
LOG=$(mktemp)
"$D/tools/tssh" "sh -s $MODE 1 $RESET" <<EOF | tee "$LOG"
$REMOTE
EOF
UUID=$(sed -n 's/^STREAM //p' "$LOG"); rm -f "$LOG"
[ -n "$UUID" ] || { echo "staging failed"; exit 1; }
mkdir -p "$D/images"
echo "streaming image to $OUT"
# Stream only if it's still the tablet we staged on (two tablets share the
# USB network address): the staged filesystem UUID must match.
"$D/tools/tssh" "sh -s $UUID" <<'EOF' | zstd -T0 -3 -q -o "$OUT"
S=$(for u in /sys/class/block/*/uevent; do grep -q "^PARTNAME=ramdump$" "$u" && echo /dev/$(sed -n "s/^DEVNAME=//p" "$u"); done)
[ "$(blkid -s UUID -o value "$S")" = "$1" ] || { echo "tablet changed since staging" >&2; exit 1; }
e2image -ra "$S" -
EOF
[ -s "$OUT" ] && zstd -t -q "$OUT" || { echo "stream failed"; rm -f "$OUT"; exit 1; }
chmod 600 "$OUT"
zstd -t -q "$OUT" && ls -lh "$OUT"
(cd "$(dirname "$OUT")" && shasum -a 256 "$(basename "$OUT")") | tee "$OUT.sha256"
if [ $MODE = personal ]; then echo "NOTE: personal image holds logins, keys and messages. Keep it private."; fi
