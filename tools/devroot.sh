#!/system/bin/sh
# Omarchy root lives on the `omarchy` partition (ext4, label omarchy; was `ramdump` until 2026-09-27).
# Mount it as a chroot on rooted Android. Usage: devroot.sh mount|umount|migrate
P=/dev/block/by-name/omarchy; R=/data/local/omarchy-dev; I=/data/local/omarchy-dev.img
case "$1" in
migrate)  # one-time: copy the image-file chroot onto the partition
  mkdir -p /data/local/omarchy-img /data/local/omarchy-part
  mount -t ext4 -o loop,ro $I /data/local/omarchy-img && mount -t ext4 $P /data/local/omarchy-part &&
  cp -a /data/local/omarchy-img/. /data/local/omarchy-part/ && sync && echo copied
  umount /data/local/omarchy-img; umount /data/local/omarchy-part ;;
mount)
  mkdir -p $R
  grep -q " $R " /proc/mounts || mount -t ext4 $P $R
  for d in dev dev/pts proc sys; do grep -q " $R/$d " /proc/mounts || mount --bind /$d $R/$d; done
  grep -q " $R/tmp " /proc/mounts || mount -t tmpfs tmpfs $R/tmp
  grep -q " $R/run " /proc/mounts || mount -t tmpfs tmpfs $R/run
  printf 'nameserver 8.8.8.8\nnameserver 1.1.1.1\n' > $R/etc/resolv.conf
  echo mounted ;;
umount)
  for d in run tmp sys proc dev/pts dev; do umount $R/$d 2>/dev/null; done
  umount $R && echo unmounted ;;
esac
