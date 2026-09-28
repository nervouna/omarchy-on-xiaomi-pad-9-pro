# Third-party components

The MIT license in `LICENSE` covers the original work in this repository. These
parts are not original and keep their own licenses:

| Path | Component | License | Source |
|---|---|---|---|
| `boot/busybox-static`, `rootfs-overlay/usr/lib/loa/busybox` | BusyBox 1.36.1, unmodified static build from Ubuntu's `busybox-static` (arm64) package `1:1.36.1-6ubuntu3.1` | GPL-2.0-only | <https://launchpad.net/ubuntu/+source/busybox/1:1.36.1-6ubuntu3.1>, upstream <https://busybox.net> |
| `patches/aquamarine-*.patch` | A patch against [Aquamarine](https://github.com/hyprwm/aquamarine) (Hyprland's rendering backend) | BSD-3-Clause, like Aquamarine | — |
| `patches/omarchy/0001-0003` | Patches from the [omarchy-android](https://github.com/nervouna/omarchy-android) project against [Omarchy](https://github.com/basecamp/omarchy) (their PRoot code paths are inactive natively) | MIT (Omarchy; omarchy-android © BlackFireAlex) | — |
| `rootfs-overlay/usr/local/bin/{Xwayland,omarchy-voxtype-*,omarchy-dbus-service}` | Runtime scripts from omarchy-android, unmodified | MIT, © BlackFireAlex | omarchy-android `runtime/guest/root` |
| `builder/in-builder.sh` Mesa options | Build recipe from omarchy-android; the image contains Mesa built from [mesa-for-android-container](https://github.com/lfdevs/mesa-for-android-container) (KGSL backend) | MIT AND BSD-3-Clause AND SGI-B-2.0 (Mesa) | pinned in `builder/pins.conf` |

Images built by `builder/build-image.sh` also contain [ttfx](https://github.com/omacom/ttfx) (MIT, built from the commit pinned in `builder/pins.conf`), Arch Linux ARM and Omarchy packages under their own licenses, and Omarchy itself (MIT).

Referenced, not included:

- [libssc](https://codeberg.org/DylanVanAssche/libssc) (GPL-3.0): its reverse-engineered
  SSC protobuf definitions were read to learn the field numbers used by
  `rootfs-overlay/usr/lib/loa/loa_ssc.py`. No libssc code is copied.
- Xiaomi and Qualcomm binaries (the stock `init_boot`, vendor libraries, firmware,
  Android vendor daemons) are **not** in this repository. The tools fetch them from
  your own tablet or the official ROM at install time. `reference/` holds short
  captures (logs, debugfs state) taken from a stock device for interoperability work.

Xiaomi, Snapdragon and Omarchy are trademarks of their owners. This project is not
affiliated with or endorsed by Xiaomi, Qualcomm, or the Omarchy project.
