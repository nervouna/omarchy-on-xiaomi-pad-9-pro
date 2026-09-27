#!/bin/sh
# The qca_cld3 Wi-Fi driver reads WCNSS_qcom_cfg.ini from the firmware dir, where the
# Android build only has a dangling symlink. Copy the device's own stock file from the
# vendor partition (mounted read-only at /android/vendor by loa-android). Unchanged:
# do NOT enable gEnableWoW=1 in it, the WPSS firmware crashes (engineering log).
# The Wi-Fi MAC file (wlan_mac.bin) comes from persist: tools/personalize.sh.
F=/usr/lib/firmware/wlan/qca_cld/wcn7750/WCNSS_qcom_cfg.ini
V=/android/vendor/etc/wifi/wcn7750/WCNSS_qcom_cfg.ini
[ -f "$F" ] && [ ! -L "$F" ] && exit 0
[ -f "$V" ] || { echo "setup-wlan-files: $V not mounted (loa-android)"; exit 0; }
mkdir -p "$(dirname "$F")"; rm -f "$F"; cp "$V" "$F"; echo "installed $F from vendor"
