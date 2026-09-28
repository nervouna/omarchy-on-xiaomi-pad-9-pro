#!/bin/sh
# Enable Omarchy's own pacman repository ([omarchy], pkgs.omarchy.org), which its
# installer menus expect ("target not found" without it). Idempotent; run by
# tools/apply-overlay.sh and again by tools/personalize.sh after the keyring reset.
set -e
KEY=/usr/share/loa/pacman/omarchy.asc
FPR=40DFB630FF42BCFFB047046CF0134EE680CAC571
got=$(gpg --show-keys --with-colons "$KEY" 2>/dev/null | awk -F: '$1 == "fpr" {print $10; exit}')
[ "$got" = "$FPR" ] || { echo "omarchy repo: unexpected key fingerprint '$got'" >&2; exit 1; }
if ! pacman-key --list-keys "$FPR" >/dev/null 2>&1; then
    pacman-key --add "$KEY" >/dev/null 2>&1
    pacman-key --lsign-key "$FPR" >/dev/null 2>&1
    echo "omarchy repo: signing key added"
fi
if ! grep -q '^\[omarchy\]' /etc/pacman.conf; then
    printf '\n[omarchy]\nServer = https://pkgs.omarchy.org/stable/$arch\n' >> /etc/pacman.conf
    echo "omarchy repo: added to /etc/pacman.conf (run pacman -Sy)"
fi
