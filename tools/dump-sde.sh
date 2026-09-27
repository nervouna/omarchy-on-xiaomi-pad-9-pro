#!/system/bin/sh
# Dump SDE/DRM debug state (run as root). Usable on Android and native.
D=/sys/kernel/debug/dri/0
[ -d $D ] || mount -t debugfs debugfs /sys/kernel/debug
for f in $D/debug/core_perf/* $D/crtc208/status $D/crtc208/state $D/crtc208/fps $D/encoder69/status $D/debug/rm_status $D/DSI-1/output_bpc; do
  [ -f "$f" ] || continue
  echo "=== $f"; cat "$f" 2>&1 | head -150
done
echo "=== clocks"
grep -iE 'disp_cc_mdss_mdp_clk|mdss_byte|mdss_pclk|disp_cc_mdss_ahb' /sys/kernel/debug/clk/clk_summary 2>/dev/null | head -20
echo "=== icc"
grep -iE 'mdp|disp|mdss|ebi|llcc' /sys/kernel/debug/interconnect/interconnect_summary 2>/dev/null | head -60
echo "=== underrun"
dmesg | grep -ci underrun
