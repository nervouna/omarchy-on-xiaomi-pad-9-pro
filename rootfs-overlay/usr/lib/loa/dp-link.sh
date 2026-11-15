#!/bin/sh
# DisplayPort link ceiling. The vendor DP driver caps the link at HBR2 (max_lclk_khz
# 540000). Through a dock that gives the display two lanes, 4K 60 Hz then trains at
# 18 bpp and the screen stays black; with HBR3 (810000) written before the desktop
# starts it trained at 24 bpp (30LR 2Ln) with a picture (issue #80). A dock already
# connected at boot may have trained before this write; re-plug it.
#
# The node is in debugfs and appears once the display modules load
# (loa-modules.service). A missing node is logged and is not a failure.
N=/sys/kernel/debug/drm_dp/max_lclk_khz
RATE=810000
for i in $(seq 1 50); do [ -e $N ] && break; sleep 0.2; done
[ -e $N ] || { echo "no $N, DP link ceiling left alone"; exit 0; }
echo "max_lclk_khz before: $(cat $N)"
echo $RATE > $N 2>/dev/null || { echo "max_lclk_khz $RATE not accepted, still $(cat $N)"; exit 1; }
echo "max_lclk_khz after: $(cat $N)"
