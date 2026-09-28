#!/bin/sh
# Import the device's own stock Android pieces into the Omarchy root, from the
# tablet's partitions (read-only), so the root image itself carries no Xiaomi or
# Qualcomm files. Runs once before loa-modules (loa-vendor-import.service), again
# only if the stamp is removed (e.g. after flashing a different stock build).
#   - second-stage kernel modules + Android load lists/blocklists
#     (system_dlkm, vendor_dlkm out of `super`, mapped read-only with dm-linear)
#   - firmware (vendor + odm partitions, modem partition image/)
#   - the THP touch chroot /opt/loa-thp (stock Bionic + touch libs + our launcher)
# The first-stage (ramdisk) modules are copied by stage 1, which has them in
# its initramfs. Nothing is ever written to an Android partition.
set -e
# LOA_IMPORT_ROOT=/some/dir writes everything below that directory instead (testing).
T=${LOA_IMPORT_ROOT:-}
STAMP=$T/usr/lib/loa/vendor-imported
K=$(uname -r)
M=$T/usr/lib/modules/$K
W=/run/loa-import
log() { echo "import-vendor: $*"; }

part() {  # PARTNAME -> /dev/sdXN
    for u in /sys/class/block/*/uevent; do
        grep -q "^PARTNAME=$1\$" "$u" && { echo /dev/$(sed -n 's/^DEVNAME=//p' "$u"); return; }
    done
}
SLOT=$(sed -n 's/^androidboot.slot_suffix = "\(_[ab]\)"$/\1/p' /proc/bootconfig 2>/dev/null)
[ -n "$SLOT" ] || SLOT=$(tr ' ' '\n' < /proc/cmdline | sed -n 's/^androidboot.slot_suffix=//p')
S=$(part super)
[ -n "$SLOT" ] && [ -b "$S" ] || { log "no slot/super"; exit 1; }
log "slot $SLOT, super $S, kernel $K"

cleanup() {
    for p in modem odm vendor system vendor_dlkm system_dlkm apex; do
        mountpoint -q $W/$p 2>/dev/null && umount $W/$p
    done
    for p in system vendor odm system_dlkm vendor_dlkm; do
        dmsetup remove "loa-import-$p$SLOT" 2>/dev/null || true
    done
    rm -rf $W
}
trap cleanup EXIT
mkdir -p $W

python3 /usr/lib/loa/loa-lpmap.py "$S" "$SLOT" system vendor odm system_dlkm vendor_dlkm > $W/lp.txt
while IFS='	' read -r n segs; do
    set -- $segs; t=""; off=0
    while [ $# -gt 1 ]; do t="${t}${off} $1 linear $S $2\n"; off=$((off + $1)); shift 2; done
    printf "$t" | dmsetup create --readonly "loa-import-$n"
done < $W/lp.txt
dmsetup mknodes 2>/dev/null || true   # no devtmpfs/udev sync on the GKI kernel
for p in system vendor odm system_dlkm vendor_dlkm; do
    mkdir -p $W/$p; mount -o ro /dev/mapper/loa-import-$p$SLOT $W/$p
done
mkdir -p $W/modem; mount -o ro "$(part modem$SLOT)" $W/modem

# Modules. Stage 1 put the ramdisk set in $M/ramdisk (first boot).
mkdir -p $M/vendor $T/usr/lib/loa/modules
cp -a $W/system_dlkm/lib/modules/$K/. $M/
cp -a $W/vendor_dlkm/lib/modules/. $M/vendor/
cp $W/system_dlkm/lib/modules/$K/modules.load $T/usr/lib/loa/modules/system_dlkm.load
cp $W/vendor_dlkm/lib/modules/modules.load $T/usr/lib/loa/modules/vendor_dlkm.load
cp $W/vendor_dlkm/lib/modules/*blocklist $T/usr/lib/loa/modules/
rm -f $M/modules.dep $M/modules.dep.bin $M/modules.alias* $M/modules.symbols* $M/modules.softdep $M/modules.devname
[ -z "$T" ] || [ -e $T/lib ] || ln -s usr/lib $T/lib   # depmod -b looks in lib/modules
depmod -b "${T:-/}" -a "$K"
log "modules: $(find $M -name '*.ko' | wc -l)"

# Firmware (firmware_class.path is /usr/lib/firmware/image, set by stage 1).
mkdir -p $T/usr/lib/firmware/image
cp -a $W/vendor/firmware/. $W/odm/firmware/. $T/usr/lib/firmware/
cp -a $W/modem/image/. $T/usr/lib/firmware/image/
# The Wi-Fi driver's config: the stock firmware dir only has a dangling link to it.
F=$T/usr/lib/firmware/wlan/qca_cld/wcn7750/WCNSS_qcom_cfg.ini
rm -f $F; install -m 644 $W/vendor/etc/wifi/wcn7750/WCNSS_qcom_cfg.ini $F
log "firmware: $(du -sh $T/usr/lib/firmware | cut -f1)"

# THP touch chroot: stock Bionic (runtime APEX) + stock libs + our launcher.
R=$T/opt/loa-thp; mkdir -p $T/opt
rm -rf $R.new; mkdir -p $R.new
python3 - "$W/system/system/apex/com.android.runtime.apex" "$W" <<'PY'
import sys, zipfile
zipfile.ZipFile(sys.argv[1]).extract("apex_payload.img", sys.argv[2])
PY
mkdir -p $W/apex; mount -o loop,ro $W/apex_payload.img $W/apex
cd $R.new
mkdir -p bin system/bin system/lib64 odm/lib64 odm/firmware apex/com.android.runtime/bin \
    apex/com.android.runtime/lib64/bionic dev sys proc tmp vendor/firmware \
    data/vendor/touch data/vendor/bsplog/touch data/vendor/touch_state mnt/vendor/persist/touch
install -m 755 $T/usr/lib/loa/loa-thp-launcher bin/loa-thp-launcher
install -m 755 $W/apex/bin/linker64 apex/com.android.runtime/bin/linker64
for l in libc libm libdl; do install -m 644 $W/apex/lib64/bionic/$l.so system/lib64/$l.so; done
for l in liblog libc++ libbase libcutils; do install -m 644 $W/system/system/lib64/$l.so system/lib64/; done
for l in libtouchreport libtouchreport_alg libtouchreport_hal libtouchreport_sensor libtensorflowlite_touch_c; do
    install -m 644 $W/odm/lib64/$l.so odm/lib64/
done
for f in shuntian_nova_thp_config.cfg palm_check.tflite smooth.tflite; do install -m 644 $W/odm/firmware/$f odm/firmware/; done
ln -sf /apex/com.android.runtime/bin/linker64 system/bin/linker64
for l in libc libm libdl; do ln -sf /system/lib64/$l.so apex/com.android.runtime/lib64/bionic/$l.so; done
cp odm/firmware/shuntian_nova_thp_config.cfg odm/firmware/shuntian_nova_thp_config.ini   # the HAL reads .ini
find . -type f ! -name MANIFEST.sha256 | sed 's|^\./||' | sort | xargs sha256sum > MANIFEST.sha256
cd /; umount $W/apex
rm -rf $R.old; [ -d $R ] && mv $R $R.old; mv $R.new $R; rm -rf $R.old
log "THP chroot: $(wc -l < $R/MANIFEST.sha256) files"

sed -n 's/^ro.vendor.build.fingerprint=//p' $W/vendor/build.prop > $STAMP
log "done ($(cat $STAMP))"
