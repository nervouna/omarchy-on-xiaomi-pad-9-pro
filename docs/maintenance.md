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

## Package updates (pacman)

Mirrors: TUNA/USTC first in `/etc/pacman.d/mirrorlist` (the official ALARM
mirror is very slow from China).

1. `pacman -Sy && pacman -Qu`, then review. Look carefully at anything touching Hyprland (needs
   an Aquamarine rebuild, below), systemd, mesa/glvnd, pipewire/wireplumber,
   NetworkManager, bluez.
2. Rollback copy: the package cache is wiped after every transaction and ALARM
   has no archive. Tar the files of the packages about to change
   (`pacman -Qlq PKG`) plus their `/var/lib/pacman/local` entries to `/root/rollback/`.
3. `pacman -Su`, then a reboot test.
4. Never install single packages on a stale sync db (partial upgrades). Check
   with `pacman -S --print` first.

## Aquamarine (patched, `IgnorePkg = aquamarine`)

Hyprland runs on a patched Aquamarine (`patches/aquamarine-0001-shuntian-*.patch`):
- a split primary plane (the SDE dual mixer underruns on one 3200-px pipe);
- DMA-heap scanout buffers for KGSL;
- a forced MODE_ID on modeset (first-frame DMS fix; without it there's no backlight/DPMS).
Rebuild whenever Hyprland moves to a new Aquamarine ABI:
check out the matching upstream tag, `git apply` the patch, build and install. Keep backups
of the old `.so` **outside** `/usr/lib` (ldconfig picks up stray `libaquamarine.so.*`).

## Packages the overlay expects

Installed by hand (the overlay doesn't install packages): `zram-generator` (masked, kept
for reference), `earlyoom`, `archlinuxarm-keyring`, `btop` (both in Omarchy's base list
but missing here), and from the AUR `fakeroot-tcp` (the kernel has no SysV IPC, so stock
`fakeroot` can't work; it has to be bootstrapped once without fakeroot) and `yay-bin`.
Omarchy's own repo (`[omarchy]`, pkgs.omarchy.org) is enabled by
`/usr/lib/loa/setup-omarchy-repo.sh` (apply-overlay, personalize). (`xorg-xrdb` + `libxmu` got installed for a reverted Xft.dpi preset; harmless.)
The golden image already contains them; check with `pacman -Q` after other installs.

## Things outside pacman

| What | How it's updated |
|---|---|
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
