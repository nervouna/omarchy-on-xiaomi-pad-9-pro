#!/bin/sh
# PostTransaction for the omarchy/omarchy-settings packages (95-loa-omarchy.hook):
#  1. re-apply /usr/share/loa/omarchy/patches/*.patch (the package update just
#     replaced the patched files); a patch that no longer applies is reported;
#  2. mark the migrations in /usr/share/loa/omarchy/migrations-skip as done;
#  3. list pending migrations that touch boot, kernel modules, sshd or groups,
#     for review before `omarchy-migrate` runs them (Omarchy detects this tablet
#     as a Snapdragon laptop, aarch64-qualcomm);
#  4. drop /usr/local/bin links into /usr/share/omarchy/bin left by the copied
#     (pre-package) install: the package puts its commands in /usr/bin, and
#     links to commands upstream has since removed would dangle;
#  5. hide the menu's install entries that can't work on this tablet
#     (omarchy-menu-audit.py: packages missing for aarch64, menu-hide).
# Never fails the transaction.
L=/usr/share/loa/omarchy

# Paths in the patches are relative to the Omarchy tree; its bin/ is a set of
# links to /usr/bin, so bin/ patches apply with base /usr. No fuzz: a fuzzy
# match would apply an already-applied hunk a second time elsewhere. -f, not
# --batch: --batch turns a patch that "looks reversed" around by itself, which
# defeats the already-applied check.
P="-p1 -s -f --fuzz=0"
for p in "$L"/patches/*.patch; do
    [ -f "$p" ] || continue
    n=$(basename "$p")
    done=""
    for base in /usr/share/omarchy /usr; do
        if patch -d $base $P -R --dry-run < "$p" >/dev/null 2>&1; then
            done=1; break
        fi
        if patch -d $base $P --dry-run < "$p" >/dev/null 2>&1; then
            patch -d $base $P --no-backup-if-mismatch -r - < "$p" >/dev/null 2>&1 &&
                { echo "LoA: applied $n"; done=1; break; }
        fi
    done
    [ -n "$done" ] || echo "LoA: WARNING: $n no longer applies to this Omarchy (fixed upstream? update $L/patches)"
done

for home in /home/*; do
    st=$home/.local/state/omarchy
    [ -d "$st" ] || continue
    owner=$(stat -c %u:%g "$home")
    install -d -o "${owner%:*}" -g "${owner#*:}" "$st/migrations"
    grep -v '^#' "$L/migrations-skip" | while read -r id reason; do
        [ -n "$id" ] && [ -f "/usr/share/omarchy/migrations/$id.sh" ] && [ ! -e "$st/migrations/$id.sh" ] || continue
        install -m 644 -o "${owner%:*}" -g "${owner#*:}" /dev/null "$st/migrations/$id.sh"
        echo "LoA: skipped migration $id for $(basename "$home"): $reason"
    done
    for m in /usr/share/omarchy/migrations/*.sh; do
        [ -f "$m" ] && [ ! -e "$st/migrations/$(basename "$m")" ] || continue
        grep -qE 'qualcomm|qcom|limine|mkinitcpio|modprobe|sshd|gpasswd|usermod|systemctl +(disable|mask)' "$m" &&
            echo "LoA: review pending migration $(basename "$m" .sh) ($(basename "$home")): $(grep -m1 '^echo' "$m" | cut -c7- | tr -d '"')"
    done
done

for f in /usr/local/bin/omarchy*; do
    [ -L "$f" ] || continue
    case $(readlink "$f") in /usr/share/omarchy/bin/*) rm -f "$f" ;; esac
done

python3 /usr/lib/loa/omarchy-menu-audit.py --apply || echo "LoA: WARNING: the menu audit failed"
exit 0
