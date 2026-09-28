#!/usr/bin/env python3
"""Convert a raw image to an Android sparse image (for fastboot flash).

  tools/img2simg.py RAW OUT.simg

Runs of all-zero 4 KiB blocks become FILL(0) chunks (written as zeros on the
device, so the partition ends up identical to RAW); everything else is RAW data.
Needed because macOS fastboot fails on very large raw files ("Failed reading").
"""
import struct, sys

BLK = 4096
RAW, FILL = 0xCAC1, 0xCAC2
ZERO = bytes(BLK)

def main(src, dst):
    with open(src, "rb") as f:
        f.seek(0, 2); size = f.tell(); f.seek(0)
        assert size % BLK == 0, "image size must be a multiple of 4096"
        total = size // BLK
        with open(dst, "wb") as o:
            o.write(bytes(28))                      # header, rewritten at the end
            chunks = 0; run_kind = None; run = []
            def flush():
                nonlocal chunks, run
                if not run: return
                n = len(run) if run_kind == RAW else run
                if run_kind == RAW:
                    data = b"".join(run)
                    o.write(struct.pack("<HHII", RAW, 0, len(run), 12 + len(data))); o.write(data)
                else:
                    o.write(struct.pack("<HHII", FILL, 0, run, 16)); o.write(bytes(4))
                chunks += 1; run = []
            for _ in range(total):
                b = f.read(BLK)
                kind = FILL if b == ZERO else RAW
                if kind != run_kind or (kind == RAW and len(run) >= 16384):
                    flush(); run_kind = kind; run = [] if kind == RAW else 0
                if kind == RAW: run.append(b)
                else: run += 1
            flush()
            o.seek(0)
            o.write(struct.pack("<IHHHHIIII", 0xED26FF3A, 1, 0, 28, 12, BLK, total, chunks, 0))
    print(f"{dst}: {total} blocks, {chunks} chunks")

if __name__ == "__main__":
    if len(sys.argv) != 3: sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
