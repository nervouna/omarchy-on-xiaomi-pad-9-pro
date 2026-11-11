#!/bin/sh
# Test for tools/check-update-tag.sh; runs on macOS and Linux.
#   tools/test-check-update-tag.sh
set -u
D=$(cd "$(dirname "$0")" && pwd)
CHK=$D/check-update-tag.sh
W=$(mktemp -d "${TMPDIR:-/tmp}/check-tag-test.XXXXXX")
trap 'rm -rf "$W"' EXIT
n=0
fail() { echo "FAIL: $*"; [ -s "$W/out" ] && sed 's/^/  | /' "$W/out"; exit 1; }
ok() {  # NAME ARGS...: must exit 0
    name=$1; shift
    "$CHK" "$@" > "$W/out" 2>&1 || fail "$name: expected acceptance"
    n=$((n + 1)); echo "PASS: $name"
}
bad() {  # NAME REASON ARGS...: must exit non-zero and mention REASON
    name=$1 reason=$2; shift 2
    "$CHK" "$@" > "$W/out" 2>&1 && fail "$name: expected rejection"
    grep -q -- "$reason" "$W/out" || fail "$name: reason is not '$reason'"
    n=$((n + 1)); echo "PASS: $name"
}

# Newest first, as `gh release list` returns them; v0.9 is not an update tag.
printf '%s\n' update-20261111-2 update-20261110-1 v0.9 > "$W/rel"
printf '%s\n' update-20261110-1 > "$W/tags"
: > "$W/none"
# A withdrawn release keeps its git tag: only the tag list knows version 20261113-4.
printf '%s\n' update-20261113-4 update-20261111-2 > "$W/tags2"
printf '%s\n' update-20261112-2 update-20261112-10 > "$W/nums"

ok "accepts a new date" 20261112-1 --existing "$W/rel"
ok "accepts with nothing released yet" 20261112-1 --existing "$W/none"
ok "accepts the next N of the same day" 20261111-3 --existing "$W/rel"
bad "rejects an equal version" "not newer" 20261111-2 --existing "$W/rel"
bad "rejects an older N" "not newer" 20261110-0 --existing "$W/rel"
bad "rejects an older date" "not newer" 20261109-9 --existing "$W/rel"
bad "N compares as a number, not text" "not newer" 20261112-9 --existing "$W/nums"
ok "N compares as a number: 11 > 10" 20261112-11 --existing "$W/nums"
bad "a tag without a release blocks (union)" "not newer" 20261113-3 --existing "$W/rel" --existing "$W/tags2"
bad "a release without a tag blocks (union)" "not newer" 20261111-2 --existing "$W/tags" --existing "$W/rel"
ok "the union allows a version newer than both" 20261113-5 --existing "$W/rel" --existing "$W/tags2"
bad "rejects a dashed date" "YYYYMMDD-N" 2026-11-12 --existing "$W/none"
bad "rejects a version without N" "YYYYMMDD-N" 20261112 --existing "$W/none"
bad "rejects a tag name" "YYYYMMDD-N" update-20261112-1 --existing "$W/none"
bad "rejects v1" "YYYYMMDD-N" v1 --existing "$W/none"
bad "rejects an empty version" "YYYYMMDD-N" "" --existing "$W/none"
bad "rejects a two-line version" "YYYYMMDD-N" "20261112-1
x" --existing "$W/none"
bad "rejects a trailing newline-injected line" "YYYYMMDD-N" "x
20261112-1" --existing "$W/none"
bad "needs a list" "required" 20261112-1
bad "rejects a missing list file" "needs a file" 20261112-1 --existing "$W/missing"
echo "check-update-tag: $n tests passed"
