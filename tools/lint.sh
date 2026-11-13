#!/bin/sh
# Syntax checks for every tracked script, chosen by shebang:
#   sh / bash   parse with the named shell (-n), then shellcheck at error level
#   python3     compile without writing bytecode
# Scripts for Android's /system/bin/sh (mksh) are parsed with bash, the closest
# shell a runner has. Needs bash, python3 and shellcheck.
cd "$(dirname "$0")/.." || exit 1
fail=0
n=0
for f in $(git ls-files); do
    [ -f "$f" ] && [ ! -L "$f" ] || continue
    line=$(head -c 128 "$f" 2>/dev/null | head -n 1 | tr -d '\r\0')
    case "$line" in
        '#!'*) ;;
        *) continue ;;
    esac
    case "$line" in
        *python*)
            python3 -c 'import sys; compile(open(sys.argv[1], "rb").read(), sys.argv[1], "exec")' "$f" \
                || { echo "== $f: python syntax"; fail=1; }
            ;;
        *'/system/bin/sh'*|*bash*)
            bash -n "$f" || { echo "== $f: shell syntax"; fail=1; }
            shellcheck --shell=bash --severity=error "$f" || fail=1
            ;;
        *'/sh'*|*' sh'*)
            sh -n "$f" || { echo "== $f: shell syntax"; fail=1; }
            shellcheck --shell=sh --severity=error "$f" || fail=1
            ;;
        *) continue ;;
    esac
    n=$((n + 1))
done
[ $fail = 0 ] && echo "lint: $n scripts clean" || { echo "lint: fix the errors above"; exit 1; }
