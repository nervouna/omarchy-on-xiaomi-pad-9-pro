# Maintenance

## Overlay workflow

- `rootfs-overlay/` = files the port **owns**. Edit here, preview with
  `tools/apply-overlay.sh --diff`, apply with `tools/apply-overlay.sh`. Every file it
  replaces is backed up first to `/var/backups/loa-overlay/<time>/`.
- `user-defaults/` = files the user may change: seeded only when missing.
- Never put a personal file (`~/.config/hypr/*.lua`, dotfiles) in `rootfs-overlay/`.
  Device Hyprland settings go in `/usr/share/loa/hypr/loa.lua`, which is loaded right after
  Omarchy's defaults and before the personal files, so the user always wins. The
  loader line in `hyprland.lua` is added by apply-overlay if missing.

## Updates (`omarchy update`)

Omarchy is installed from its own packages (`omarchy`, `omarchy-settings`) and
the tablet follows Omarchy's **aarch64 stable channel**: `[omarchy]`
(pkgs.omarchy.org) first, then Omarchy's Arch Linux ARM snapshot
(arm-stable-mirror.omarchy.org, about a day behind ALARM). Update the upstream
way: `omarchy update` (or the Update menu). It runs `pacman -Syu`, Omarchy's
migrations, the post-update hooks and `mise up`. Plain `pacman -Syu` is refused
by Omarchy's guard hook; `OMARCHY_ALLOW_DIRECT_PACMAN=1` overrides it.

What the tablet adds (all in `rootfs-overlay/`):

| Piece | Why |
|---|---|
| `IgnorePkg = aquamarine` + `/etc/pacman.d/hooks/10-loa-aquamarine-guard.hook` | Our Aquamarine is patched (below). When a new Hyprland needs a newer Aquamarine, pacman would install the stock one under `--noconfirm`; the guard aborts the whole transaction instead, with a message. Rebuild ours, install it with `LOA_AQUAMARINE=1 pacman -U ...`, update again |
| `/etc/pacman.d/hooks/95-loa-omarchy.hook` -> `/usr/lib/loa/omarchy-post-upgrade.sh` | After every Omarchy package change: re-applies `/usr/share/loa/omarchy/patches/*.patch` (a patch that stops applying is reported: check whether upstream fixed it), marks the migrations in `/usr/share/loa/omarchy/migrations-skip` as done, and lists pending migrations that touch boot, kernel modules, sshd or groups. Omarchy detects this tablet as `aarch64-qualcomm` (a Snapdragon laptop), so read those before they run |
| plymouth units masked (`/etc/systemd/system/plymouth-*.service` -> /dev/null) | `omarchy-settings` depends on plymouth; with no initramfs or LUKS here it would only take DRM master from the stage 1 splash and Hyprland at boot and shutdown |
| `/usr/lib/loa/setup-omarchy-repo.sh` + the user hook `~/.config/omarchy/hooks/pre-refresh-pacman.d/loa-device` | Omarchy 4.0.6's `omarchy-refresh-pacman` (Update > Channel, reinstall) copies its **x86_64** template on ARM (no `[alarm]`, `[multilib]`); the hook puts back the aarch64 channel and `IgnorePkg` before it upgrades |

Before a large update, tar the root to `/var/backups` (ext4: Omarchy's Snapper
snapshots don't exist here), as in "Backups" below without piping it off the
tablet. After it, reboot and check the desktop, touch, audio and Wi-Fi.

Mesa-KGSL (`/opt/omarchy-android/mesa`) is outside pacman. Its libraries must
still resolve after an update:
`LD_LIBRARY_PATH=/opt/omarchy-android/mesa/root/usr/lib ldd /opt/omarchy-android/mesa/root/usr/lib/libgallium-*.so | grep 'not found'`.
The builder now builds it without LLVM. The tablets' older build links
`libLLVM.so.22.1`; `/etc/pacman.d/hooks/20-loa-mesa-keep-llvm.hook` copies the
libLLVM it needs next to it before an llvm-libs upgrade removes it.

## Aquamarine (patched, `IgnorePkg = aquamarine`)

Hyprland runs on a patched Aquamarine (`patches/aquamarine-0001-shuntian-*.patch`):
- a split primary plane (the SDE dual mixer underruns on one 3200-px pipe);
- DMA-heap scanout buffers for KGSL;
- a forced MODE_ID on modeset (first-frame DMS fix; without it there's no backlight/DPMS).
Rebuild whenever Hyprland moves to a new Aquamarine ABI (the guard hook above
stops the update when that happens): check out the matching upstream tag,
`git apply` the patch, build and install with `LOA_AQUAMARINE=1`. Keep backups
of the old `.so` **outside** `/usr/lib` (ldconfig picks up stray `libaquamarine.so.*`).

## Packages the overlay expects

Installed by hand (the overlay doesn't install packages): `zram-generator` (masked, kept
for reference), `earlyoom`, `archlinuxarm-keyring`, `btop` (both in Omarchy's base list
but missing here), and from the AUR `fakeroot-tcp` (the kernel has no SysV IPC, so stock
`fakeroot` can't work; it has to be bootstrapped once without fakeroot; it provides
`fakeroot`, which the `omarchy` package depends on) and `yay-bin`.
The pacman channel (`[omarchy]` first, Omarchy's ALARM snapshot) is set by
`/usr/lib/loa/setup-omarchy-repo.sh` (apply-overlay, personalize). (`xorg-xrdb` + `libxmu` got installed for a reverted Xft.dpi preset; harmless.)
The golden image already contains them; check with `pacman -Q` after other installs.

## Things outside pacman

| What | How it's updated |
|---|---|
| Mesa-KGSL (`/opt/omarchy-android/mesa`) | `builder/build-image.sh` builds it; copy `out/mesa` over the tree (see "Updates" for the library check) |
| Aquamarine | our package, see above |
| mise | GitHub binary to `/usr/local/bin/mise` (check SHASUMS256) |
| Coding agents | `mise up` (alias `mup`), never their self-updaters |

## Backups

Full root backup to the Mac (the live system is fine; sockets are skipped):

```
tools/tssh 'tar --one-file-system --xattrs --acls --numeric-owner -cpf - -C / . | zstd -T8 -3 -q' > ~/LoA-backups/omarchy-root-$(date +%F).tar.zst
```

Keep backups out of this repository: they hold secrets.

## Memory

- 7.3 GiB usable on the 8 GB model.
- zram (`loa-zram.service`, zstd, RAM/2; zram-generator is masked because systemd sees no udev device events here) and earlyoom
  (`/etc/default/earlyoom`) are the safety net. systemd-oomd can't work here:
  the bootloader sets `cgroup_disable=pressure`.
- The journal is capped at 500 MB, because the keyboard driver logs every touchpad packet.
