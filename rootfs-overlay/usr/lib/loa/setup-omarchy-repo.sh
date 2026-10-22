#!/bin/sh
# Keep /etc/pacman.conf on Omarchy's aarch64 channel plus this tablet's one
# delta (IgnorePkg = aquamarine, our patched build). Idempotent; run by
# tools/apply-overlay.sh, tools/personalize.sh (after its keyring reset) and the
# user's pre-refresh-pacman Omarchy hook (after `omarchy-refresh-pacman` copied
# its template over the file).
#
# Older Omarchy builds copied the x86_64 template here ([multilib], no [alarm],
# stable-mirror.omarchy.org): such a file is replaced with the aarch64 one.
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

# The template: Omarchy's own once its package is installed, else our copy.
T=/usr/share/omarchy/default/pacman/aarch64
[ -f $T/pacman-stable.conf ] && [ -f $T/mirrorlist-stable ] || T=/usr/share/loa/pacman
C=/etc/pacman.conf
if ! grep -q '^\[alarm\]' $C || grep -q '^\[multilib\]' $C || ! grep -q '^\[omarchy\]' $C; then
    cp -a $C $C.before-loa-$(date +%Y%m%d%H%M%S)
    cp -a /etc/pacman.d/mirrorlist /etc/pacman.d/mirrorlist.before-loa-$(date +%Y%m%d%H%M%S)
    if [ $T = /usr/share/loa/pacman ]; then
        install -m 644 $T/pacman.conf $C
        install -m 644 $T/mirrorlist /etc/pacman.d/mirrorlist
    else
        install -m 644 $T/pacman-stable.conf $C
        install -m 644 $T/mirrorlist-stable /etc/pacman.d/mirrorlist
    fi
    echo "pacman: Omarchy aarch64 stable channel ($T)"
fi

# Aquamarine carries patches/aquamarine-*.patch; pacman must not replace it
# (/etc/pacman.d/hooks/10-loa-aquamarine-guard.hook aborts if a dependency tries).
if ! grep -q '^IgnorePkg *=.*\baquamarine\b' $C; then
    if grep -q '^IgnorePkg *=' $C; then
        sed -i 's/^\(IgnorePkg *=.*\)$/\1 aquamarine/' $C
    elif grep -q '^#IgnorePkg' $C; then
        sed -i 's/^#IgnorePkg *=.*/IgnorePkg = aquamarine/' $C
    else
        sed -i 's/^\[options\]$/[options]\nIgnorePkg = aquamarine/' $C
    fi
    echo "pacman: IgnorePkg = aquamarine"
fi
