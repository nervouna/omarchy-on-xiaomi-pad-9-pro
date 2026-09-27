#!/bin/sh
# Xiaomi THP (touch host processing) for the NT36536 panel: raw frames from
# /dev/xiaomi-touch -> vendor algorithm -> coordinates reported back into
# NVTCapacitiveTouchScreen. Stock Bionic libs run in an Android-layout chroot
# at /opt/loa-thp (built from GPT's native-thp-v1 bundle; config .cfg -> .ini).
R=/opt/loa-thp
for d in dev sys proc; do mkdir -p $R/$d; mountpoint -q $R/$d || mount --bind /$d $R/$d; done
mkdir -p $R/data/vendor/touch $R/data/vendor/bsplog/touch $R/tmp
for i in $(seq 1 50); do [ -e /sys/class/touch/touch_dev ] && [ -c /dev/xiaomi-touch ] && break; sleep 0.2; done
cd /
exec env -i PATH=/bin LD_LIBRARY_PATH=/system/lib64:/odm/lib64 chroot $R /bin/loa-thp-launcher --run
