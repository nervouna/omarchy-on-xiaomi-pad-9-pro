# images/ (git-ignored)

| File | Source | sha256 |
|---|---|---|
| `init_boot-stock-OS4.0.5.0.img` | `init_boot.img` from the official fastboot ROM OS4.0.5.0.XFPCNXM (restore image) | `61427d71…` |
| `init_boot-omarchy.img` | `python3 boot/build-init-boot.py` | changes per build |
| `init_boot-magisk-*.img` | Magisk-patched stock init_boot (only for Android-side root work) | |
| `omarchy-{clean,personal}-DATE.img.zst` | `tools/make-image.sh` (+ `.sha256`) | |

2026-09-27 (rebuilt 19:41): `omarchy-clean-20260927.img.zst`, 3.6 GiB compressed, 17 GiB raw,
sha256 `3216b4c1…`, ext4 UUID `924b46d4-184e-48d7-9083-0d9067055ff6` (= the first tablet's ramdump;
origin checked). New overlay layout (loa.lua loader line, personal hypr files = templates + the
owner's own lines, audio drop-ins in /etc), Omarchy icon font linked, no Xft.dpi preset,
keyring/earlyoom/zram packages. Audited: nothing root-owned in the home,
no Wi-Fi/BT/proxy/agent/browser data, password locked, empty machine-id, no wlan_mac.bin.
Note: "clean" keeps the owner's own Hyprland lines (Caps<->Ctrl, natural scrolling, Super+Shift+S).
