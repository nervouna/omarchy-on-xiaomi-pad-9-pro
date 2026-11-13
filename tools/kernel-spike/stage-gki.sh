#!/bin/sh
# usage: stage-gki.sh ARTIFACT_DIR  (run from the repo root)
set -e
A=$1; N=6.12.69-android16-6-maybe-dirty-4k
tools/tssh "set -e; cd /usr/lib/modules/$N; rm -rf kernel modules.* /tmp/gki; mkdir /tmp/gki; tar xzf - -C /tmp/gki; cp -a /tmp/gki/lib/modules/$N/. .; rm -rf /tmp/gki; rm -f modules.dep modules.dep.bin modules.alias* modules.symbols* modules.softdep modules.devname; depmod -a $N; find kernel -name '*.ko' | wc -l; find . -name '*.ko' | wc -l; ls; f=\$(find kernel -name bluetooth.ko); tail -c 28 \$f | head -c 27; echo; sync" < $A/system_dlkm_staging_archive.tar.gz
