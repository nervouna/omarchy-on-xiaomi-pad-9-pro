#!/bin/sh
# Assemble /opt/loa-android: a minimal Android-layout chroot for stock vendor
# daemons (Bionic). /system,/vendor,/odm are the read-only stock partitions
# (android-parts.sh); Bionic libc/libm/libdl + linker64 come from the runtime
# APEX copy in /opt/loa-thp (stock /system/lib64/libc.so links into the APEX).
set -e
R=/opt/loa-android
/usr/lib/loa/android-parts.sh >/dev/null
mkdir -p $R/system $R/vendor $R/odm $R/dev $R/proc $R/sys $R/data $R/tmp $R/mnt/vendor/persist \
         $R/apex $R/linkerconfig
bind() { mountpoint -q "$2" || mount --bind "$1" "$2"; }
bind /android/system/system $R/system
bind /android/vendor $R/vendor
bind /android/odm $R/odm
bind /dev $R/dev; bind /dev/pts $R/dev/pts; bind /proc $R/proc; bind /sys $R/sys
mountpoint -q $R/data || mount -t tmpfs -o mode=0771 tmpfs $R/data
mountpoint -q $R/tmp  || mount -t tmpfs tmpfs $R/tmp
mkdir -p $R/data/vendor/audio $R/data/vendor/audio_dsp $R/data/vendor/touch $R/data/vendor/bsplog/touch
# Bluetooth HAL: calibration.bin must be writable or it SSRs itself; ssr dumps; mac_addr.
mkdir -p $R/data/vendor/bluetooth $R/data/vendor/bsplog/bt/ssr_dump $R/data/vendor/mac_addr
# DSP firmware + *.jsn service descriptions (Android mounts the modem partition here).
bind /usr/lib/firmware $R/vendor/firmware_mnt
bind /android/dsp $R/vendor/dsp
bind /android/bt_firmware $R/vendor/bt_firmware
bind /android/persist $R/mnt/vendor/persist
# Stock APEXes: zip with an uncompressed erofs apex_payload.img -> loop-mount it
# read-only at its offset (com.android.runtime = linker64 + full Bionic).
mount_apex() {
    a=/android/system/system/apex/$1.apex; d=$R/apex/$1
    mountpoint -q $d && return 0
    off=$(python3 -c "import zipfile,struct,sys
z=zipfile.ZipFile(sys.argv[1]); i=z.getinfo('apex_payload.img'); assert i.compress_type==0
f=open(sys.argv[1],'rb'); f.seek(i.header_offset); h=f.read(30); n,e=struct.unpack('<HH',h[26:30])
print(i.header_offset+30+n+e)" $a)
    mkdir -p $d; mount -t erofs -o ro,loop,offset=$off $a $d 2>/dev/null || mount -t ext4 -o ro,loop,offset=$off $a $d
}
mount_apex com.android.runtime
mount_apex com.android.i18n
# Read-only snapshot of the stock Android property area (taken from a live
# OS4.0.5.0 boot) so Bionic property_get() works for vendor daemons.
if [ ! -e /dev/__properties__/property_info ]; then
    tar -xzf /usr/lib/loa/android-props.tar.gz -C /dev
    chmod 0711 /dev/__properties__; chmod 0444 /dev/__properties__/*
fi
echo "android chroot ready at $R"
