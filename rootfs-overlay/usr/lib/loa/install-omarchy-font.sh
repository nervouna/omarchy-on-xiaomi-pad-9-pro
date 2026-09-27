#!/bin/sh
# Omarchy's icon font (menu logo U+E900, agent/app icons with iconFont "omarchy")
# ships in /usr/share/omarchy/default/fonts/omarchy/omarchy.ttf; a real Omarchy
# install puts it at /usr/share/fonts/omarchy/omarchy.ttf. This rootfs copied
# Omarchy's files without that step, so the glyphs fell back to other fonts.
# Linked (not copied) so Omarchy updates to the font carry through. Idempotent.
set -e
SRC=/usr/share/omarchy/default/fonts/omarchy/omarchy.ttf
DST=/usr/share/fonts/omarchy/omarchy.ttf
[ -f $SRC ] || { echo "no $SRC"; exit 0; }
[ "$(readlink $DST 2>/dev/null)" = $SRC ] && exit 0
mkdir -p /usr/share/fonts/omarchy
ln -sf $SRC $DST
fc-cache -f /usr/share/fonts/omarchy >/dev/null
echo "installed $DST -> $SRC"
