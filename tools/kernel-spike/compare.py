#!/usr/bin/env python3
"""Compare a built kernel's exported symbol CRCs with what the tablet's stock
modules import.

usage: compare.py imports.tsv SYMVERS [BASELINE_SYMVERS]

imports.tsv: "crc<TAB>symbol<TAB>module path" (modprobe --dump-modversions).
SYMVERS: vmlinux.symvers / Module.symvers of the build under test.
"""
import collections
import os
import sys


def symvers(path):
    out = {}
    with open(path) as f:
        for line in f:
            p = line.rstrip("\n").split("\t")
            if len(p) >= 3:
                out[p[1]] = (int(p[0], 16), p[2])
    return out


imports = collections.defaultdict(lambda: collections.defaultdict(set))
with open(sys.argv[1]) as f:
    for line in f:
        crc, sym, mod = line.rstrip("\n").split("\t")
        imports[sym][int(crc, 16)].add(os.path.basename(mod))

# Symbols that the stock modules export to each other are not the kernel's.
built = symvers(sys.argv[2])
base = symvers(sys.argv[3]) if len(sys.argv) > 3 else None

missing, mismatch, ok = [], [], 0
broken_mods = collections.defaultdict(set)
for sym, crcs in sorted(imports.items()):
    if sym not in built:
        missing.append(sym)
        continue
    crc, _ = built[sym]
    bad = {m for c, mods in crcs.items() if c != crc for m in mods}
    if bad:
        mismatch.append(sym)
        for m in bad:
            broken_mods[m].add(sym)
    else:
        ok += 1

all_mods = {m for crcs in imports.values() for mods in crcs.values() for m in mods}
print(f"imported symbols: {len(imports)}  match: {ok}  "
      f"CRC mismatch: {len(mismatch)}  not exported by this build: {len(missing)}")
print(f"modules with a CRC mismatch: {len(broken_mods)} of {len(all_mods)}")
if mismatch:
    print("mismatching symbols (first 40):", " ".join(mismatch[:40]))
if base is not None:
    changed = sorted(s for s in built if s in base and base[s][0] != built[s][0])
    gone = sorted(s for s in base if s not in built)
    new = sorted(s for s in built if s not in base)
    print(f"vs baseline build: {len(changed)} CRCs changed, {len(gone)} symbols gone, {len(new)} new")
    used = [s for s in changed if s in imports]
    print(f"  changed symbols that stock modules import: {len(used)}")
    if changed:
        print("  changed (first 40):", " ".join(changed[:40]))
    if new:
        print("  new (first 40):", " ".join(new[:40]))
if "-v" in sys.argv:
    print("missing:", " ".join(missing))
