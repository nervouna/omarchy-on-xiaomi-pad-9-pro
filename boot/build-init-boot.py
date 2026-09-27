#!/usr/bin/env python3
"""Build init_boot-omarchy.img: stock init_boot v4 header + our lz4-legacy newc cpio.
Same packing as the proven V8-V13 probe images (header ramdisk size at 12,
signature size zeroed at 1580)."""
import hashlib, os, pathlib, subprocess, sys
here = pathlib.Path(__file__).resolve().parent
work = here.parent
root = here / "initramfs"
applets = """sh ash mount umount mknod mkdir insmod grep sed cat echo sleep seq ls basename tr mdev
switch_root cp ip setsid uname head ln rm sync reboot chmod dmesg ps kill mv test [ printf env
readlink stat wc tail cut touch id df free""".split()
entries = []  # (name, mode, data)
def add(name, mode, data=b""): entries.append((name, mode, data))
add("bin", 0o040755)
add("bin/busybox", 0o100755, (here / "busybox-static").read_bytes())
for a in applets: add(f"bin/{a}", 0o120777, b"busybox")
add("loa", 0o040755)
for f in sorted((root / "loa").iterdir()):
    add(f"loa/{f.name}", 0o100755 if os.access(f, os.X_OK) else 0o100644, f.read_bytes())
add("init", 0o100755, (root / "init").read_bytes())

# Stock Android first-stage ramdisk (from the stock init_boot), so stage 1 can
# hand over to Android (Volume Up / next-boot-android flag). Its /init becomes
# /init.android; everything else keeps its path.
def newc_entries(buf):
    off = 0
    while True:
        h = buf[off:off + 110]; assert h[:6] == b"070701", "not newc"
        f = [int(h[6 + 8 * i:14 + 8 * i], 16) for i in range(13)]
        mode, fsize, nsize = f[1], f[6], f[11]
        name = buf[off + 110:off + 110 + nsize - 1].decode()
        off = (off + 110 + nsize + 3) & ~3
        data = buf[off:off + fsize]; off = (off + fsize + 3) & ~3
        if name == "TRAILER!!!": return
        yield name, mode, data
stock_img = (work / "images/init_boot-stock-OS4.0.5.0.img").read_bytes()
rd_size = int.from_bytes(stock_img[12:16], "little")
stock_lz4 = here / "stock-ramdisk.lz4"; stock_lz4.write_bytes(stock_img[4096:4096 + rd_size])
stock_cpio = subprocess.run(["/opt/homebrew/bin/lz4", "-d", "-c", str(stock_lz4)], check=True, capture_output=True).stdout
have = {e[0] for e in entries}
for name, mode, data in newc_entries(stock_cpio):
    if name == ".": continue
    if name == "init": name = "init.android"
    if name in have: continue
    add(name, mode, data)
out = bytearray(); ino = 1
def rec(name, mode, data):
    global ino
    nb = name.encode() + b"\0"
    hdr = "070701" + "".join("%08x" % v for v in [ino, mode, 0, 0, 1, 0, len(data), 0, 0, 0, 0, len(nb), 0])
    ino += 1
    out.extend(hdr.encode() + nb); out.extend(b"\0" * (-len(out) % 4))
    out.extend(data); out.extend(b"\0" * (-len(out) % 4))
for e in entries: rec(*e)
rec("TRAILER!!!", 0, b"")
out.extend(b"\0" * (-len(out) % 512))
cpio = here / "initramfs.cpio"; cpio.write_bytes(out)
lz4 = here / "initramfs.lz4"
subprocess.run(["/opt/homebrew/bin/lz4", "-l", "-f", "-q", str(cpio), str(lz4)], check=True)
rd = lz4.read_bytes()
stock = (work / "images/init_boot-stock-OS4.0.5.0.img").read_bytes()
assert stock[:8] == b"ANDROID!" and int.from_bytes(stock[40:44], "little") == 4
hdr = bytearray(stock[:4096])
hdr[12:16] = len(rd).to_bytes(4, "little")
hdr[1580:1584] = (0).to_bytes(4, "little")
img = bytes(hdr) + rd; img += b"\0" * (-len(img) % 4096)
assert len(img) <= len(stock), "exceeds init_boot partition"
dst = work / "images/init_boot-omarchy.img"; dst.write_bytes(img)
print(f"{dst.name}: {len(img)} bytes, ramdisk {len(rd)}, sha256 {hashlib.sha256(img).hexdigest()}")
