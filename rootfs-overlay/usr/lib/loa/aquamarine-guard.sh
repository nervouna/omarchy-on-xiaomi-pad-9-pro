#!/bin/sh
# PreTransaction guard for aquamarine (10-loa-aquamarine-guard.hook). Our own
# build is installed with LOA_AQUAMARINE=1 in pacman's environment.
[ "${LOA_AQUAMARINE:-}" = 1 ] && exit 0
cat >&2 <<'EOF'
LoA: this transaction would replace aquamarine with the stock package.
The tablet's display needs the patched build (split primary plane, DMA-heap
scanout, forced MODE_ID); without it the panel underruns or stays dark.
Usually a new Hyprland needs a newer Aquamarine. Rebuild ours at the version it
needs (docs/maintenance.md, "Aquamarine"), install it with
  sudo LOA_AQUAMARINE=1 pacman -U aquamarine-<version>-<rel>-aarch64.pkg.tar.zst
then run the update again. Nothing was changed.
EOF
exit 1
