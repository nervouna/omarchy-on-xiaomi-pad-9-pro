#!/system/bin/sh
# Copy stock kernel modules + firmware from running Android into the Omarchy root.
R=/data/local/omarchy-dev; K=$(uname -r); M=$R/usr/lib/modules/$K
mkdir -p $M/vendor $R/usr/lib/firmware
cp -a /system_dlkm/lib/modules/$K/. $M/
cp -a /vendor_dlkm/lib/modules/. $M/vendor/
# Android load order + blocklists, kept for our loader
mkdir -p $R/usr/lib/loa/modules
cp /system_dlkm/lib/modules/$K/modules.load $R/usr/lib/loa/modules/system_dlkm.load
cp /vendor_dlkm/lib/modules/modules.load $R/usr/lib/loa/modules/vendor_dlkm.load
cp /vendor_dlkm/lib/modules/*blocklist $R/usr/lib/loa/modules/
rm -f $M/modules.dep $M/modules.dep.bin $M/modules.alias* $M/modules.symbols* $M/modules.softdep $M/modules.devname
cp -a /vendor/firmware/. /odm/firmware/. $R/usr/lib/firmware/
mkdir -p $R/usr/lib/firmware/image && cp -a /vendor/firmware_mnt/image/. $R/usr/lib/firmware/image/
echo "modules: $(find $M -name '*.ko' | wc -l)  firmware: $(du -sh $R/usr/lib/firmware | cut -f1)"
