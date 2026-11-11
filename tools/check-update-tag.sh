#!/bin/sh
# Version gate for an update release (used by .github/workflows/release-update.yml
# and promote-update.yml). Exits 0 and prints the version when VERSION is exactly
# YYYYMMDD-N and strictly newer than every update-YYYYMMDD-N tag listed in the
# --existing files, compared as (date, N) with N a number, as `loa-update` does.
#   tools/check-update-tag.sh VERSION --existing FILE [--existing FILE ...]
# A FILE lists tags one per line (git tags, release tags, or both: the files are
# merged, so a withdrawn release whose tag was kept still blocks its version).
# Lines that are not update tags are ignored. The order of the lines does not matter.
set -e
die() { echo "check-update-tag: $*" >&2; exit 1; }
VER=${1:-}; [ $# -eq 0 ] || shift
FILES=""
while [ $# -gt 0 ]; do
    case "$1" in
        --existing) [ -f "${2:-}" ] || die "--existing needs a file (got '${2:-}')"; FILES="$FILES
$2"; shift 2 ;;
        *) die "usage: $0 VERSION --existing FILE [--existing FILE ...]" ;;
    esac
done
# One line only: a newline in the value must not slip past the pattern.
[ "$(printf '%s\n' "$VER" | wc -l)" -eq 1 ] && printf '%s\n' "$VER" | grep -Eq '^[0-9]{8}-[0-9]+$' ||
    die "version must be YYYYMMDD-N (got '$VER')"
[ -n "$FILES" ] || die "--existing FILE is required"
# Numeric (date, N) comparison, as loa-update's newer().
newer() { [ "${1%-*}" -gt "${2%-*}" ] || { [ "${1%-*}" -eq "${2%-*}" ] && [ "${1#*-}" -gt "${2#*-}" ]; }; }
OLD_IFS=$IFS; IFS='
'
# shellcheck disable=SC2086
set -- $FILES
IFS=$OLD_IFS
for t in $(cat "$@" | grep -E '^update-[0-9]{8}-[0-9]+$' | sort -u || true); do
    newer "$VER" "${t#update-}" || die "version $VER is not newer than the existing $t"
done
echo "$VER"
