#!/bin/sh
# Gate for an update release tag (used by .github/workflows/release-update.yml
# and promote-update.yml). Exits 0 and prints the version (YYYYMMDD-N) when
#   - TAG is exactly update-YYYYMMDD-N,
#   - its commit is an ancestor of the main branch (unless --skip-ancestry), and
#   - its version is newer than every update-* tag in the release list, compared
#     as (date, N) with N a number, as `loa-update` compares versions.
#   tools/check-update-tag.sh TAG --releases FILE (--commit SHA | --skip-ancestry) [--repo DIR] [--main REF]
# FILE lists existing release tags, one per line; lines that are not update tags
# are ignored. --repo defaults to this checkout, --main to origin/main.
set -e
die() { echo "check-update-tag: $*" >&2; exit 1; }
TAG=${1:-}; [ $# -eq 0 ] || shift
REL="" COMMIT="" SKIP="" REPO="" MAIN=origin/main
while [ $# -gt 0 ]; do
    case "$1" in
        --releases) REL=${2:-}; shift 2 ;;
        --commit) COMMIT=${2:-}; shift 2 ;;
        --skip-ancestry) SKIP=1; shift ;;
        --repo) REPO=${2:-}; shift 2 ;;
        --main) MAIN=${2:-}; shift 2 ;;
        *) die "usage: $0 TAG --releases FILE (--commit SHA | --skip-ancestry) [--repo DIR] [--main REF]" ;;
    esac
done
[ -n "$REPO" ] || REPO=$(cd "$(dirname "$0")/.." && pwd)
# One line only: a newline in the tag must not slip past the pattern.
[ "$(printf '%s\n' "$TAG" | wc -l)" -eq 1 ] && printf '%s\n' "$TAG" | grep -Eq '^update-[0-9]{8}-[0-9]+$' ||
    die "tag must be update-YYYYMMDD-N (got '$TAG')"
VER=${TAG#update-}
[ -n "$REL" ] && [ -f "$REL" ] || die "--releases FILE is required (the existing release tags, one per line)"
if [ -z "$SKIP" ]; then
    [ -n "$COMMIT" ] || die "--commit SHA is required unless --skip-ancestry"
    git -C "$REPO" merge-base --is-ancestor "$COMMIT" "$MAIN" 2>/dev/null ||
        die "commit $COMMIT is not on main ($MAIN): tag a commit of main"
fi
# Numeric (date, N) comparison, as loa-update's newer().
newer() { [ "${1%-*}" -gt "${2%-*}" ] || { [ "${1%-*}" -eq "${2%-*}" ] && [ "${1#*-}" -gt "${2#*-}" ]; }; }
for t in $(grep -E '^update-[0-9]{8}-[0-9]+$' "$REL" || true); do
    newer "$VER" "${t#update-}" || die "version $VER is not newer than the existing release $t"
done
echo "$VER"
