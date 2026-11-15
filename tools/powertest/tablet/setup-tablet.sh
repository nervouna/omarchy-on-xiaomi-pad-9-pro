#!/bin/sh
# Installs the power test's software on the tablet (as root), idempotently.
# Run by `tools/powertest/powertest.py setup` after it copied the sources to
# /opt/loa-powertest/src. Everything lives under /opt/loa-powertest; nothing is
# written to the desktop user's home:
#   nodejs, npm      pacman packages (from the configured snapshot, no -Sy)
#   pi/              Pi Agent, npm --prefix, pinned version
#   project/         working copy of the test project (a git repo, owned by the user)
#   home/            HOME for every test process (Chromium profile, caches, Pi)
#   chromium/        the test Chromium's profile
#   npm-cache/       npm's cache
set -eu
B=/opt/loa-powertest
PI_PKG=@earendil-works/pi-coding-agent
PI_VER=1.5.2
U="setpriv --reuid=1000 --regid=1000 --init-groups"
export npm_config_cache=$B/npm-cache npm_config_update_notifier=false npm_config_fund=false npm_config_audit=false

pacman -Q nodejs npm >/dev/null 2>&1 || pacman -S --needed --noconfirm nodejs npm
node --version

mkdir -p $B/pi $B/npm-cache
have=$(cat "$B/pi/lib/node_modules/$PI_PKG/package.json" 2>/dev/null | grep -m1 '"version"' | cut -d'"' -f4 || true)
if [ "$have" != "$PI_VER" ]; then
    npm install --global --prefix "$B/pi" "$PI_PKG@$PI_VER"
fi
"$B/pi/bin/pi" --version

mkdir -p $B/home $B/chromium $B/project
chown 1000:1000 $B/home $B/chromium $B/project $B/npm-cache
chown -R 1000:1000 $B/npm-cache
# The working copy: replaced when the project's sources changed, node_modules kept.
want=$(cd $B/src/project && cat package.json package-lock.json index.html src/* | sha256sum | cut -c1-16)
cd $B/project
if [ "$(cat .loa-src 2>/dev/null)" != "$want" ]; then
    find . -mindepth 1 -maxdepth 1 ! -name node_modules -exec rm -rf {} +
    cp -r $B/src/project/. .
    chown -R 1000:1000 .
    $U env HOME=$B/home npm ci --no-audit --no-fund
    G="$U env HOME=$B/home git -c user.name=loa -c user.email=loa@localhost"
    rm -rf .git
    $G init -q
    printf 'node_modules\n.loa-src\n' > .git/info/exclude
    $G add -A .
    $G commit -q -m pristine
    echo "$want" > .loa-src
    chown 1000:1000 .loa-src
fi
$U env HOME=$B/home node node_modules/vite/bin/vite.js --version
echo "setup: done"
