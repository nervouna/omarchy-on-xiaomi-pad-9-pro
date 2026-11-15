#!/usr/bin/env python3
"""Fail when a kernel build's exported symbols differ from a baseline build's.

usage: compare-symvers.py BASELINE_DIR BUILD_DIR

Each directory holds vmlinux.symvers and kernel_aarch64_Module.symvers. The
baseline is the same source with the stock configuration, whose CRCs equal what
the tablet's stock modules import (issue #57). A changed or missing symbol means
those modules may be refused; new exports are fine.
"""
import sys


def symvers(d):
    out = {}
    for name in ("vmlinux.symvers", "kernel_aarch64_Module.symvers"):
        with open(f"{d}/{name}") as f:
            for line in f:
                p = line.rstrip("\n").split("\t")
                if len(p) >= 3:
                    out[p[1]] = p[0]
    return out


base, built = symvers(sys.argv[1]), symvers(sys.argv[2])
changed = sorted(s for s in base if s in built and base[s] != built[s])
gone = sorted(s for s in base if s not in built)
new = sorted(s for s in built if s not in base)
print(f"{len(base)} baseline symbols: {len(changed)} CRCs changed, {len(gone)} gone, {len(new)} new")
for label, syms in (("changed", changed), ("gone", gone), ("new", new)):
    if syms:
        print(f"{label}: {' '.join(syms[:40])}{' ...' if len(syms) > 40 else ''}")
sys.exit(1 if changed or gone else 0)
