#!/bin/bash
# Install Omarchy's bundled app icons into the hicolor theme under the names its
# .desktop entries use (Icon=basecamp, disk-usage, omarchy-discord, ...). A real
# Omarchy package owns these under /usr/share/icons/hicolor; this rootfs got the
# Omarchy tree copied to /usr/share/omarchy instead, so nothing put them there.
# Naming = omarchy-webapp-install's icon_name_from_ref/safe_icon_name. Idempotent.
set -euo pipefail
src=/usr/share/omarchy/applications/icons
dst=/usr/share/icons/hicolor/512x512/apps
safe_icon_name() {
  printf '%s\n' "$1" | tr '[:upper:]' '[:lower:]' | sed 's/[^[:alnum:]]\+/-/g; s/^-//; s/-$//'
}
install -d -m 0755 "$dst"
for f in "$src"/*.png; do
  name=$(basename "$f"); name=${name%.*}
  case $name in omarchy-*) icon=$name ;; *) icon=$(safe_icon_name "$name") ;; esac
  install -m 0644 "$f" "$dst/$icon.png"
  echo "$icon"
done
gtk-update-icon-cache -q -f -t /usr/share/icons/hicolor || true
