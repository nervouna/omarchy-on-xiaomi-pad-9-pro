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

# Throwaway keys and a git copy of the repo for make-update-bundle.sh.
ssh-keygen -q -t ed25519 -N '' -C test -f $W/k1 && ssh-keygen -q -t ed25519 -N '' -C other -f $W/k2 || fail "ssh-keygen"
cp -a "$SRC" $W/repo
(cd $W/repo && git init -q && git add -A && git -c user.name=test -c user.email=test@invalid commit -qm test) > $W/out 2>&1 || fail "git copy of the repo"

v=$(cat $S/version 2>/dev/null)
echo "$v" | grep -Eq '^[0-9]{8}-0$' || fail "the image records its bundle version (got '$v')"
pass "the image records the bundle version it was built from ($v)"

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

# 4. Automatic rollback (loa-update-rollback.service runs `loa-update boot-check`).
okcmd=$(sed -n 's/^ExecStart=//p' /etc/systemd/system/loa-boot-ok.service)
bundle 29990101-2 $W/b2 $W/k1
swap_key; lu --file $W/b2/loa-update.tar || fail "applying the bundle for the automatic rollback"
[ "$(cat $S/pending)" = applied ] || fail "an update leaves the marker 'applied'"
eval "$okcmd" > /dev/null 2>&1
[ "$(cat $S/pending)" = applied ] || fail "loa-boot-ok leaves an update that has not booted yet alone"
lu boot-check && [ "$(cat $S/pending)" = tried ] && same $F $W/repo/rootfs-overlay$F || fail "the first boot after an update marks it 'tried'"
lu boot-check || fail "the automatic rollback runs"
same $F $W/F.before && [ ! -e $N ] && [ ! -e $S/pending ] && [ ! -e $S/version ] ||
    fail "the automatic rollback restores when the marker says a boot failed"
pass "the automatic rollback restores when the marker says a boot failed"
bundle 29990101-3 $W/b3 $W/k1
swap_key; lu --file $W/b3/loa-update.tar && lu boot-check || fail "applying the bundle for loa-boot-ok"
eval "$okcmd" > /dev/null 2>&1
[ ! -e $S/pending ] && lu boot-check && same $F $W/repo/rootfs-overlay$F && [ "$(cat $S/version)" = 29990101-3 ] ||
    fail "loa-boot-ok clears the marker of a boot that reached the desktop"
pass "loa-boot-ok clears the marker of a boot that reached the desktop"

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
provides=$(awk '$0 == "%PROVIDES%" {on = 1; next} /^%[A-Z]+%$/ {on = 0} on && NF' $db)
# shellcheck disable=SC2086
mkpkg "$cur.1" $W/aquamarine-$cur.1-aarch64.pkg.tar.zst $provides
bundle 29990101-4 $W/b4 $W/k1 --aquamarine $W/aquamarine-$cur.1-aarch64.pkg.tar.zst
swap_key; lu --file $W/b4/loa-update.tar || fail "applying a bundle with Aquamarine"
[ "$(pacman -Q aquamarine | cut -d' ' -f2)" = "$cur.1" ] || fail "the bundled Aquamarine is installed"
lu rollback || fail "rolling back the Aquamarine update"
[ "$(pacman -Q aquamarine | cut -d' ' -f2)" = "$cur" ] && pacman -Qk aquamarine > /dev/null 2>&1 ||
    fail "rollback reinstalls the previous Aquamarine"
pass "a bundled Aquamarine for the installed Hyprland is installed, and rollback reinstalls the previous one"
mkpkg "$cur.2" $W/aquamarine-$cur.2-aarch64.pkg.tar.zst "libaquamarine.so=0-64"
bundle 29990101-6 $W/b6 $W/k1 --aquamarine $W/aquamarine-$cur.2-aarch64.pkg.tar.zst
swap_key; lu --file $W/b6/loa-update.tar || fail "applying a bundle with a mismatched Aquamarine"
[ "$(pacman -Q aquamarine | cut -d' ' -f2)" = "$cur" ] && [ -f $S/aquamarine/aquamarine-$cur.2-aarch64.pkg.tar.zst ] &&
    grep -q "not installing Aquamarine" $W/out || fail "a mismatched Aquamarine is kept, not installed"
pass "a bundled Aquamarine whose libaquamarine.so Hyprland does not use is kept, not installed"

# 6. An install killed after its second change (F replaced, then N added), with
# loa-update itself, so none of its post-processing runs; then the automatic
# rollback works from what was recorded before the install started.
echo "-- changed again by the test" >> $F; cp -a $F $W/F.before2; rm -f $N
vbefore=$(cat $S/version)
(cd $W/repo && sed -i 's/echo "updated \$f"$/echo "updated $f"; [ $n = 2 ] \&\& kill -KILL 0/' tools/overlay-install.sh &&
    grep -q 'kill -KILL 0' tools/overlay-install.sh && git -c user.name=test -c user.email=test@invalid commit -qam interrupt) > $W/out 2>&1 || fail "building the interrupting install script"
bundle 29990101-7 $W/b7 $W/k1
swap_key
setsid -w "$LU" --file $W/b7/loa-update.tar > $W/out 2>&1 && fail "the interrupted install exits 0"
same $F $W/repo/rootfs-overlay$F && [ -e $N ] && [ "$(cat $S/pending)" = applied ] && [ "$(cat $S/version)" = "$vbefore" ] ||
    fail "the install was interrupted after replacing F and adding N"
lu boot-check && lu boot-check || fail "the automatic rollback after an interrupted install runs"
same $F $W/F.before2 && [ ! -e $N ] && [ ! -e $S/pending ] && [ "$(cat $S/version)" = "$vbefore" ] ||
    fail "the automatic rollback after an interrupted install restores the replaced file and removes the added one"
pass "the automatic rollback after an interrupted install restores the replaced file and removes the added one"

rm -rf $W
echo "loa-update tests: all $n passed"
