#!/bin/sh
# Test for tools/check-update-tag.sh; runs on macOS and Linux, needs only git.
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

R=$W/repo
git init -q -b main "$R"
git -C "$R" -c user.name=t -c user.email=t@t commit -q --allow-empty -m one
ON_MAIN=$(git -C "$R" rev-parse HEAD)
git -C "$R" switch -q -c side
git -C "$R" -c user.name=t -c user.email=t@t commit -q --allow-empty -m side
OFF_MAIN=$(git -C "$R" rev-parse HEAD)
git -C "$R" switch -q main

printf '%s\n' update-20261110-1 update-20261111-2 v0.9 > "$W/rel"
: > "$W/none"

ok "accepts a new tag on a main commit" update-20261112-1 --commit "$ON_MAIN" --repo "$R" --main main --releases "$W/rel"
ok "accepts with no release yet" update-20261112-1 --commit "$ON_MAIN" --repo "$R" --main main --releases "$W/none"
ok "accepts the next N of the same day" update-20261111-3 --commit "$ON_MAIN" --repo "$R" --main main --releases "$W/rel"
ok "N compares as a number" update-20261111-10 --commit "$ON_MAIN" --repo "$R" --main main --releases "$W/rel"
bad "rejects a dashed date" "update-YYYYMMDD-N" update-2026-11-12 --commit "$ON_MAIN" --repo "$R" --main main --releases "$W/none"
bad "rejects a tag without N" "update-YYYYMMDD-N" update-20261112 --commit "$ON_MAIN" --repo "$R" --main main --releases "$W/none"
bad "rejects v1" "update-YYYYMMDD-N" v1 --commit "$ON_MAIN" --repo "$R" --main main --releases "$W/none"
bad "rejects a two-line tag" "update-YYYYMMDD-N" "update-20261112-1
x" --commit "$ON_MAIN" --repo "$R" --main main --releases "$W/none"
bad "rejects a commit not on main" "not on main" update-20261112-1 --commit "$OFF_MAIN" --repo "$R" --main main --releases "$W/none"
bad "rejects an equal version" "not newer" update-20261111-2 --commit "$ON_MAIN" --repo "$R" --main main --releases "$W/rel"
bad "rejects an older N" "not newer" update-20261111-1 --commit "$ON_MAIN" --repo "$R" --main main --releases "$W/rel"
bad "rejects an older date" "not newer" update-20261109-9 --commit "$ON_MAIN" --repo "$R" --main main --releases "$W/rel"
ok "skips the ancestry check on request" update-20261112-1 --skip-ancestry --releases "$W/none"
bad "needs a release list" "releases" update-20261112-1 --commit "$ON_MAIN" --repo "$R" --main main
bad "needs a commit unless skipped" "commit" update-20261112-1 --repo "$R" --main main --releases "$W/none"
echo "check-update-tag: $n tests passed"
