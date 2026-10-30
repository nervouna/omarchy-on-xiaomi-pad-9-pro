# Omarchy on the Xiaomi Pad 9 Pro

**English** | [简体中文](README.zh-CN.md)

![Xiaomi Pad 9 Pro](https://img.shields.io/badge/device-Xiaomi%20Pad%209%20Pro-lightgrey)
![Host: macOS](https://img.shields.io/badge/host-macOS-lightgrey)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

<!-- banner -->

[Omarchy](https://omarchy.org) (Arch Linux ARM + Hyprland) running **natively**
on the Xiaomi Pad 9 Pro (codename `shuntian`, Qualcomm SM8845), booting
straight into the desktop on power-up. No Android framework, no chroot inside
Android, no PRoot: the tablet runs systemd, Hyprland and the Omarchy shell on the
stock Android GKI kernel. Android's own vendor daemons (audio, Bluetooth, sensors,
touch) run beside it in a small "service island".

<!-- screenshots -->

## Status

**Work in progress.** The port is daily-usable on the author's two test tablets
(8 GB and 12 GB). It is for people who own this exact tablet and are at home with an
unlocked bootloader, Fastboot and Arch Linux. It needs a Xiaomi Pad 9 Pro on stock
ROM `OS4.0.5.0.XFPCNXM`, a Mac for the host scripts, an ARM64 Arch Linux ARM machine
to build the image on, and Magisk root once; the full list is under
[Requirements](#requirements).

Installing flashes partitions on the tablet. A mistake can leave it unbootable,
unlocking the bootloader can void the warranty, and repartitioning wipes Android's
data. Read [Safety first](#safety-first) before you start.

Most of the hardware works; cameras, the modem, the headset jack, tap-to-wake and
auto-rotate do not. See [What works](#what-works), the hard limits of the stock
kernel under [Limits](#limits), and the details in [docs/status.md](docs/status.md).

There are no releases and no prebuilt images: you build the root image and the boot
image from source. Publishing prebuilt images is on the [Roadmap](#roadmap).
See [CONTRIBUTING.md](CONTRIBUTING.md) to report a bug or send a fix, and
[SECURITY.md](SECURITY.md) for security problems.

## Requirements

> [!IMPORTANT]
> - **An unlocked bootloader.** Nothing here unlocks it for you; that's Xiaomi's
>   own procedure.
> - **Xiaomi Pad 9 Pro (`shuntian`) on stock ROM `OS4.0.5.0.XFPCNXM`** (China ROM,
>   Android 17, GKI kernel 6.12.69 from the `android16-6.12` branch). The port reuses that build's kernel, modules, firmware
>   and vendor daemons: any other build or model will not work without porting work.
>   Tested on the 8 GB and 12 GB models.
> - **A Mac** with Android platform-tools, `zstd`, `lz4` and `python3`. The host
>   scripts are written for macOS.
> - **Magisk root on stock Android**, once, to capture your tablet's Android
>   properties (`tools/capture-android-props.sh`).
> - **An ARM64 Arch Linux ARM machine to build the image on**: an ARM64 container
>   or VM, or a tablet that already runs the port. It needs access to GitHub.

## What works

| Area | State |
|---|---|
| Automatic boot into Omarchy; Android still bootable on demand | works |
| Display 3200×2136 @ 120 Hz, GPU (Adreno 829 via KGSL Mesa, GL + Vulkan) | works |
| Touch, brightness, auto-brightness, screen-off, s2idle suspend | works |
| Wi-Fi, Bluetooth (incl. A2DP headphones) | works |
| Speakers, built-in microphones (PipeWire → stock Qualcomm audio stack) | works |
| Xiaomi pogo keyboard + touchpad, backlight, cover close/open | works |
| Charging (battery auth, PPS fast charge ~34 W) | works; full-power adapter auth in progress |
| Xiaomi Focus Pencil Pro as a pointer (auto-pairing, hover, tap, drag, double tap = right click) | works |
| Chinese input (fcitx5) | works |
| Cameras, modem, headset jack, tap-to-wake, auto-rotate | not yet |

Details and caveats: [docs/status.md](docs/status.md).

## Limits

The port runs on the stock kernel and firmware, which set some hard limits:

- **No user namespaces.** Anything that needs them (Flatpak/bubblewrap, rootless
  containers, systemd's `PrivateUsers=`) doesn't work; the overlay switches
  `PrivateUsers=` off for the affected services. Chromium's setuid sandbox works.
- **No deep sleep.** Deep suspend fails on resume (PMIC errors), so the tablet uses
  s2idle, only on battery, with Wi-Fi and Bluetooth off while asleep. Opening the
  cover doesn't wake it: press a key or the power button.
- **No memory pressure info** (`cgroup_disable=pressure` on the bootloader command
  line): no systemd-oomd; zram + earlyoom instead. 8 GB is tight for heavy
  Electron apps; 12 GB is comfortable.
- **No AF_ALG crypto sockets**: no iwd; NetworkManager instead.
- **No SysV IPC**: stock `fakeroot` (and so `makepkg`/AUR builds) fails;
  `fakeroot-tcp` from the AUR replaces it.
- **No devtmpfs**: `/dev` is populated by mdev, with udev layered on top.
- **Patched Aquamarine**: updating Hyprland means rebuilding Aquamarine with
  `patches/` (see [docs/maintenance.md](docs/maintenance.md)).

## My setup

What the author runs daily on it: [Clash Verge Rev](https://github.com/clash-verge-rev/clash-verge-rev)
in TUN mode (arm64 `.deb`, unpacked by hand), Codex installed through Omarchy's mise
agent picker, WeChat, and Lark (as a native Wayland app with
`--ozone-platform=wayland --enable-wayland-ime`, so fcitx5 works and it isn't
double-scaled). None of this is in the repo; it just shows what the port can carry.

## Roadmap

- **Prebuilt images**: the root image now builds from scratch and carries no
  vendor files (each tablet imports its own on first boot). Next: build it on
  GitHub's ARM runners and publish it, a first-login password instead of
  SSH-key-only access, and a property snapshot that doesn't need Magisk.
- **Focus Pencil Pro**: motion sensors (accelerometer + gyro, for air gestures),
  haptic feedback, pressure/tilt, palm rejection.
- **Charging**: Xiaomi adapter authentication for full-power charging.
- **Cameras**, **modem**, **headset jack**.
- **Tap-to-wake**, **wake on cover open**, **auto-rotate**.

## Safety first

**Rule #1: never lose Fastboot.** Nothing here writes the bootloader. The tools
only write `init_boot_<slot>`, `ramdump` and (optionally) a carved-out `omarchy`
partition. The stage-1 init reboots to Fastboot by itself after 3 boots that never
reach the desktop, and the stock `init_boot` restores Android.

Still: this flashes partitions on a device you own, voids what warranty unlocking
hasn't already voided, and may wipe Android's data (repartitioning does). Use a
tablet you can afford to lose. No warranty, see [LICENSE](LICENSE).

## Installing

Follow [docs/runbook.md](docs/runbook.md). In short:

```
tools/capture-android-props.sh          # stock Android + Magisk: your tablet's property snapshot
builder/build-image.sh                  # on an ARM64 Arch Linux ARM machine: root image from scratch
python3 boot/build-init-boot.py         # stage-1 boot image from the stock init_boot
tools/install.sh images/omarchy-scratch-*.img.zst  # new tablet in Fastboot
tools/personalize.sh                    # new identity (Wi-Fi MAC, host keys, ids)
tools/apply-overlay.sh                  # bring the system up to this repo; adds your SSH key
tools/repartition.sh 64 --apply         # optional: 64 GiB root instead of 17
```

You need your own SSH key in `keys/` (the repo ships none) and the stock
`init_boot` from the official ROM in `images/`.

## Going back to Android

Android stays bootable on demand. To make it the default again, flash the stock
`init_boot` from the official ROM back in Fastboot, to the slot you installed to
([docs/status.md](docs/status.md#restore-stock-android-permanently)):

```
fastboot flash init_boot_<slot> images/init_boot-stock-OS4.0.5.0.img
```

## Layout

| Path | What |
|---|---|
| `boot/` | Stage-1 init (busybox) + `loa-helper`, and `build-init-boot.py`, which packs them with the stock first-stage ramdisk into `init_boot` |
| `rootfs-overlay/` | System files the port owns (systemd units, daemons in `usr/lib/loa`, `/usr/share/loa/hypr/loa.lua` device settings, PipeWire/WirePlumber drop-ins in `/etc`). `tools/apply-overlay.sh` installs/updates them, backing up anything it replaces (`--diff` previews) |
| `user-defaults/` | Files the user may customise (hypridle, Chromium flags, fcitx5 profile): installed only if missing, never overwritten |
| `builder/` | From-scratch root image builder: package list, pinned sources, build scripts |
| `tools/` | Mac-side scripts: `tssh` (SSH over USB), install/image/repartition/personalize, `build.sh` for the native helpers (`tools/src`) |
| `patches/` | Aquamarine patch (split primary plane, DMA-heap scanout, forced MODE_ID); the small Omarchy patches live in `rootfs-overlay/usr/share/loa/omarchy/patches/` and are re-applied after each Omarchy update |
| `reference/` | Captures from stock Android (keyboard/pen packets, DRM/SDE state, logcat excerpts) and kernel crash logs |
| `docs/` | Runbook, status, maintenance, and the full engineering log |
| `images/`, `keys/` | Local only (git-ignored): boot and root images, your SSH key |

("LoA" in file names is the project's original working name.)

## Not in git

- **Xiaomi/Qualcomm binaries**: the stock `init_boot`, the vendor libraries the
  NDK helpers link against, firmware. Get them from the official ROM or your tablet
  (`images/README.md`, `tools/fetch-device-libs.sh`).
- **Device identity**: the Android property snapshot (serial numbers), Wi-Fi MAC,
  SSH keys. Each install creates or captures its own.
- **Root filesystem images**: multi-GB.

## Credits

- [Omarchy](https://omarchy.org), [Hyprland](https://hyprland.org) and
  [Arch Linux ARM](https://archlinuxarm.org).
- [libssc](https://codeberg.org/DylanVanAssche/libssc) for the reverse-engineered
  Qualcomm sensor protocol definitions.
- Built with a lot of help from AI coding agents; the
  [engineering log](docs/engineering-log.md) is the detailed trail.

Not affiliated with or endorsed by Xiaomi, Qualcomm or the Omarchy project.
Third-party components: [THIRD_PARTY.md](THIRD_PARTY.md).

## License

[MIT](LICENSE) © 2026 Xiaoyu Guan
