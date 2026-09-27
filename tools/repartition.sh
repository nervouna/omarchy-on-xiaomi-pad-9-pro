#!/bin/sh
# Move the Omarchy root from `ramdump` (17 GiB, where tools/install.sh puts it)
# to its own `omarchy` partition carved from the FRONT of Android's userdata.
# Run on the Mac while the tablet runs native Omarchy from `ramdump`.
#   tools/repartition.sh [SIZE_GIB]            plan only (default 64)
#   tools/repartition.sh [SIZE_GIB] --apply    do it
# DESTROYS ANDROID'S DATA (userdata + metadata are wiped; Android re-creates
# them on its next boot). The ramdump copy stays intact as a rollback
# (relabelled omarchy-old). Stage 1 already prefers `omarchy` over `ramdump`,
# so a reboot afterwards lands on the new partition.
# Procedure proven on 2026-09-27 (docs/engineering-log.md).
set -e
D=$(cd "$(dirname "$0")/.." && pwd)
SIZE=64; APPLY=0
for a in "$@"; do case $a in --apply) APPLY=1;; *[!0-9]*) echo "bad argument $a"; exit 2;; *) SIZE=$a;; esac; done
mkdir -p "$D/backups"

"$D/tools/tssh" "sh -s $SIZE $APPLY" <<'EOF'
set -e
SIZE=$1; APPLY=$2
part() { for u in /sys/class/block/*/uevent; do grep -q "^PARTNAME=$1\$" "$u" && { echo /dev/$(sed -n 's/^DEVNAME=//p' "$u"); return; }; done; }
ROOT=$(findmnt -no SOURCE /)
[ "$ROOT" = "$(part ramdump)" ] || { echo "refusing: / must be on ramdump (is $ROOT)"; exit 1; }
[ -z "$(part omarchy)" ] || { echo "refusing: an omarchy partition already exists"; exit 1; }
U=$(part userdata); M=$(part metadata)
[ -b "$U" ] && [ -b "$M" ] || { echo "userdata/metadata not found"; exit 1; }
for x in $U $M; do
    findmnt "$x" >/dev/null && { echo "$x is mounted"; exit 1; }
    [ -z "$(ls /sys/class/block/${x#/dev/}/holders)" ] || { echo "$x is in use"; exit 1; }
done
DISK=/dev/$(basename "$(readlink -f /sys/class/block/${U#/dev/}/..)")
sfdisk -d $DISK > /run/gpt-before.sfdisk
python3 - "$SIZE" "$U" /run/gpt-before.sfdisk /run/gpt-after.sfdisk <<'PY'
import re, sys
size_gib, udev, src, dst = int(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4]
lines = open(src).read().splitlines()
ss = int(next(l.split(":")[1] for l in lines if l.startswith("sector-size:")))
last_lba = int(next(l.split(":")[1] for l in lines if l.startswith("last-lba:")))
parts = [l for l in lines if l.startswith("/dev/")]
num = lambda l: int(re.match(r"/dev/\D+(\d+)", l).group(1))
field = lambda l, k: int(re.search(k + r"=\s*(\d+)", l).group(1))
ul = next(l for l in parts if l.split()[0] == udev)
ustart, usize = field(ul, "start"), field(ul, "size")
assert ustart + usize - 1 == max(field(l, "start") + field(l, "size") - 1 for l in parts), "userdata is not the last partition"
new = size_gib * 2**30 // ss
align = 2**20 // ss
assert new % align == 0
left = usize - new
assert left * ss >= 8 * 2**30, "userdata would be smaller than 8 GiB"
n = max(num(l) for l in parts) + 1
dev = re.match(r"(/dev/\D+)\d+", udev).group(1)
out = []
for l in lines:
    if l.split()[:1] == [udev]:
        l = re.sub(r"start=\s*\d+", "start=%12d" % (ustart + new), l)
        l = re.sub(r"size=\s*\d+", "size=%12d" % left, l)
        out.append(l)
        out.append('%s%d : start=%12d, size=%12d, type=0FC63DAF-8483-4772-8E79-3D69D8477DE4, name="omarchy"' % (dev, n, ustart, new))
    else:
        out.append(l)
open(dst, "w").write("\n".join(out) + "\n")
print("sector size %d; new %s%d 'omarchy' start %d size %d (%d GiB);" % (ss, dev, n, ustart, new, size_gib))
print("userdata %s start %d size %d (%.1f GiB, was %.1f GiB)" % (udev, ustart + new, left, left * ss / 2**30, usize * ss / 2**30))
PY
diff /run/gpt-before.sfdisk /run/gpt-after.sfdisk || true
sfdisk --no-act --no-reread --no-tell-kernel --force $DISK < /run/gpt-after.sfdisk >/dev/null
echo "dry run of the new table: ok"
[ "$APPLY" = 1 ] || { echo "plan only; re-run with --apply"; exit 0; }

# ---- apply ----------------------------------------------------------------
cp /run/gpt-before.sfdisk /root/gpt-before-repartition.sfdisk
sfdisk --no-reread --no-tell-kernel --force $DISK < /run/gpt-after.sfdisk >/dev/null
N=$(sed -n 's|^\(/dev/[a-z]*[0-9]*\) : .*name="omarchy".*|\1|p' /run/gpt-after.sfdisk)
UN=${U#/dev/}; NN=${N#/dev/}
partx -u --nr ${UN#${DISK#/dev/}} $DISK; partx -a --nr ${NN#${DISK#/dev/}} $DISK; sleep 1
[ -b $N ] || { echo "kernel did not add $N"; exit 1; }
# Kernel view must match the new table before anything is written (units: 512 B).
SS=$(blockdev --getss $DISK)
want() { sed -n "s|^$1 : start= *\([0-9]*\), size= *\([0-9]*\).*|\1 \2|p" /run/gpt-after.sfdisk; }
set -- $(want $U); [ "$(cat /sys/class/block/$UN/start)" = $(($1 * SS / 512)) ] || { echo "userdata start mismatch"; exit 1; }
set -- $(want $N); [ "$(cat /sys/class/block/$NN/start)" = $(($1 * SS / 512)) ] || { echo "new partition start mismatch"; exit 1; }
echo "partition table written; copying the root filesystem (desktop freezes ~1 min)"
cat > /run/loa-copy.sh <<CP
#!/bin/sh
exec >/run/loa-copy.log 2>&1
( sleep 900; fsfreeze -u / 2>/dev/null ) & guard=\$!
sync; fsfreeze -f / && echo frozen
dd if=$ROOT of=$N bs=16M iflag=direct oflag=direct conv=fsync; echo "dd rc=\$?"
fsfreeze -u / && echo unfrozen; kill \$guard; echo DONE
CP
chmod +x /run/loa-copy.sh; rm -f /run/loa-copy.log; setsid -f /run/loa-copy.sh
until grep -q DONE /run/loa-copy.log 2>/dev/null; do sleep 5; done
cat /run/loa-copy.log
grep -q "dd rc=0" /run/loa-copy.log || { echo "copy failed"; exit 1; }
e2fsck -fy $N >/dev/null || [ $? -le 1 ]
tune2fs -U random $N >/dev/null; resize2fs $N >/dev/null 2>&1; e2label $ROOT omarchy-old
blkid $ROOT $N
# Wipe Android's userdata + metadata so it formats them at the new size.
blkdiscard -f $U >/dev/null 2>&1 || true
dd if=/dev/zero of=$U bs=16M count=4 oflag=direct conv=fsync status=none
dd if=/dev/zero of=$M bs=16M count=4 oflag=direct conv=fsync status=none
echo "done: reboot (systemctl reboot); stage 1 will mount the omarchy partition"
EOF
"$D/tools/tssh" 'cat /root/gpt-before-repartition.sfdisk 2>/dev/null || cat /run/gpt-before.sfdisk' > "$D/backups/gpt-before-repartition-$(date +%Y%m%d-%H%M).sfdisk"
