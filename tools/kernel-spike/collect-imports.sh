#!/bin/sh
# Print every symbol the tablet's kernel modules import, with its CRC:
#   crc<TAB>symbol<TAB>module path
# Read-only. Run from the repo root with a tablet on the USB cable:
#   tools/kernel-spike/collect-imports.sh > imports.tsv
# Then, with a build's kernel_aarch64_Module.symvers from the
# "Kernel namespace spike" workflow artifacts:
#   tools/kernel-spike/compare.py imports.tsv variant.symvers baseline.symvers
# The output describes proprietary modules: keep it out of the repository.
cd "$(dirname "$0")/../.." || exit 1
# shellcheck disable=SC2016  # expanded on the tablet
tools/tssh 'find "/usr/lib/modules/$(uname -r)" -name "*.ko" | while read -r f; do
    modprobe --dump-modversions "$f" 2>/dev/null | sed "s|\$|\t$f|"
done'
