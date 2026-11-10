#!/bin/sh
# Build the over-the-air update bundle that `loa-update` installs on a tablet.
#   tools/make-update-bundle.sh --version V --out DIR [--aquamarine PKG] [--key PRIVATE_KEY]
#
# DIR/loa-update.tar holds this checkout's committed rootfs-overlay/,
# user-defaults/ and tools/overlay-install.sh (as overlay-install.sh), the
# Aquamarine package when given, and MANIFEST: "version V", "commit C", then one
# "sha256 path" line per member (a symlink's sha256 is of its target). With
# --key, DIR/loa-update.tar.sig is an `ssh-keygen -Y sign` signature over the tar
# (namespace loa-update). V is YYYYMMDD-N. Runs on macOS and Linux.
#
# The files come from HEAD (`git archive`), never from the working tree: a
# git-ignored local input (android-props.tar.gz, keys) must not reach a bundle.
set -e
die() { echo "make-update-bundle: $*" >&2; exit 1; }
D=$(cd "$(dirname "$0")/.." && pwd)
VER="" OUT="" AQ="" KEY=""
while [ $# -gt 0 ]; do
    case "$1" in
        --version) VER=$2; shift 2 ;;
        --out) OUT=$2; shift 2 ;;
        --aquamarine) AQ=$2; shift 2 ;;
        --key) KEY=$2; shift 2 ;;
        *) die "usage: $0 --version YYYYMMDD-N --out DIR [--aquamarine PKG] [--key PRIVATE_KEY]" ;;
    esac
done
echo "$VER" | grep -Eq '^[0-9]{8}-[0-9]+$' || die "--version must be YYYYMMDD-N (got '$VER')"
[ -n "$OUT" ] || die "--out DIR is required"
[ -z "$AQ" ] || [ -f "$AQ" ] || die "no such package: $AQ"
case "$(basename "${AQ:-aquamarine-x.pkg.tar.zst}")" in aquamarine-*.pkg.tar.zst) ;; *) die "--aquamarine takes an aquamarine-*.pkg.tar.zst" ;; esac
[ -z "$KEY" ] || [ -f "$KEY" ] || die "no such key: $KEY"
if command -v sha256sum >/dev/null 2>&1; then SHA="sha256sum"; else SHA="shasum -a 256"; fi
git -C "$D" rev-parse --verify -q HEAD >/dev/null || die "$D is not a git checkout"
COMMIT=$(git -C "$D" rev-parse HEAD)
[ -z "$(git -C "$D" status --porcelain -- rootfs-overlay user-defaults tools/overlay-install.sh)" ] ||
    echo "make-update-bundle: note: uncommitted changes are not in the bundle (it is built from $COMMIT)" >&2

mkdir -p "$OUT"; OUT=$(cd "$OUT" && pwd)
T=$(mktemp -d "${TMPDIR:-/tmp}/loa-bundle.XXXXXX")
trap 'rm -rf "$T"' EXIT
mkdir "$T/b"
git -C "$D" archive --format=tar HEAD rootfs-overlay user-defaults tools/overlay-install.sh | tar -xf - -C "$T/b"
mv "$T/b/tools/overlay-install.sh" "$T/b/overlay-install.sh"; rmdir "$T/b/tools"
[ -z "$AQ" ] || cp "$AQ" "$T/b/"

# MANIFEST: every file and symlink but MANIFEST itself, sorted by path.
cd "$T/b"
{
    echo "version $VER"
    echo "commit $COMMIT"
    find . \( -type f -o -type l \) | sed 's|^\./||' | LC_ALL=C sort | while IFS= read -r f; do
        if [ -L "$f" ]; then h=$(printf '%s' "$(readlink "$f")" | $SHA | cut -d' ' -f1)
        else h=$($SHA < "$f" | cut -d' ' -f1); fi
        echo "$h $f"
    done
} > "$T/MANIFEST"
mv "$T/MANIFEST" MANIFEST
MEMBERS="MANIFEST overlay-install.sh rootfs-overlay user-defaults"
[ -z "$AQ" ] || MEMBERS="$MEMBERS $(basename "$AQ")"
rm -f "$OUT/loa-update.tar" "$OUT/loa-update.tar.sig"
# shellcheck disable=SC2086
COPYFILE_DISABLE=1 tar --no-xattrs -cf "$T/loa-update.tar" $MEMBERS
cd /
mv "$T/loa-update.tar" "$OUT/loa-update.tar"
if [ -n "$KEY" ]; then
    ssh-keygen -q -Y sign -f "$KEY" -n loa-update "$OUT/loa-update.tar" || die "signing failed"
    echo "wrote $OUT/loa-update.tar and $OUT/loa-update.tar.sig (version $VER, commit $COMMIT)"
else
    echo "wrote $OUT/loa-update.tar (version $VER, commit $COMMIT; unsigned)"
fi
