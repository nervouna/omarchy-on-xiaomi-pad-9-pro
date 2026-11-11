# Native Omarchy port status

Last updated: 2026-11-12

## Goal

Boot the complete Omarchy desktop as the tablet's native operating system on
power-up, with no Android or PRoot, while keeping Fastboot recovery available.

## Status: working

Xiaomi Pad 9 Pro (`shuntian`, SM8845, slot B, stock OS4.0.5.0.XFPCNXM kernel
6.12.69-android16 GKI; the ROM is Android 17). Everything listed here was verified on the device; items
marked *user* were confirmed by looking at, touching or listening to the tablet.

The two test tablets (8 GB and 12 GB) were both reinstalled on 2026-11-11 from the
same CI-built image (`omarchy-scratch-20261110`): Omarchy 4.5.0-3, Hyprland 0.57.1-2,
patched Aquamarine 0.16.0-100, quickshell 0.3.2. On 4.5 the owner has verified the
display, touch, keyboard cover, sound, power key, charging and the Omarchy menu. The
pen and Bluetooth headphones are not yet re-checked on 4.5
([#38](https://github.com/nervouna/omarchy-on-xiaomi-pad-9-pro/issues/38)).

| Area | State |
| --- | --- |
| Automatic boot into native Omarchy (systemd, Hyprland, Omarchy shell) | works; root on its own `omarchy` partition (64 GiB on the 8 GB tablet, 192 GiB on the 12 GB one, carved from userdata); `ramdump` holds a fallback root on both |
| Display 3200x2136@120, no underruns | works (*user*) |
| GPU: Adreno 829 via KGSL Mesa (GL + Vulkan) for Hyprland and apps | works (*user*: smooth) |
| Touch (Xiaomi THP) with correct orientation | works (*user*) |
| Wi-Fi (NetworkManager + wpa_supplicant), NTP | works |
| Battery status (upower) | works |
| Speakers via PipeWire -> stock AGM/AudioReach | works (*user*) |
| Volume buttons / Omarchy volume OSD | works (*user*) |
| Boot stock Android on demand (`reboot-to-android`) | works |
| Built-in microphones via PipeWire -> stock PAL | works |
| Power button: short press screen off/on, hold -> Omarchy system menu | works (*user*) |
| Brightness control (panel0-backlight) | works (*user*) |
| Screen-off (DPMS), idle screen-off after 5 min (hypridle, no lock) | works (*user*); wake by power key, not touch |
| Suspend (s2idle) on battery while the screen is off (loa-sleepd) | works (*user*); wake by power key or keyboard key (not cover open, [#15](https://github.com/nervouna/omarchy-on-xiaomi-pad-9-pro/issues/15)) |
| Low battery: clean power-off at 3 % (loa-sleepd; RTC wake-ups re-check while asleep) | works (tested with a simulated 2 %, awake and asleep) |
| Keyboard backlight (auto in dim light, `loa-kbd-backlight`) | works (*user*: levels) |
| Bluetooth (stock HAL + bridge -> BlueZ): pairing, A2DP headphones | works (*user*) |
| Xiaomi pogo keyboard + touchpad (DSP relay, enable packets, libinput quirk) | works (*user*), incl. reattach |
| Keyboard cover: close = screen off, open = screen on (hall SW_LID) | works (*user*) |
| App launching (uwsm) | works (*user*) |
| Charging: battery auth (batterysecret), PPS fast charge via charge pumps | works: ~34 W with a Xiaomi 55 W adapter; adapter auth for full power in progress ([#16](https://github.com/nervouna/omarchy-on-xiaomi-pad-9-pro/issues/16)) |
| Omarchy setup menu (nvim) and default-agent picker (mise; agents via `mise use -g`) | works |
| Omarchy updates the upstream way (`omarchy update`: Omarchy's own aarch64 packages, its ALARM snapshot, its migrations) | works; both test tablets run 4.5.0-3 since their 2026-11-11 reinstalls (the 4.0.6 update of 2026-10-22 is superseded). Omarchy patches left: 0003, 0005, 0009; [#43](https://github.com/nervouna/omarchy-on-xiaomi-pad-9-pro/issues/43) drops 0006-0008 |
| Xiaomi Focus Pencil Pro: BLE pairing, pointer (hover/tap/drag), double tap = right click | works (*user*); pinch/swipes unused for now; motion sensors, haptics, pressure open ([#20](https://github.com/nervouna/omarchy-on-xiaomi-pad-9-pro/issues/20)) |
| Ambient light sensor (auto-brightness, own SSC client) | works (*user*) |
| Cameras ([#21](https://github.com/nervouna/omarchy-on-xiaomi-pad-9-pro/issues/21)), modem ([#22](https://github.com/nervouna/omarchy-on-xiaomi-pad-9-pro/issues/22)), other sensors and auto-rotate ([#18](https://github.com/nervouna/omarchy-on-xiaomi-pad-9-pro/issues/18)) | not attempted |

Fastboot was never touched. Power + Volume Down still enters it. Stage 1 also
reboots straight to Fastboot after 3 boots that never reach the desktop, and a
kernel panic reboots instead of parking in Qualcomm CrashDump mode.

## How it boots

1. `init_boot_b` holds `init_boot-omarchy.img`: a busybox stage-1 init plus the
   stock Android first-stage ramdisk. It loads the stock first-stage modules,
   mounts the ext4 root on the `omarchy` partition (64 GiB on the 8 GB tablet,
   192 GiB on the 12 GB one; carved from the front of userdata; falls back to the
   old copy on the 17 GiB `ramdump` partition) and switches to systemd. It can hand over to the stock Android
   init instead (one-shot flag from `reboot-to-android`, or Volume Up held
   early in boot).
2. systemd units load the stock vendor modules in Android's order, start the
   DSPs (ADSP/CDSP/WPSS), run the Xiaomi THP touch daemon, a USB debug gadget
   (SSH/serial) and the desktop.
3. Display: SDE dual-mixer panels underrun when one pipe scans out the whole
   3200-pixel width. Patched Aquamarine splits the primary plane in two
   (`AQ_DRM_SPLIT_PRIMARY`) and allocates scanout buffers from a DMA-BUF heap
   (`AQ_DRM_DMA_HEAP`) so the KGSL GPU can render into them.
4. Audio: stock Qualcomm userspace (pd-mapper, audioadsprpcd, servicemanager,
   audio HAL with AGM/PAL) runs natively in an Android-layout chroot backed by
   the read-only stock system/vendor/odm/dsp partitions. PipeWire's "Speakers"
   sink feeds it through a small relay.

## Where things are

See the repository [README](../README.md) for the layout and
[runbook](runbook.md) for installing on another tablet. The chronological
engineering log is [engineering-log.md](engineering-log.md).

## Restore stock Android permanently

```
fastboot flash init_boot_<slot> images/init_boot-stock-OS4.0.5.0.img
```

## Open items

Each item is tracked in its issue:

- Charging: Xiaomi adapter authentication for full power,
  [#16](https://github.com/nervouna/omarchy-on-xiaomi-pad-9-pro/issues/16).
- Standby drain: s2idle drains about 3.7 %/h, about the same as staying awake
  with the screen off, [#14](https://github.com/nervouna/omarchy-on-xiaomi-pad-9-pro/issues/14).
- Wake on cover open, [#15](https://github.com/nervouna/omarchy-on-xiaomi-pad-9-pro/issues/15);
  tap-to-wake, [#19](https://github.com/nervouna/omarchy-on-xiaomi-pad-9-pro/issues/19);
  auto-rotate, [#18](https://github.com/nervouna/omarchy-on-xiaomi-pad-9-pro/issues/18).
- Screensaver, [#23](https://github.com/nervouna/omarchy-on-xiaomi-pad-9-pro/issues/23).
- Headset jack, [#17](https://github.com/nervouna/omarchy-on-xiaomi-pad-9-pro/issues/17).
- Pen features (motion sensors, haptics, pressure, palm rejection),
  [#20](https://github.com/nervouna/omarchy-on-xiaomi-pad-9-pro/issues/20).
- Cameras, [#21](https://github.com/nervouna/omarchy-on-xiaomi-pad-9-pro/issues/21);
  modem, [#22](https://github.com/nervouna/omarchy-on-xiaomi-pad-9-pro/issues/22).
- Prebuilt images, [#24](https://github.com/nervouna/omarchy-on-xiaomi-pad-9-pro/issues/24).

Not tracked as an issue:

- Omarchy's Wi-Fi UI expects iwd, which can't run (the kernel lacks AF_ALG).
  NetworkManager is used instead; the Omarchy network panel uses
  NetworkManager directly.
- Memory: 8 GB model = 7.3 GiB usable. zram (3.6 GiB) + earlyoom keep heavy
  Electron/chat app mixes from freezing the tablet; a 12 GB model is the
  real fix.
