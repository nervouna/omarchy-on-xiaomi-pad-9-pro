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
# /usr/share/loa/hypr/loa.lua, loaded at the end of Omarchy's defaults
# (default/hypr/omarchy.lua; the loader is added by /usr/lib/loa/omarchy-post-upgrade.sh).
set -e
D=$(cd "$(dirname "$0")/.." && pwd)
MODE=apply; [ "$1" = --diff ] && MODE=diff
(cd "$D" && COPYFILE_DISABLE=1 tar -cf - rootfs-overlay user-defaults) | "$D/tools/tssh" 'cat > /run/loa-overlay.tar'
# Your SSH public key (keys/*.pub, git-ignored) is added to root's authorized_keys;
# the repo ships no key.
PUB=$(cat "$D"/keys/*.pub 2>/dev/null | head -1)
"$D/tools/tssh" "sh -s $MODE '$PUB'" < "$D/tools/overlay-install.sh"
