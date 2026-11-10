#!/bin/sh
# Tests for loa-update (rootfs-overlay/usr/local/bin/loa-update), run as root
# inside a scratch copy of the built root: the "Build image" workflow chroots
# into the loop-mounted image. Never on a tablet: it swaps a throwaway key into
# allowed_signers and installs and rolls back bundles.
#   builder/test-loa-update.sh SRC     SRC: a copy of this repository (no .git needed)
set -u
[ -e /run/loa-boot-ok ] && { echo "refusing: this is a booted tablet, not a scratch root"; exit 1; }
SRC=$(cd "${1:?usage: test-loa-update.sh SRC}" && pwd)
W=$(mktemp -d /tmp/loa-test.XXXXXX)
S=/var/lib/loa-update
U=/etc/systemd/system
SIGNERS=/usr/share/loa/update/allowed_signers
LU=/usr/local/bin/loa-update
F=/usr/share/loa/hypr/loa.lua                  # an overlay file the tests change
N=/usr/share/loa/omarchy/migrations-skip       # an overlay file the tests delete
n=0
fail() { echo "FAIL: $*"; [ -s $W/out ] && sed 's/^/  | /' $W/out; exit 1; }
pass() { n=$((n + 1)); echo "PASS: $*"; }
lu() { "$LU" "$@" > $W/out 2>&1; }
# Every loa-update run checks against the throwaway key: a good apply installs
# the bundle's allowed_signers (the real key) and a rollback restores the older one.
swap_key() { printf 'loa-update namespaces="loa-update" %s\n' "$(cut -d' ' -f1,2 $W/k1.pub)" > $SIGNERS; }
bundle() {  # VERSION DIR KEY [--aquamarine PKG]
    v=$1 d=$2 k=$3; shift 3
    sh $W/repo/tools/make-update-bundle.sh --version "$v" --out "$d" --key "$k" "$@" > $W/out 2>&1 || fail "make-update-bundle $v"
}
same() { cmp -s "$1" "$2"; }
marker() { cat $S/pending 2>/dev/null; }
# A refusal: non-zero exit, the expected reason, and no change anywhere in the
# root (ctime of every file outside loa-update's cache).
refuse() {  # NAME REASON ARGS...
    name=$1 reason=$2; shift 2
    swap_key; sync; sleep 1; touch $W/stamp; sleep 1
    lu "$@" && fail "$name: exit 0"
    grep -q "$reason" $W/out || fail "$name: reason is not '$reason'"
    ch=$(find / -xdev -path $S/cache -prune -o -cnewer $W/stamp -print | head -5)
    [ -z "$ch" ] || { echo "$ch" > $W/out; fail "$name: the root changed"; }
    pass "$name"
}
# What loa-boot-ok.service does when a boot reaches the desktop.
okcmd=$(sed -n 's/^ExecStart=//p' $U/loa-boot-ok.service)
# The boot check of a later boot: the chroot's boot id never changes, so the
# boot that applied the update is made to look like an earlier one.
later_boot() { echo 00000000-0000-0000-0000-000000000000 > $S/pending-boot; }
# An update that booted, reached the desktop and kept it for 10 minutes.
boot_ok() {
    later_boot; lu boot-check && eval "$okcmd" > /dev/null 2>&1 && lu confirm && [ ! -e $S/pending ] ||
        fail "confirming an update as a good boot does"
}
last_rollback() { read -r t rv why < $S/last-rollback && echo "$rv $why"; }
# The install script the next bundles carry: good, kill (killed after its
# second change), fail (exit 1 before its step 5).
install_script() {
    cp "$SRC/tools/overlay-install.sh" $W/repo/tools/overlay-install.sh
    case $1 in
        kill) sed -i 's/echo "updated \$f"$/echo "updated $f"; [ $n = 2 ] \&\& kill -KILL 0/' $W/repo/tools/overlay-install.sh &&
              grep -q 'kill -KILL 0' $W/repo/tools/overlay-install.sh ;;
        fail) sed -i 's/^# 5\. Modes, accounts, units\.$/exit 1\n&/' $W/repo/tools/overlay-install.sh &&
              grep -qx 'exit 1' $W/repo/tools/overlay-install.sh ;;
    esac && (cd $W/repo && git -c user.name=test -c user.email=test@invalid commit -q --allow-empty -am "install script: $1") > $W/out 2>&1 ||
        fail "building the '$1' install script"
}

# Throwaway keys and a git copy of the repo for make-update-bundle.sh.
ssh-keygen -q -t ed25519 -N '' -C test -f $W/k1 && ssh-keygen -q -t ed25519 -N '' -C other -f $W/k2 || fail "ssh-keygen"
cp -a "$SRC" $W/repo
(cd $W/repo && git init -q && git add -A && git -c user.name=test -c user.email=test@invalid commit -qm test) > $W/out 2>&1 || fail "git copy of the repo"

v=$(cat $S/version 2>/dev/null)
echo "$v" | grep -Eq '^[0-9]{8}-0$' || fail "the image records its bundle version (got '$v')"
pass "the image records the bundle version it was built from ($v)"

# 0. The units: the boot check is ordered before the early units and has no
# After= (After=local-fs.target closed a cycle with that Before=), and the three
# update units are enabled by links the overlay ships.
ru=$U/loa-update-rollback.service
! grep -q '^After=' $ru && grep '^Before=' $ru | grep -qw 'loa-mdev\.service' && grep '^Before=' $ru | grep -qw 'loa-modules\.service' ||
    fail "loa-update-rollback.service has no After= and is ordered before loa-mdev and loa-modules"
[ -L $U/sysinit.target.wants/loa-update-rollback.service ] && [ -L $U/sysinit.target.wants/loa-update-deadline.service ] &&
    [ -L $U/graphical.target.wants/loa-update-confirm.service ] ||
    fail "the rollback, deadline and confirm units are enabled by links"
pass "the boot check runs before the early units, and the rollback, deadline and confirm units are enabled"

# 1. A good bundle, on a root that has no recorded version (installed before
# loa-update): F changed and N deleted beforehand, so the update replaces one
# file and adds the other.
rm -f $S/version
echo "-- changed by the test" >> $F; cp -a $F $W/F.before; rm -f $N
bundle 29990101-1 $W/b1 $W/k1
swap_key
lu --file $W/b1/loa-update.tar || fail "a good bundle applies"
[ "$(cat $S/version)" = 29990101-1 ] || fail "a good bundle records its version"
pass "a root without a recorded version takes any bundle"
pass "a good bundle applies and records its version"
R=$(cat $S/last); BK=$(cat $R/backup)
same $F $W/repo/rootfs-overlay$F && [ -n "$BK" ] && same "$BK$F" $W/F.before ||
    fail "a changed overlay file is replaced and its backup exists"
pass "a changed overlay file is replaced and its backup exists"
boot_ok

# 2. Refusals, each bundle sound in every way but one (G: a good, newer bundle).
bundle 29990101-5 $W/g $W/k1
mkdir -p $W/t/x $W/t2; tar -xf $W/g/loa-update.tar -C $W/t/x
echo "-- tampered" >> $W/t/x/rootfs-overlay$F
(cd $W/t/x && tar -cf $W/t/loa-update.tar MANIFEST overlay-install.sh rootfs-overlay user-defaults)
cp $W/g/loa-update.tar.sig $W/t/loa-update.tar.sig
refuse "a tar modified after signing is refused" "bad signature" --file $W/t/loa-update.tar
bundle 29990101-5 $W/o $W/k2
refuse "a bundle signed by another key is refused" "bad signature" --file $W/o/loa-update.tar
bundle 20000101-1 $W/old $W/k1
refuse "an older version is refused" "not newer" --file $W/old/loa-update.tar
# A member that climbs out of the bundle, listed in MANIFEST with its true hash and signed.
python3 - $W/g/loa-update.tar $W/t2/loa-update.tar <<'PY' || fail "building the .. bundle"
import hashlib, io, sys, tarfile
src, dst = sys.argv[1:]
evil, data = "rootfs-overlay/../../../tmp/loa-escaped", b"escaped\n"
with tarfile.open(src) as a, tarfile.open(dst, "w", format=tarfile.GNU_FORMAT) as b:
    for m in a.getmembers():
        f = a.extractfile(m) if m.isfile() else None
        if m.name == "MANIFEST":
            text = f.read() + ("%s %s\n" % (hashlib.sha256(data).hexdigest(), evil)).encode()
            m.size = len(text); f = io.BytesIO(text)
        b.addfile(m, f)
    m = tarfile.TarInfo(evil); m.size = len(data); b.addfile(m, io.BytesIO(data))
PY
ssh-keygen -q -Y sign -f $W/k1 -n loa-update $W/t2/loa-update.tar || fail "signing the .. bundle"
refuse "a member path with .. is refused" "unsafe member path" --file $W/t2/loa-update.tar

# 3. Rollback by hand: F back to what it was before the update, N removed again.
lu rollback || fail "rollback runs"
same $F $W/F.before && [ ! -e $N ] && [ ! -e $S/version ] ||
    fail "rollback restores the changed file and removes an added one"
pass "rollback restores the changed file and removes an added one"
[ "$(last_rollback)" = "29990101-1 manual" ] || fail "a rollback by hand is recorded as 29990101-1 manual (got '$(last_rollback)')"

# 4. Automatic rollback (loa-update-rollback.service runs `loa-update boot-check`).
bundle 29990101-2 $W/b2 $W/k1
swap_key; lu --file $W/b2/loa-update.tar || fail "applying the bundle for the automatic rollback"
[ "$(marker)" = applied ] || fail "an update leaves the marker 'applied'"
refuse "a second update before the first has booted is refused" "not been confirmed" --file $W/g/loa-update.tar
eval "$okcmd" > /dev/null 2>&1
[ "$(marker)" = applied ] || fail "loa-boot-ok leaves an update that has not booted yet alone"
lu boot-check && [ "$(marker)" = applied ] || fail "the boot check in the boot that applied an update leaves it 'applied'"
pass "the boot check in the boot that applied an update leaves it 'applied'"
later_boot
lu boot-check && [ "$(marker)" = tried ] && same $F $W/repo/rootfs-overlay$F || fail "the first boot after an update marks it 'tried'"
lu boot-check || fail "the automatic rollback runs"
same $F $W/F.before && [ ! -e $N ] && [ ! -e $S/pending ] && [ ! -e $S/pending-boot ] && [ ! -e $S/version ] ||
    fail "the automatic rollback restores when the marker says a boot failed"
pass "the automatic rollback restores when the marker says a boot failed"
# The rollback is on record, `check` shows it without a download, and the
# cached bundle stays and applies again.
[ "$(last_rollback)" = "29990101-2 tried" ] || fail "an automatic rollback is recorded as 29990101-2 tried (got '$(last_rollback)')"
swap_key; lu check --file $S/cache/loa-update.tar || fail "check on the cached bundle runs"
grep -q 'last rollback: 29990101-2 .*(tried)' $W/out && [ -s $S/cache/loa-update.tar ] && [ -s $S/cache/loa-update.tar.sig ] ||
    fail "check shows the last rollback and keeps the cached bundle"
pass "check shows the last rollback and keeps the cached bundle"
swap_key; lu --file $S/cache/loa-update.tar && [ "$(cat $S/version)" = 29990101-2 ] && [ ! -e $S/last-rollback ] ||
    fail "the cached bundle applies again after its rollback"
pass "the cached bundle applies again after its rollback"
lu rollback && [ "$(last_rollback)" = "29990101-2 manual" ] || fail "a rollback by hand is recorded as 29990101-2 manual (got '$(last_rollback)')"
pass "a rollback records the version and what triggered it"

# Trial and confirm: loa-boot-ok turns 'tried' into 'booted', a boot that
# finds 'booted' rolls back, `confirm` keeps the update.
bundle 29990101-3 $W/b3 $W/k1
swap_key; lu --file $W/b3/loa-update.tar || fail "applying the bundle for loa-boot-ok"
lu confirm && fail "confirm accepts an update that has not booted"
[ "$(marker)" = applied ] || fail "a refused confirm leaves the marker 'applied'"
later_boot; lu boot-check && eval "$okcmd" > /dev/null 2>&1
[ "$(marker)" = booted ] || fail "loa-boot-ok marks a tried update 'booted'"
lu boot-check && same $F $W/F.before && [ ! -e $S/pending ] && [ "$(last_rollback)" = "29990101-3 booted" ] ||
    fail "a boot that finds 'booted' rolls the update back"
pass "an update whose boot ended within its 10 minutes is rolled back at the next boot"
swap_key; lu --file $W/b3/loa-update.tar || fail "applying the bundle for confirm"
later_boot; lu boot-check && eval "$okcmd" > /dev/null 2>&1 && lu confirm || fail "confirm keeps an update that reached the desktop"
[ ! -e $S/pending ] && lu boot-check && same $F $W/repo/rootfs-overlay$F && [ "$(cat $S/version)" = 29990101-3 ] ||
    fail "a confirmed update is kept by the next boot check"
pass "confirm refuses an update that has not booted, and keeps one that reached the desktop"

# 5. Aquamarine: test packages (one placeholder file) that provide what the
# installed one provides, or a libaquamarine.so the installed Hyprland does not use.
cur=$(pacman -Q aquamarine | cut -d' ' -f2)
db=/var/lib/pacman/local/aquamarine-$cur/desc
mkpkg() {  # VERSION OUT PROVIDES...
    ver=$1 out=$2; shift 2; d=$W/pkg-$ver; mkdir -p $d/usr/share/loa-test
    echo test > $d/usr/share/loa-test/aquamarine
    { echo "pkgname = aquamarine"; echo "pkgbase = aquamarine"; echo "pkgver = $ver"
      echo "pkgdesc = loa-update test package"; echo "arch = aarch64"; echo "size = 5"
      for p in "$@"; do echo "provides = $p"; done; } > $d/.PKGINFO
    (cd $d && bsdtar --zstd --uid 0 --gid 0 -cf "$out" .PKGINFO usr) || fail "building $out"
}
# Every path of the installed Aquamarine: type, mode, owner, and the content
# hash of a file or the target of a symlink.
snap() {
    pacman -Qlq aquamarine | while IFS= read -r p; do
        if [ -L "$p" ]; then x=$(readlink "$p"); elif [ -f "$p" ]; then x=$(sha256sum < "$p" | cut -d' ' -f1); else x=-; fi
        echo "$p $(stat -c '%F %a %U:%G' "$p") $x"
    done
}
snap > $W/aq.before
L=$(pacman -Qlq aquamarine | grep '^/usr/lib/libaquamarine\.so\.' | while IFS= read -r p; do [ -f "$p" ] && [ ! -L "$p" ] && echo "$p"; done)
[ -n "$L" ] && [ "$(echo "$L" | wc -l)" = 1 ] || fail "the installed Aquamarine has one regular file /usr/lib/libaquamarine.so.* (got '$L')"
# shellcheck disable=SC2012
ls /var/cache/pacman/pkg/aquamarine-"$cur"-* $S/aquamarine/aquamarine-"$cur"-* 2>/dev/null | grep -q . &&
    fail "a package file of the installed Aquamarine $cur exists already, so the rebuild from the installed files is not tested"
provides=$(awk '$0 == "%PROVIDES%" {on = 1; next} /^%[A-Z]+%$/ {on = 0} on && NF' $db)
# shellcheck disable=SC2086
mkpkg "$cur.1" $W/aquamarine-$cur.1-aarch64.pkg.tar.zst $provides
bundle 29990101-4 $W/b4 $W/k1 --aquamarine $W/aquamarine-$cur.1-aarch64.pkg.tar.zst
swap_key; lu --file $W/b4/loa-update.tar || fail "applying a bundle with Aquamarine"
R=$(cat $S/last)
[ "$(pacman -Q aquamarine | cut -d' ' -f2)" = "$cur.1" ] && [ ! -e "$L" ] || fail "the bundled Aquamarine is installed (and $L is gone)"
lu rollback || fail "rolling back the Aquamarine update"
[ "$(pacman -Q aquamarine | cut -d' ' -f2)" = "$cur" ] && pacman -Qk aquamarine > /dev/null 2>&1 ||
    fail "rollback reinstalls the previous Aquamarine"
snap > $W/aq.after
same $W/aq.before $W/aq.after || { diff $W/aq.before $W/aq.after > $W/out; fail "rollback brings back every file of the previous Aquamarine as it was"; }
[ "$(pacman -Qp "$(cat "$R.rolled-back/aquamarine-prev")" 2>/dev/null)" = "aquamarine $cur" ] ||
    fail "the package kept for rollback is Aquamarine $cur"
pass "a bundled Aquamarine for the installed Hyprland is installed, and rollback reinstalls the previous one"
pass "rollback brings back every file of the previous Aquamarine as it was, from a package rebuilt from the installed files"
mkpkg "$cur.2" $W/aquamarine-$cur.2-aarch64.pkg.tar.zst "libaquamarine.so=0-64"
bundle 29990101-6 $W/b6 $W/k1 --aquamarine $W/aquamarine-$cur.2-aarch64.pkg.tar.zst
swap_key; lu --file $W/b6/loa-update.tar || fail "applying a bundle with a mismatched Aquamarine"
[ "$(pacman -Q aquamarine | cut -d' ' -f2)" = "$cur" ] && [ -f $S/aquamarine/aquamarine-$cur.2-aarch64.pkg.tar.zst ] &&
    grep -q "not installing Aquamarine" $W/out || fail "a mismatched Aquamarine is kept, not installed"
pass "a bundled Aquamarine whose libaquamarine.so Hyprland does not use is kept, not installed"
boot_ok

# 6. An install killed after its second change (F replaced, then N added), with
# loa-update itself, so none of its post-processing runs; then the boot check
# rolls it back at once from what was recorded before the install started.
echo "-- changed again by the test" >> $F; cp -a $F $W/F.before2; rm -f $N
vbefore=$(cat $S/version)
install_script kill
bundle 29990101-7 $W/b7 $W/k1
swap_key
setsid -w "$LU" --file $W/b7/loa-update.tar > $W/out 2>&1 && fail "the interrupted install exits 0"
same $F $W/repo/rootfs-overlay$F && [ -e $N ] && [ "$(marker)" = applying ] && [ "$(cat $S/version)" = "$vbefore" ] ||
    fail "the install was interrupted after replacing F and adding N, with the marker 'applying'"
lu boot-check || fail "the automatic rollback after an interrupted install runs"
same $F $W/F.before2 && [ ! -e $N ] && [ ! -e $S/pending ] && [ "$(cat $S/version)" = "$vbefore" ] ||
    fail "one boot check after an interrupted install restores the replaced file and removes the added one"
pass "one boot check after an interrupted install restores the replaced file and removes the added one"

# 7. An install script that fails: loa-update rolls back what it did and exits non-zero.
install_script fail
echo "-- changed a third time" >> $F; cp -a $F $W/F.before3; rm -f $N
bundle 29990101-8 $W/b8 $W/k1
swap_key; lu --file $W/b8/loa-update.tar && fail "an update whose install script fails exits 0"
same $F $W/F.before3 && [ ! -e $N ] && [ "$(cat $S/version)" = "$vbefore" ] && [ ! -e $S/pending ] && [ ! -e $S/last ] ||
    fail "a failed install is rolled back at once"
pass "an update whose install script fails is rolled back at once and exits non-zero"

# 8. Killed again, then a good update: it rolls the interrupted one back before
# it applies, so its own rollback restores the state from before both.
install_script kill
echo "-- changed a fourth time" >> $F; cp -a $F $W/F.before4; rm -f $N
bundle 29990101-9 $W/b9 $W/k1
swap_key
setsid -w "$LU" --file $W/b9/loa-update.tar > $W/out 2>&1 && fail "the second interrupted install exits 0"
[ "$(marker)" = applying ] || fail "the second interrupted install leaves the marker 'applying'"
install_script good
bundle 29990101-10 $W/b10 $W/k1
swap_key; lu --file $W/b10/loa-update.tar && grep -q interrupted $W/out && [ "$(cat $S/version)" = 29990101-10 ] ||
    fail "a good update after an interrupted install applies"
lu rollback || fail "rolling back the update that followed an interrupted install"
same $F $W/F.before4 && [ ! -e $N ] && [ "$(cat $S/version)" = "$vbefore" ] ||
    fail "an update after an interrupted install rolls that install back first"
pass "an update after an interrupted install rolls that install back first"

# 9. The deadline (loa-update-deadline.service, 300 s into a boot), with a
# systemctl in PATH that only logs.
mkdir -p $W/bin
printf '#!/bin/sh\necho "$*" >> %s/systemctl.log\n' $W > $W/bin/systemctl; chmod 755 $W/bin/systemctl
deadline() { PATH=$W/bin:$PATH "$LU" boot-deadline > $W/out 2>&1; }
echo "-- changed a fifth time" >> $F; cp -a $F $W/F.before5; rm -f $N
bundle 29990101-11 $W/b11 $W/k1
swap_key; lu --file $W/b11/loa-update.tar || fail "applying the bundle for the deadline"
mkdir -p /loa; echo 2 > /loa/boot-attempts; rm -f /run/loa-boot-ok $W/systemctl.log
deadline && [ "$(marker)" = applied ] && same $F $W/repo/rootfs-overlay$F && [ ! -e $W/systemctl.log ] ||
    fail "the deadline leaves an update alone whose marker is not 'tried'"
later_boot; lu boot-check && [ "$(marker)" = tried ] || fail "the boot check marks the update 'tried' for the deadline"
touch /run/loa-boot-ok
deadline && [ "$(marker)" = tried ] && same $F $W/repo/rootfs-overlay$F && [ ! -e $W/systemctl.log ] &&
    [ "$(cat /loa/boot-attempts)" = 2 ] || fail "the deadline leaves a boot alone that reached loa-boot-ok"
pass "the deadline leaves an update alone when the boot reached loa-boot-ok or the marker is not 'tried'"
rm -f /run/loa-boot-ok
deadline
same $F $W/F.before5 && [ ! -e $N ] && [ ! -e $S/pending ] && [ ! -e $S/pending-boot ] && [ "$(cat /loa/boot-attempts)" = 0 ] &&
    grep -qx -e '--no-block reboot' $W/systemctl.log && [ "$(last_rollback)" = "29990101-11 deadline" ] ||
    fail "the deadline rolls back, resets the boot counter and reboots"
pass "300 s into a boot of an update without loa-boot-ok, the deadline rolls back, resets the boot counter and reboots"

# 10. Last: an update that installs a broken loa-update (only `exit 1`). The
# boot check runs through the unit's ExecStart, as systemd does, so the copy
# kept with the record rolls it back. `lu` is unusable until then.
PINNED=$(cat <<'EOF'
/bin/sh -c 'r=$$(cat /var/lib/loa-update/last 2>/dev/null); [ -x "$$r/loa-update" ] && exec "$$r/loa-update" boot-check; exec /usr/local/bin/loa-update boot-check'
EOF
)
bc=$(sed -n 's/^ExecStart=//p' $ru)
[ "$bc" = "$PINNED" ] || { echo "$bc" > $W/out; fail "the ExecStart of loa-update-rollback.service is the pinned text"; }
install_script good
printf '#!/bin/sh\nexit 1\n' > $W/repo/rootfs-overlay$LU
(cd $W/repo && git -c user.name=test -c user.email=test@invalid commit -qam "broken loa-update") > $W/out 2>&1 || fail "committing a broken loa-update"
cp -a $LU $W/lu.before
echo "-- changed a sixth time" >> $F; cp -a $F $W/F.before6; rm -f $N
bundle 29990101-12 $W/b12 $W/k1
swap_key; lu --file $W/b12/loa-update.tar && same $LU $W/repo/rootfs-overlay$LU || fail "applying the update with a broken loa-update"
later_boot
run=$(printf '%s\n' "$bc" | sed 's/\$\$/$/g')
eval "$run" > $W/out 2>&1 && [ "$(marker)" = tried ] || fail "the unit's boot check marks the update 'tried'"
eval "$run" > $W/out 2>&1 || fail "the unit's boot check rolls back"
same $F $W/F.before6 && [ ! -e $N ] && [ ! -e $S/pending ] && same $LU $W/lu.before ||
    fail "the boot check runs the loa-update that wrote the record and restores the installed one"
pass "the boot check runs the loa-update kept with the record, so an update with a broken loa-update is rolled back"

rm -rf $W
echo "loa-update tests: all $n passed"
