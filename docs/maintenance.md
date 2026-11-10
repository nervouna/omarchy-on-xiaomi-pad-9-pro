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
| `/usr/lib/loa/omarchy-menu-audit.py` (run by the post-upgrade script and apply-overlay) + `/usr/share/loa/omarchy/menu-hide` | Omarchy 4.0.6's menu offers its x86_64 catalogue on ARM. The audit reads each Install entry and the scripts it calls, checks their packages with `pacman -Sp` (AUR fallbacks: the AUR's `arch`), and hides the entries that can't work by setting `when` to `false` (original kept in `loaWhen`, the reason in `loaHidden`). `menu-hide` adds what no package check sees (no kernel headers for DKMS, no KVM). Hidden entries come back by themselves once their packages resolve. Run it without `--apply` for a report |
| `/etc/pacman.d/hooks/30-loa-chrome-sandbox.hook` -> `/usr/lib/loa/chrome-sandbox.sh` | The kernel has no user namespaces, so Chromium and Electron apps need their `chrome-sandbox` setuid root and abort otherwise. Fixes any that a package installs without the bit, and hands a package tree owned by a stray uid to root |
| plymouth units masked (`/etc/systemd/system/plymouth-*.service` -> /dev/null) | `omarchy-settings` depends on plymouth; with no initramfs or LUKS here it would only take DRM master from the stage 1 splash and Hyprland at boot and shutdown |
| `/usr/lib/loa/setup-omarchy-repo.sh` + the user hook `~/.config/omarchy/hooks/pre-refresh-pacman.d/loa-device` | Omarchy 4.0.6's `omarchy-refresh-pacman` (Update > Channel, reinstall) copies its **x86_64** template on ARM (no `[alarm]`, `[multilib]`); the hook puts back the aarch64 channel and `IgnorePkg` before it upgrades |

The post-upgrade script only notices a patch that stops applying. A patch whose
upstream fix leaves the patched lines alone keeps applying, so drop these by hand:

- `0006-shell-let-cloned-menus-see-their-kinds-through-the-panel-model.patch`:
  once Omarchy 4.5 is installed (fixed there by omacom/omarchy#13439). It only
  matters while a cloned menu plugin is enabled.

`0007` (font-set) and `0008` (restart-shell) are backports of fixes in Omarchy 4.5;
neither applies to v4.5.0-rc1, so the post-upgrade script reports them once 4.5
lands. Delete them then.

`0009` (bluetooth-power) is ours: Omarchy 4.5 turns Bluetooth off with
`rfkill block bluetooth`, which also blocks the chip's `bt_power` switch and kills
the stock HAL. The patch blocks only the controller (`hci0`). Keep it until
upstream stops blocking every Bluetooth switch.

Before a large update, tar the root to `/var/backups` (ext4: Omarchy's Snapper
snapshots don't exist here), as in "Backups" below without piping it off the
tablet. After it, reboot and check the desktop, touch, audio and Wi-Fi.

Mesa-KGSL (`/opt/omarchy-android/mesa`) is outside pacman. Its libraries must
still resolve after an update:
`LD_LIBRARY_PATH=/opt/omarchy-android/mesa/root/usr/lib ldd /opt/omarchy-android/mesa/root/usr/lib/libgallium-*.so | grep 'not found'`.
The builder now builds it without LLVM. The tablets' older build links
`libLLVM.so.22.1`; `/etc/pacman.d/hooks/20-loa-mesa-keep-llvm.hook` copies the
libLLVM it needs next to it before an llvm-libs upgrade removes it.

## Over-the-air updates (`loa-update`)

A tablet away from the Mac takes a new version of this repo's files over Wi-Fi.
Nothing runs on a timer: an update is installed only when the owner runs it.

```
sudo loa-update check             # installed version and the latest release's
sudo loa-update --diff            # download, verify, list what would change
sudo loa-update                   # download, verify, apply, record
sudo loa-update --tag <T>         # the bundle of release <T> (how a pre-release is tried)
sudo loa-update --file <PATH>     # a local bundle, <PATH>.sig beside it
sudo loa-update rollback          # undo the last applied update
sudo loa-update confirm           # keep an update now (it is kept by itself after 10 minutes on the desktop)
```

`releases/latest` never resolves to a pre-release, so a plain `loa-update` only
sees promoted releases. `--force` installs the same or an older version; an
unsigned or wrongly signed bundle is never installed.

**The bundle.** `tools/make-update-bundle.sh --version YYYYMMDD-N --out DIR
[--aquamarine PKG] [--key PRIVATE_KEY]` writes `DIR/loa-update.tar` (and with
`--key`, `DIR/loa-update.tar.sig`). It holds the committed `rootfs-overlay/`,
`user-defaults/` and `tools/overlay-install.sh` of `HEAD` (never the working
tree, so no git-ignored local input gets in), the patched Aquamarine package when
given, and `MANIFEST` (version, commit, sha256 of every member). Versions compare
as (date, N). The signature is `ssh-keygen -Y sign`, namespace `loa-update`; the
private key exists only as the Actions secret `LOA_UPDATE_SIGNING_KEY`, the
public one is `/usr/share/loa/update/allowed_signers`.

It does **not** hold Mesa-KGSL or `init_boot`: those stay wired and Fastboot-only.

**What `loa-update` does.** Before it writes anything: the signature over the
tar, no member that is absolute, contains `..` or is not a file, directory or
symlink, every member's sha256 against `MANIFEST`, and a version newer than the
installed one (a tablet with no recorded version, installed before this, counts
as older than any). Then it installs the bundled Aquamarine with
`LOA_AQUAMARINE=1 pacman -U`, but only when its version differs from the
installed one and the `libaquamarine.so` it provides is the one the installed
Hyprland depends on; otherwise the package is kept in
`/var/lib/loa-update/aquamarine/` and the output says why (install it by hand
together with the Hyprland that needs it, as under "Aquamarine" below). Then it
runs the bundle's own `overlay-install.sh apply` (the wired path, backups in
`/var/backups/loa-overlay/<time>/` included) and records the version.

**Rollback.** `loa-update rollback` restores the files the update replaced from
its backup, removes the files and directories it added, reinstalls the previous
Aquamarine if it changed it, and restores the recorded version. It is one level
deep: the last applied update. Not undone: units newly enabled by the install
script, and its other steps (pacman channel, groups, icons).

If the install script fails, `loa-update` rolls back what it did at once and
exits non-zero. An install that was killed (power loss, a closed terminal) is
rolled back by the next boot, or by the next `loa-update` before it installs
anything.

**Automatic rollback.** The marker `/var/lib/loa-update/pending` follows the
update from the install to the confirmed boot:

| Marker | Written by | The boot check (`loa-update-rollback.service`) does |
|---|---|---|
| `applying` | `loa-update`, before the install script runs | rolls back at once |
| `applied` | `loa-update`, after the install script succeeded | nothing in the boot that installed it; in a later boot, sets `tried` |
| `tried` | the boot check | rolls back: the last boot never reached `loa-boot-ok` |
| `booted` | `loa-boot-ok` (desktop up for 20 s) | rolls back: the last boot ended within its 10 minutes of trial |
| (none) | `loa-update confirm`, or a rollback | nothing |

The boot check runs before the early LoA units (`loa-mdev`, `loa-modules`,
`loa-zram`, `loa-vendor-import`) and udev, through the copy of `loa-update`
kept with the update's record, so an update that breaks early boot or ships a
broken `loa-update` is still rolled back. It reloads systemd after a rollback.

- **300 s deadline.** `loa-update-deadline.service`: 300 s into a boot whose
  marker is `tried` and that has not reached `loa-boot-ok` (no
  `/run/loa-boot-ok`), the tablet rolls the update back, resets the stage-1 boot
  counter and reboots by itself. It never acts on any other marker, so a boot
  without a pending update is never rebooted.
- **10 minutes of trial.** `loa-update-confirm.service` runs
  `loa-update confirm` 10 minutes after `loa-boot-ok` if `loa-desktop` is still
  active; that deletes the marker and the update is kept. `sudo loa-update
  confirm` does the same at once (only on `booted`). There is no confirm at
  shutdown: **a good update that is rebooted or powered off within its 10
  minutes is rolled back** by the next boot. Install it again (`sudo loa-update`, or
  `--file /var/lib/loa-update/cache/loa-update.tar` without a network) and let
  the desktop run 10 minutes.
- **Screen dark or touch dead after the reboot.** Hold Power until the tablet
  restarts, within the 10 minutes. **Placeholder, to be measured by the owner on
  the 8 GB tablet: how many seconds of holding Power force the restart, and that
  it boots Omarchy rather than Fastboot.** That boot finds `tried` or `booted`
  and rolls the update back. With systemd up but no desktop, the deadline does
  it after 300 s without a key press.

One update at a time: `loa-update` refuses a new update while the marker is
`applied`, `tried` or `booted` (also with `--force`), and says how to get out
(reboot and wait, `loa-update confirm`, or `loa-update rollback`). Do not run
`omarchy update` between an update and the boot that confirms it either: a
rollback would then undo the update on top of a changed system. `loa-update
check` shows the marker and the last rollback (time, version, and what
triggered it: `manual`, `install-failed`, `applying`, `tried`, `booted`,
`deadline`) before it downloads anything.

**State**, all in `/var/lib/loa-update/`: `version`, `pending` and
`pending-boot` (the boot id of the boot that installed the update), `last` (path
of the last update's record), `last-rollback`, `updates/<version>-<time>/` (its
backup directory, added files and directories, previous version, previous
Aquamarine package, install log, the `loa-update` that wrote it; `.rolled-back`
once undone), `aquamarine/` (package files kept for rollback, rebuilt from the
installed files when no package file exists, and held-back bundled ones) and
`cache/` (the last download, kept until a newer one has fully arrived). A fresh
image records the bundle version it was built from (build date and `0`).

`builder/test-loa-update.sh` tests all this in the CI build, in a chroot of the
built root with a throwaway key.

## Aquamarine (patched, `IgnorePkg = aquamarine`)

Hyprland runs on a patched Aquamarine (`patches/aquamarine-0001-shuntian-*.patch`):
- a split primary plane (the SDE dual mixer underruns on one 3200-px pipe);
- DMA-heap scanout buffers for KGSL;
- a forced MODE_ID on modeset (first-frame DMS fix; without it there's no backlight/DPMS).
The patch is for the tag in `builder/pins.conf` (v0.16.0, for Hyprland 0.57, since
2026-11-07). Rebuild whenever Hyprland moves to a new Aquamarine ABI (the guard hook above
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

## Root image from CI

`.github/workflows/build-image.yml` builds the from-scratch root image
(`builder/build-image.sh`, runbook 1A) on a GitHub-hosted `ubuntu-24.04-arm`
runner: it unpacks the signature-checked Arch Linux ARM tarball, enters it with
`chroot` and runs the builder there as root. It runs on every push to `main`, on
pull requests that touch `builder/`, `rootfs-overlay/`, `patches/`,
`user-defaults/`, `tools/overlay-install.sh` or the workflow, and on demand
(Actions > Build image > Run workflow). Two more jobs run on every push and pull
request: `check-public` (`tools/check-public.sh`) and `lint` (`tools/lint.sh`:
shell and Python syntax, shellcheck at error level).

The `ci` job passes when every other job passed or was skipped. It is the one
check that `main`'s branch protection requires, so pull requests land with
`gh pr merge --auto --squash` once it is green; direct pushes to `main` are
rejected.

The job checks the image (`sha256sum -c`, `zstd -t`, a 16 GiB size, `e2fsck -fn`
on the decompressed file) and uploads the artifact `omarchy-scratch-image` for
14 days: `omarchy-scratch-DATE.img.zst` and its `.sha256`. To get it:

```
gh run list --workflow build-image.yml --status success --limit 1
gh run download <run-id> -n omarchy-scratch-image -D /tmp/omarchy-image
(cd /tmp/omarchy-image && shasum -a 256 -c *.sha256)
```

The image has no SSH key, Android property snapshot or `images/pkgs` extras
(local-only inputs): add the key with `tools/apply-overlay.sh` after the first
boot, or build locally for an image that has them.

The job fails when the build log reports an Omarchy patch that no longer
applies (`LoA: WARNING: <patch> no longer applies`), except the patches listed
in `EXPECTED_STALE_PATCHES` at the top of the workflow (now `0007` and `0008`,
see above). When you delete a stale patch, remove it from that list too; when an
Omarchy update breaks another one, fix or drop the patch.

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
