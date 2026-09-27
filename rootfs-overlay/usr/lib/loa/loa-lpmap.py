#!/usr/bin/env python3
"""Print dm-linear tables for Android dynamic partitions inside `super`.

Reads the liblp metadata (geometry at 4096, metadata slots after the primary +
backup geometry) of the metadata slot that belongs to the requested A/B suffix
(_a -> 0, _b -> 1) and prints, per partition, one line:
    NAME<TAB>LEN START [LEN START ...]      (512-byte sectors)
usage: loa-lpmap.py SUPER_DEV SUFFIX NAME...   e.g. /dev/sda31 _b system vendor odm
Only linear extents on super itself (block device index 0) are supported.
"""
import struct, sys

LP_GEOMETRY_MAGIC = 0x616c4467
LP_METADATA_MAGIC = 0x414c5030

def main():
    dev, suffix, names = sys.argv[1], sys.argv[2], sys.argv[3:]
    slot = {"_a": 0, "_b": 1}[suffix]
    with open(dev, "rb") as f:
        f.seek(4096)
        g = f.read(4096)
        magic, = struct.unpack_from("<I", g, 0)
        if magic != LP_GEOMETRY_MAGIC:
            sys.exit("no liblp geometry on %s" % dev)
        md_max, md_slots = struct.unpack_from("<II", g, 40)
        f.seek(4096 + 2 * 4096 + slot * md_max)
        h = f.read(md_max)
    if struct.unpack_from("<I", h, 0)[0] != LP_METADATA_MAGIC:
        sys.exit("bad metadata header in slot %d" % slot)
    hsz = struct.unpack_from("<I", h, 8)[0]
    t = h[hsz:]
    desc = lambda o: struct.unpack_from("<III", h, o)   # offset, count, entry size
    parts, exts = desc(80), desc(92)
    table = {}
    for i in range(parts[1]):
        e = t[parts[0] + i * parts[2]:parts[0] + (i + 1) * parts[2]]
        name = e[:36].rstrip(b"\0").decode()
        _attr, first, num, _grp = struct.unpack_from("<IIII", e, 36)
        segs = []
        for j in range(first, first + num):
            nsec, ttype, tdata, tsrc = struct.unpack_from("<QIQI", t, exts[0] + j * exts[2])
            if ttype != 0 or tsrc != 0:
                sys.exit("%s: unsupported extent (type %d, source %d)" % (name, ttype, tsrc))
            segs += [nsec, tdata]
        table[name] = segs
    for n in names:
        segs = table.get(n + suffix)
        if not segs:
            sys.exit("%s%s: missing or empty in metadata slot %d" % (n, suffix, slot))
        print("%s%s\t%s" % (n, suffix, " ".join(map(str, segs))))

main()
