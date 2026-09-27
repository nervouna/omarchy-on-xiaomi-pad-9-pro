#!/bin/sh
# binderfs for the stock Android service island (/dev/binder,hwbinder,vndbinder).
mkdir -p /dev/binderfs
mountpoint -q /dev/binderfs || mount -t binder binder /dev/binderfs
for b in binder hwbinder vndbinder; do ln -sf binderfs/$b /dev/$b; done
chmod 0666 /dev/binderfs/binder /dev/binderfs/hwbinder /dev/binderfs/vndbinder
