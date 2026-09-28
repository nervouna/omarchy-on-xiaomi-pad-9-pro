# Runbook: native Omarchy on another Xiaomi Pad 9 Pro

Target: a second `shuntian` (any RAM size). Everything the port needs from
Android (kernel modules, firmware, vendor daemons) is tied to the stock build
**OS4.0.5.0.XFPCNXM** (Android 17, GKI kernel 6.12.69 from the android16-6.12 branch), so the new tablet must run
exactly that build.

> Status: the from-scratch path (1A) was built and installed on a tablet on
> 2026-09-29 (build on another tablet running the port, first boot imported the
> vendor files by itself). Slot **a** is still untested.

## 0. What you need

- A Mac with Android platform-tools (`fastboot`, `adb`), `zstd`, `lz4`,
  `python3` (`brew install android-platform-tools zstd lz4`). `zig` and the
  NDK only matter if you rebuild the helpers (`tools/build.sh`).
- `images/init_boot-stock-OS4.0.5.0.img` (sha256 `61427d71…`): the
  `init_boot.img` from the official fastboot ROM of that build.
- `keys/loa_shuntian` (+ `.pub`): your SSH key for `tools/tssh`
  (`ssh-keygen -t ed25519 -N '' -f keys/loa_shuntian`). The repo ships no key;
  the builder and `tools/apply-overlay.sh` add `keys/*.pub` to root's
  `authorized_keys`. It's the only way in at first: the image's user password is locked.
- `rootfs-overlay/usr/lib/loa/android-props.tar.gz`: the Android property
  snapshot of *your* tablet (git-ignored; it holds serial numbers). Capture it
  with `tools/capture-android-props.sh` while stock Android runs with Magisk root.
- For 1A: an ARM64 Arch Linux ARM machine to build on (a tablet already
  running the port, an ARM64 container or VM, a GitHub ARM runner) with access
  to GitHub, crates.io and the Arch Linux ARM mirrors. For 1B: a working tablet.

## 1A. Build the root image from scratch (recommended)

```
builder/build-image.sh [OUTDIR]        # as root on the ARM64 build machine; ~30 min
```

It installs Arch Linux ARM packages (`builder/packages.txt`) into an empty root,
Omarchy at a pinned commit with `patches/omarchy/`, Mesa with the KGSL backend,
our patched Aquamarine and `ttfx` (built from pinned sources, `builder/pins.conf`),
then this repo's overlay through the same script `apply-overlay.sh` uses. Output:
`omarchy-scratch-DATE.img.zst` (16 GiB ext4, ~2.3 GiB compressed). The image
carries **no Xiaomi/Qualcomm files**: on its first boot, stage 1 copies the
first-stage modules and `loa-vendor-import.service` copies the second-stage
modules, firmware and touch libraries from the tablet's own partitions
(read-only). The build runs in a private mount namespace; local-only inputs
(your key, props snapshot, `images/pkgs/*.pkg.tar.zst`) are included if present.

## 1B. Or clone a working tablet

```
tools/make-image.sh --clean            # dry run: what is kept / dropped
tools/make-image.sh --clean --reset-hypr --apply   # ~15 min; -> images/omarchy-clean-DATE.img.zst
```

- `--clean` = golden image: no Wi-Fi profiles, Bluetooth pairings, browser or
  chat data, logins or shell history; password locked. Only the desktop config
  in the home whitelist is kept; `--reset-hypr` resets the personal Hyprland files.
- `--personal` = your full system minus per-device identity (to *move* to
  a new tablet). Treat that image like a password vault.
- It stages the image on the working tablet's `ramdump` partition, overwriting it.

## 2. Prepare the new tablet

1. Unlock the bootloader (Xiaomi's procedure).
2. Flash the official fastboot ROM **OS4.0.5.0.XFPCNXM** (`flash_all`). Boot
   Android once to be sure it works; its data doesn't matter.
3. Note the active slot: `fastboot getvar current-slot`. The first tablet ran
   slot **b**. Stage 1 and the island derive the slot at runtime
   **(untested on slot a)**.

## 3. Build the boot image (Mac)

```
python3 boot/build-init-boot.py        # -> images/init_boot-omarchy.img
```

It packs `boot/initramfs` (busybox stage 1, `loa-helper`) plus the stock
first-stage ramdisk (so Android can still be booted) into the stock `init_boot`
header. Stage 1 mounts the first of `omarchy`, `ramdump` that exists and mounts.

## 4. Install (tablet in Fastboot: Power + Volume Down, USB to the Mac)

```
tools/install.sh images/omarchy-scratch-DATE.img.zst     # or omarchy-clean-DATE
```

- It checks product `shuntian`, the unlock state and the slot, verifies the digest, then flashes
  the image to `ramdump` and our `init_boot` to the active slot, and reboots.
  macOS fastboot can't send a multi-GB raw file, so it converts the image to
  Android sparse format first (`tools/img2simg.py`).
- To try a new image on a tablet that already runs the port from its `omarchy`
  partition, without touching it: `LOA_INIT_BOOT=images/init_boot-omarchy-test-ramdump.img`
  (built with `LOA_ROOT_PARTS="ramdump omarchy" LOA_INIT_BOOT_OUT=... python3 boot/build-init-boot.py`).
  Flashing the normal `init_boot-omarchy.img` switches back.
- The first boot of a from-scratch image takes ~30 s longer (vendor import).
- The desktop appears in about a minute. `tools/tssh uptime` should answer: SSH runs over
  the USB gadget network, IPv6 link-local, with no Mac setup.
- **(untested)** If the bootloader refuses `fastboot flash ramdump`, use the
  Magisk route instead:
  1. flash a Magisk-patched stock init_boot and boot Android;
  2. `adb push` the raw image to `/data/local/tmp`;
  3. `adb shell su -c dd if=/data/local/tmp/omarchy.img of=/dev/block/by-name/ramdump bs=16M`;
  4. back in Fastboot, flash `images/init_boot-omarchy.img` to `init_boot_<slot>`.

## 5. Personalize (native Omarchy)

```
tools/personalize.sh [hostname]        # Wi-Fi MAC from persist, machine-id,
                                       # SSH host keys, pacman keyring, hostname
tools/tssh -t passwd omarchy           # sudo password (autologin doesn't need it)
tools/apply-overlay.sh                 # bring the image up to the repo's overlay
tools/tssh systemctl reboot
```

Then connect Wi-Fi (Omarchy menu or `nmcli dev wifi connect SSID --ask`).
NTP fixes the clock. Bluetooth reads its address from `persist` at every
boot, so nothing to do there.

The Android daemons read the property snapshot from
`rootfs-overlay/usr/lib/loa/android-props.tar.gz` (see section 0). An image
carries the snapshot of whoever built it (same build, so only the serials
differ); capture your own and re-run `tools/apply-overlay.sh`.

Mirrors: the image uses Arch Linux ARM's default mirror list; pick closer ones
in `/etc/pacman.d/mirrorlist` if downloads crawl.

Check: `tools/tssh 'systemctl --failed; journalctl -b -u loa-android | tail'`,
where `android-parts.sh` logs the slot and the super mapping it used.

## 6. Bigger root (optional, wipes Android's data)

The image lives on `ramdump` (17 GiB). To carve a larger root from the front of
Android's userdata:

```
tools/repartition.sh 64                # plan: prints the new GPT, changes nothing
tools/repartition.sh 64 --apply        # GPT, frozen copy, grow, wipe userdata
tools/tssh systemctl reboot            # stage 1 now mounts `omarchy`
```

The `ramdump` copy stays as a rollback (label `omarchy-old`). Android
re-formats its smaller userdata on its next boot; expect Xiaomi/Google account
activation. Leave Android at least 16–20 GiB: its OTAs stage into userdata.

## 7. Afterwards

- Re-apply LoA files at any time: `tools/apply-overlay.sh`.
- Coding agents: `mise install` (Omarchy manages them with mise).
- Updates: see [maintenance.md](maintenance.md). Never update Hyprland without
  rebuilding the patched Aquamarine.

## Recovery

| Situation | Way out |
|---|---|
| Boot loops / no desktop | After 3 boots that never reach `loa-boot-ok`, stage 1 goes to Fastboot by itself |
| Want Android | Hold **Volume Up** right after the logo, or `reboot-to-android` in Omarchy |
| Back to stock for good | `fastboot flash init_boot_<slot> images/init_boot-stock-OS4.0.5.0.img` |
| New root broken after repartition | `fastboot flash init_boot_<slot>` an image whose stage 1 only knows `ramdump`, or remove the `omarchy` partition |
| Fastboot | Power + Volume Down; the bootloader is never written by any tool here |
