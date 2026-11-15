# Maintenance

## Overlay workflow

- `rootfs-overlay/` = files the port **owns**. Edit here, preview with
  `tools/apply-overlay.sh --diff`, apply with `tools/apply-overlay.sh`. Every file it
  replaces is backed up first to `/var/backups/loa-overlay/<time>/`.
- `user-defaults/` = files the user may change: seeded by the first install (the image
  build, `LOA_FIRST_INSTALL=1`) only. An update (`tools/apply-overlay.sh`, `loa-update`)
  changes nothing under `/home`; it prints `differs from the default: <path>` for each
  file that is missing or differs from the installed copy.
- `/etc/hostname` is not in the overlay: the image build writes `shuntian` and an update
  never replaces it. Rename a tablet with `hostnamectl set-hostname NAME`.
- Never put a personal file (`~/.config/hypr/*.lua`, dotfiles) in `rootfs-overlay/`.
  Device Hyprland settings go in `/usr/share/loa/hypr/loa.lua`, which is loaded right after
  Omarchy's defaults and before the personal files, so the user always wins. An update
  does not edit `hyprland.lua` or any other file in the home directory.

## Updates (`omarchy update`)

Omarchy is installed from its own packages (`omarchy`, `omarchy-settings`) and
the tablet follows Omarchy's **aarch64 stable channel**: `[omarchy]`
(pkgs.omarchy.org) first, then Omarchy's Arch Linux ARM snapshot
(arm-stable-mirror.omarchy.org, about a day behind ALARM). Update the upstream
way: `omarchy update` (or the Update menu). It runs `pacman -Syu`, Omarchy's
migrations, the post-update hooks and `mise up`. Plain `pacman -Syu` is refused
by Omarchy's guard hook; `OMARCHY_ALLOW_DIRECT_PACMAN=1` overrides it. The image
ships no sync databases (a build's would be newer than Omarchy's snapshot and make
`pacman -S` fail with 404), and `tools/personalize.sh` ends with `pacman -Syy`.

What the tablet adds (all in `rootfs-overlay/`):

| Piece | Why |
|---|---|
| `IgnorePkg = aquamarine` + `/etc/pacman.d/hooks/10-loa-aquamarine-guard.hook` | Our Aquamarine is patched (below). When a new Hyprland needs a newer Aquamarine, pacman would install the stock one under `--noconfirm`; the guard aborts the whole transaction instead, with a message. Rebuild ours, install it with `LOA_AQUAMARINE=1 pacman -U ...`, update again |
| `/etc/pacman.d/hooks/95-loa-omarchy.hook` -> `/usr/lib/loa/omarchy-post-upgrade.sh` | After every Omarchy package change: re-applies `/usr/share/loa/omarchy/patches/*.patch` (a patch that stops applying is reported: check whether upstream fixed it), marks the migrations in `/usr/share/loa/omarchy/migrations-skip` as done, and lists pending migrations that touch boot, kernel modules, sshd or groups. Omarchy detects this tablet as `aarch64-qualcomm` (a Snapdragon laptop), so read those before they run |
| `/usr/lib/loa/omarchy-menu-audit.py` (run by the post-upgrade script and apply-overlay) + `/usr/share/loa/omarchy/menu-hide` | Omarchy 4.0.6's menu offers its x86_64 catalogue on ARM. The audit reads each Install entry and the scripts it calls, checks their packages with `pacman -Sp` (AUR fallbacks: the AUR's `arch`), and hides the entries that can't work by setting `when` to `false` (original kept in `loaWhen`, the reason in `loaHidden`). `menu-hide` adds what no package check sees (no kernel headers for DKMS). Hidden entries come back by themselves once their packages resolve. Run it without `--apply` for a report. It changes nothing while pacman has no sync databases (a fresh image has none until `pacman -Syy`) |
| `/etc/pacman.d/hooks/30-loa-chrome-sandbox.hook` -> `/usr/lib/loa/chrome-sandbox.sh` | The kernel has no user namespaces, so Chromium and Electron apps need their `chrome-sandbox` setuid root and abort otherwise. Fixes any that a package installs without the bit, and hands a package tree owned by a stray uid to root |
| plymouth units masked (`/etc/systemd/system/plymouth-*.service` -> /dev/null) | `omarchy-settings` depends on plymouth; with no initramfs or LUKS here it would only take DRM master from the stage 1 splash and Hyprland at boot and shutdown |
| `/usr/lib/loa/setup-omarchy-repo.sh` + the wrapper `/usr/local/bin/omarchy-hook` | Omarchy 4.0.6's `omarchy-refresh-pacman` (Update > Channel, reinstall) copies its **x86_64** template on ARM (no `[alarm]`, `[multilib]`); the wrapper runs it for `pre-refresh-pacman` and puts back the aarch64 channel and `IgnorePkg` before it upgrades |

The post-upgrade script only notices a patch that stops applying. A patch whose
upstream fix leaves the patched lines alone keeps applying, so drop such a patch
by hand once its fix is installed: delete the file and add its path to the
"dropped patches" list in `tools/overlay-install.sh`, which takes the change out
of the installed Omarchy files again and removes the patch from the tablets.
`0006`, `0007` and `0008` went that way with Omarchy 4.5 (2026-11-11).

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
private key exists only as the secret `LOA_UPDATE_SIGNING_KEY` of the GitHub
environment `update-signing`, which only the branch `main` may deploy to; the
public one is `/usr/share/loa/update/allowed_signers`.

It does **not** hold Mesa-KGSL or `init_boot`: those stay wired and Fastboot-only.

**Cutting a release.** From `main`, by hand:

```
gh workflow run release-update.yml --ref main -f version=YYYYMMDD-N
```

or Actions > Release update > Run workflow on `main`. `N` is one more than the
highest N ever used that day, and **a version is never reused**, released or
withdrawn. Nobody pushes `update-*` tags by hand: the workflow creates the tag.
`.github/workflows/release-update.yml` runs two jobs, both only on `main`.
`build` (no secret) checks out the `main` commit the run started on and runs
`tools/check-update-tag.sh`: the version must be exactly `YYYYMMDD-N` and newer,
as (date, N) with N a number, than every existing `update-*` git tag **and**
every release (the union, so a withdrawn release whose tag was kept still blocks
its version). Then it builds the unsigned overlay-only bundle with
`tools/make-update-bundle.sh` and hands it on as an artifact. `release` is the
only job with the environment `update-signing`: it checks out no code and runs no
repository script. It re-validates the version, refuses when the tag
`update-<version>` already exists, checks the bundle's `MANIFEST` against the
version and the commit, signs the tar (`ssh-keygen -Y sign -n loa-update`, key in
a mode-600 file that an `always()` step removes), verifies the signature against
`allowed_signers` at that commit, and creates the tag and a **pre-release**
(`gh release create update-<version> ... --target <commit> --prerelease
--latest=false`) with `loa-update.tar` and `loa-update.tar.sig`. The release notes
hold the version, the commit, the sha256 of `loa-update.tar` and the canary
checklist. The test of the version gate is `tools/test-check-update-tag.sh`
(runs on macOS and Linux, and in the `lint` job). The Aquamarine package is not
bundled yet (#45); the workflow marks the place and the version rule it needs.

What stands between a commit and the signing key: the environment `update-signing`
admits only the branch `main` (Settings > Environments > update-signing >
Deployment branches and tags; GitHub enforces it whatever the workflow file on
another ref says), and `main` takes changes only through pull requests with the
`ci` check. The `if: github.ref == 'refs/heads/main'` on the jobs is a
convenience, not the gate.

**Canary, then promote.** `releases/latest` ignores a pre-release, so no tablet
gets it by itself. On the 8 GB tablet:

1. `sudo loa-update --tag <tag>` over Wi-Fi.
2. At once, before the reboot and before any `check` or `--diff` (they download again): `sha256sum /var/lib/loa-update/cache/loa-update.tar` equals the sha256 in the release notes.
3. Reboot; desktop, touch, audio and Wi-Fi work.
4. After 10 minutes on the desktop the marker is gone (`/var/lib/loa-update/pending` does not exist).
5. `sudo loa-update check --tag <tag>` passes (it verifies the release against its own installed `allowed_signers`, so a release that locks itself out fails here).

Then Actions > Promote update > Run workflow (on `main`) with the tag and that
sha256, or `gh workflow run promote-update.yml --ref main -f tag=<tag> -f sha256=<sha256>`.
`promote-update.yml` downloads the two assets, fails unless the tar's sha256
equals the input, the signature verifies against `main`'s `allowed_signers`, the
release is a pre-release and no newer version is already latest; then it clears
the pre-release flag and marks it latest. It uploads nothing, so the promoted
bytes are the tested bytes.

**Withdrawing a bad release.** `gh release edit <tag> --prerelease` (back to a
pre-release, if it was promoted) or `gh release delete <tag>` **without**
`--cleanup-tag`: the tag stays, so the version is never reused, and
`releases/latest` resolves to the previous release. A tablet that already
installed it goes back with `sudo loa-update rollback` while it is still within
its trial; otherwise ship a newer release (versions only go up).

**What `loa-update` does.** Before it writes anything: the signature over the
tar, no member that is absolute, contains `..` or is not a file, directory or
symlink, every member's sha256 against `MANIFEST`, and a version newer than the
installed one (a tablet with no recorded version, installed before this, counts
as older than any). Then it writes the update's record (the package of the
installed Aquamarine to go back to, the backup directory, the files it will
add), `last` and the marker `applying`, and syncs, before anything of the system
is replaced. Then it installs the bundled Aquamarine with
`LOA_AQUAMARINE=1 pacman -U`, but only when its version differs from the
installed one and the `libaquamarine.so` it provides is the one the installed
Hyprland depends on; otherwise the package is kept in
`/var/lib/loa-update/aquamarine/` and the output says why (install it by hand
together with the Hyprland that needs it, as under "Aquamarine" below). Then it
runs the bundle's own `overlay-install.sh apply` (the wired path, backups in
`/var/backups/loa-overlay/<time>/` included; each backup is synced before its
original is replaced) and records the version.

**Rollback.** `loa-update rollback` restores the files the update replaced from
its backup, removes the files and directories it added, reinstalls the previous
Aquamarine if it changed it, and restores the recorded version. It is one level
deep: the last applied update. Not undone: units newly enabled by the install
script, and its other steps (pacman channel, groups, icons).

If the Aquamarine install or the install script fails, `loa-update` rolls back
what it did at once and exits non-zero. An install that was killed in either
step (power loss, a closed terminal) is rolled back by the next boot, or by the
next `loa-update` before it installs anything. A rollback removes a stale
`/var/lib/pacman/db.lck` before it reinstalls Aquamarine, but only when no
pacman process runs.

**A rollback that cannot complete** (a file it cannot copy back, a failed
Aquamarine reinstall) exits non-zero and leaves the marker `applying`, the
record and the installed version as they are: it is retried by every boot check
and by the next `loa-update`, and `sudo loa-update rollback` retries it by hand.
`loa-boot-ok` never promotes it and `loa-update confirm` refuses it. `sudo
loa-update check` shows it as

```
loa-update: update state: the rollback of <version> (<trigger>) did not complete: <reason>
loa-update:   the next boot, sudo loa-update rollback, or sudo loa-update retries it; until then <version> is neither kept nor undone
```

**Automatic rollback.** The marker `/var/lib/loa-update/pending` follows the
update from the install to the confirmed boot:

| Marker | Written by | The boot check (`loa-update-rollback.service`) does | The 300 s deadline does |
|---|---|---|---|
| `applying` | `loa-update`, before the Aquamarine step and the install script; every rollback, before it changes anything | rolls back | rolls back and reboots |
| `applied` | `loa-update`, after the install script succeeded | nothing in the boot that installed it; in a later boot, sets `tried` | nothing |
| `tried` | the boot check | rolls back: the last boot never reached `loa-boot-ok` | rolls back and reboots |
| `booted` | `loa-boot-ok` (desktop up for 20 s), only from `tried` | rolls back: the last boot ended within its 10 minutes of trial | nothing |
| anything else (an empty or cut-off write) | | rolls back if `last` names a record, else removes it | nothing |
| (none) | `loa-update confirm` (only from `booted`), or a completed rollback | nothing | nothing |

The deadline acts only in a boot without `/run/loa-boot-ok`. It resets the
stage-1 boot counter only after a completed rollback, and reboots either way, so
a rollback that keeps failing in a boot without a desktop ends in Fastboot after
stage 1's three attempts instead of rebooting forever; a boot with a desktop is
never rebooted.

The boot check runs before the early LoA units (`loa-mdev`, `loa-modules`,
`loa-zram`, `loa-vendor-import`) and udev, through the copy of `loa-update`
kept with the update's record, so an update that breaks early boot or ships a
broken `loa-update` is still rolled back. It reloads systemd after a rollback.
The deadline unit runs through the same dispatcher.

Both waits below are uptime (`/proc/uptime`), which counts time in suspend: a
tablet that suspends (cover closed, idle on battery) acts at its first wake
after them.

- **300 s deadline.** `loa-update-deadline.service`: 300 s into a boot whose
  marker is `tried` or `applying` and that has not reached `loa-boot-ok` (no
  `/run/loa-boot-ok`), the tablet rolls the update back, resets the stage-1 boot
  counter if the rollback completed, and reboots by itself. If `loa-desktop` is
  active at that point it first waits up to 60 s more for `loa-boot-ok`, whose
  own 20 s wait does not advance while the tablet is asleep (a tablet that
  suspends right after the desktop came up wakes past the 300 s before
  `loa-boot-ok`); a desktop that is not active (failed, or between restarts)
  gets no wait. It never acts on any other marker, so a boot without a pending
  update is never rebooted.
- **10 minutes of trial.** `loa-update-confirm.service` runs
  `loa-update confirm` 10 minutes after `loa-boot-ok` if `loa-desktop` is still
  active; that deletes the marker and the update is kept. It waits for a
  `loa-update check` or `--diff` that is running at that moment (a download
  gives up when it stays below 1 kB/s for 60 s, or after 30 minutes, per try;
  three retries). `sudo loa-update
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
check` shows the installed version, the marker and the last rollback (time,
version, and what triggered it: `manual`, `install-failed`, `applying`, `tried`,
`booted`, `deadline`) before it downloads anything, so a failed download still
shows them.

**State**, all in `/var/lib/loa-update/`: `version`, `pending` and
`pending-boot` (the boot id of the boot that installed the update), `last` (path
of the last update's record), `last-rollback`, `updates/<version>-<time>/` (its
backup directory, added files and directories, previous version, previous
Aquamarine package, install log, the `loa-update` that wrote it, and while a
rollback has not completed `rolling-back` and `rollback-error`; `.rolled-back`
once undone), `aquamarine/` (package files kept for rollback, rebuilt from the
installed files when no package file exists, and held-back bundled ones) and
`cache/` (the last download, kept until a newer one has fully arrived). A fresh
image records the bundle version it was built from (build date and `0`).

`builder/test-loa-update.sh` tests all this in the CI build, in a chroot of the
built root with a throwaway key.

## Kernel (`loa-kernel`)

The stock kernel has no user, PID or IPC namespaces, and they are built-in options:
no module adds them. The tablets can run a kernel this repo builds instead: the public
Android common kernel the stock one was built from (branch `android16-6.12-2026-03`,
6.12.69; every project pinned in `kernel/manifest.xml`) with `kernel/loa.fragment`
(`USER_NS`, `PID_NS`, `POSIX_MQUEUE`, `IPC_NS`; also `FHANDLE`, which systemd expects, and
the netfilter `addrtype` match, which Docker's rules need). Its release is
`6.12.69-android16-6-<kernel/VERSION>-4k`. The root image and the update bundle do not
carry it: it is installed over USB, per tablet, and the stock kernel stays one command
away. Everything in the overlay works on both kernels.

**Why the stock modules still load.** The modules check a CRC per imported symbol
(`CONFIG_MODVERSIONS`, derived from DWARF type information), not the release string.
The rebuilt kernel exports the same CRC as the stock one for every symbol the tablet's
974 modules import (#57). Options that change a structure the modules see cannot be
added: `SYSVIPC` changes `task_struct` and with it every CRC, so `fakeroot` keeps needing
`fakeroot-tcp`; `CGROUP_PIDS` changes 4224 CRCs, so there is no `pids` cgroup controller.
Try a new option as a pull request that edits `kernel/loa.fragment`: the `check` job says
whether it is safe.

**Build.** `.github/workflows/kernel.yml` (official Kleaf toolchain, about 35 minutes)
builds the tree twice, with the stock configuration (`baseline`) and with the fragment
(`loa`), and `kernel/compare-symvers.py` fails the run when a CRC of the baseline changed
or a symbol is gone. It runs on pull requests that touch `kernel/` or the workflow.
`kernel/prepare.sh` makes the two source changes: the release string, and
`EXPORT_SYMBOL_GPL` for `put_ipc_ns` and `init_ipc_ns`, which `rust_binder.ko` needs once
IPC namespaces are on (a gap in the Android common kernel). To publish a build:

```
gh workflow run kernel.yml --ref main -f release=true
```

creates the release `kernel-<release>` with `boot-gz.img`, the GKI modules
(`system_dlkm_staging_archive.tar.gz`), the configuration, the pinned manifest, the
source diff and `SHA256SUMS`. A new build gets a new `kernel/VERSION` (`loa2`, ...): the
GKI modules are signed with a key made for each build, so a kernel only loads its own.

**Install.** With the tablet on USB, running Omarchy with the current overlay:

```
tools/install-kernel.sh             # the newest kernel-* release
tools/install-kernel.sh --restore   # the stock kernel again
```

It copies the slot's stock `boot` image to `backups/` on the Mac, then runs
`loa-kernel install` on the tablet, which

- refuses unless the slot is marked successful and `boot` holds the stock kernel
  `6.12.69-android16-6-g586bfab1b9c5-abogki536749445-4k` (or a saved copy of it exists);
- keeps the stock image in `/var/lib/loa/kernel/boot_<slot>-stock.img`;
- builds `/usr/lib/modules/<new release>/`: hard links to the stock tree's `ramdisk/` and
  `vendor/` modules plus the rebuilt GKI modules. The stock tree is not touched;
- writes `boot_<slot>` and reads it back. Nothing else is written.

The boot image is put together on the tablet because `boot` is an AVB chain partition:
the unlocked bootloader accepts a digest mismatch, but refuses a `boot` whose vbmeta is
unsigned or whose footer is not at the end of the partition, and then stops in Fastboot
(`fastboot boot` fails as well while such an image is in flash). So the stock vbmeta and
footer stay in place and only the image in front of them is replaced, with the
gzip-compressed kernel: the uncompressed one does not fit.

`loa-kernel status` shows the running kernel, what `boot` holds and whether the stock
image is saved.

**If the tablet does not come up.** Hold Power + Volume Down for Fastboot, then
`fastboot flash boot_<slot> backups/boot-stock-<hash>.img` and `fastboot reboot`. From a
running system: `sudo loa-kernel restore`. Both module trees stay, so either kernel
boots.

**Android.** Android's own GKI modules (`system_dlkm`) are signed for the stock kernel
and the rebuilt one does not trust them. `reboot-to-android` therefore writes the stock
kernel back first; on the next Omarchy boot `loa-kernel-reinstall.service` writes the
rebuilt kernel again, and the restart after that runs it. Holding Volume Up at power-on
starts Android on whatever kernel is in `boot`: restore the stock kernel before using
that path.

**A new ROM.** `loa-kernel` only knows the stock kernel of OS4.0.5.0. After moving a
tablet to another ROM, restore the stock kernel first, and repeat the #57 comparison
against the new modules before building for it.

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

The tarball's signature is checked against the fingerprint pinned in the
workflow (`ALARM_KEY_FPR`). The public key itself is read from
`builder/archlinuxarm-keyring.gpg`, a copy of `archlinuxarm.gpg` from
github.com/archlinuxarm/archlinuxarm-keyring, so the job does not depend on a
keyserver. The bootstrap's `apt-get` and `pacman` downloads retry up to five
times, because runner networking drops out now and then.

The `ci` job passes when every other job passed or was skipped. It is the one
check that `main`'s branch protection requires, so pull requests land with
`gh pr merge --auto --squash` once it is green; direct pushes to `main` are
rejected.

The job checks the image (`sha256sum -c`, a full decompression, a 16 GiB size, `e2fsck -fn`
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
in `EXPECTED_STALE_PATCHES` at the top of the workflow (empty now). When an
Omarchy update breaks a patch, fix or drop the patch; list it there only while
the tablets still need it on an older Omarchy.

## Backups

Full root backup to the Mac (the live system is fine; sockets are skipped):

```
tools/tssh 'tar --one-file-system --xattrs --acls --numeric-owner -cpf - -C / . | zstd -T8 -3 -q' > ~/LoA-backups/omarchy-root-$(date +%F).tar.zst
```

Keep backups out of this repository: they hold secrets.

## Memory

- 7.3 GiB usable on the 8 GB model.
- zram (`loa-zram.service`, zstd, sized to RAM; zram-generator is masked because systemd sees no udev device events here) and earlyoom
  (`/etc/default/earlyoom`) are the safety net. systemd-oomd can't work here:
  the bootloader sets `cgroup_disable=pressure`.
- The journal is capped at 500 MB, because the keyboard driver logs every touchpad packet.

## CPU frequency

- The stock kernel command line sets `cpufreq.default_governor=performance`, and Android's
  post-boot script, which would switch to `walt`, does not run here. `loa-cpufreq.service`
  (`/usr/lib/loa/cpufreq-setup.sh`) sets `schedutil` on both policies once the cpufreq
  driver's module is loaded.
- Measured on the 8 GB tablet ([#60](https://github.com/nervouna/omarchy-on-xiaomi-pad-9-pro/issues/60)):
  0.6 W less than `performance` when idle, screen on or off; same sustained throughput;
  short bursts take 1.6 times as long. `walt` draws 0.14 W less than `schedutil` at its
  boot defaults with the screen off, but a short burst takes about three times as long
  without Android's input boost.
- To try another governor: `GOVERNOR=walt` in `/etc/default/loa-cpufreq`, then
  `systemctl restart loa-cpufreq`. The setting is runtime only; nothing is written to the boot image.
- The same service stops most of the idle frequency switching, which is what `schedutil`
  at its boot defaults pays over `walt`. Kernel RT threads carry `uclamp.min` 1024
  (`/proc/sys/kernel/sched_util_clamp_min_rt_default`), so each wake-up takes `policy0`
  from its lowest step to its highest, and `rate_limit_us` 45 lets `policy6` switch about
  20 times a second. The service writes 0 into the RT clamp (Android's post-boot script
  does the same) and then 10000 into `schedutil/rate_limit_us` on both policies.
- Measured on the 8 GB tablet ([#60](https://github.com/nervouna/omarchy-on-xiaomi-pad-9-pro/issues/60)):
  0.09 W less awake with the screen off (0.81 W to 0.72 W, the same as `walt`), 0.15 W
  less with a static screen on; ramp-up, burst latency and throughput unchanged. Neither
  setting works alone: the clamp alone changes nothing, and the rate limit alone draws
  more (0.91 W to 0.96 W), so the rate limit is written only after the clamp is accepted.
  Not measured: the latency of RT threads themselves (audio, touch and pen interrupt threads).
- To go back to the boot state: `RT_CLAMP_MIN=1024` and `RATE_LIMIT_US=45` in
  `/etc/default/loa-cpufreq`, then `systemctl restart loa-cpufreq`.
- The same service lowers the bus clock floor. The vendor bus DCVS driver starts
  `/sys/devices/system/cpu/bus_dcvs/{DDR,LLCC,DDRQOS}` with `boost_freq` at `hw_max_freq`
  "for better boot perf", and Android's post-boot script, which writes `hw_min_freq` into
  it, does not run here, so the memory and cache clocks stay at maximum. The service
  writes `hw_min_freq` into each `boost_freq`.
- Measured on the 8 GB tablet ([#60](https://github.com/nervouna/omarchy-on-xiaomi-pad-9-pro/issues/60)):
  0.24 W less (1.11 W to 0.87 W, 22 %) awake with the screen off; no change while the
  screensaver runs, since the clock is at maximum anyway; same sustained memory
  throughput. The cost: a short memory-heavy burst after a pause takes about 1.6 times as
  long (a 64 MiB copy: about 9 ms to 14 ms).
- To go back to the boot state: `BUS_FLOOR=max` in `/etc/default/loa-cpufreq`, then
  `systemctl restart loa-cpufreq`. A missing `bus_dcvs` directory or a refused write is
  logged but does not fail the unit.

## Idle

- hypridle (`~/.config/hypr/hypridle.conf`, a user default) is the only timer; its steps
  are in `/usr/lib/loa/idle.sh`, which reads the power source
  (`/sys/class/power_supply/usb/online`) when a step fires.
- On battery: after 1 min the backlight fades to 1 % (`loa-autobrightness` does it while
  `/run/user/1000/loa-idle-dim` exists, and writes the earlier value back without
  learning a bias), after 2 min the screen switches off and `loa-sleepd` suspends. The
  screensaver never starts, because the screen is off before Omarchy's 150 s
  (`idle.screensaver` in `~/.config/omarchy/shell.json`) and patch 0005 keeps it from
  launching on a dark screen: keep the second timeout below that value.
- On external power: Omarchy's screensaver at 150 s, screen off 5 min after that
  launch (it counts as activity), so 7.5 min after the last input.
- The power key and the cover wake the screen without hypridle seeing input, so
  `loa-autobrightness` also ends the dim whenever the panel comes back on.
- Double tap to wake: `loa-power-key` arms the touch controller's double-tap gesture
  (`loa-xtouch set 14 1`, read by the driver when the panel goes off) and disarms it
  while the cover is closed. The gesture arrives as `KEY_WAKEUP` on
  `NVTCapacitiveTouchScreen` and also wakes s2idle. After an idle screen-off Hyprland
  takes the key itself (`key_press_enables_dpms`); after a power-key screen-off the
  touchscreen is disabled in Hyprland, so `loa-power-key` reads the key. A single tap
  does nothing.
- To test the battery steps on the USB cable: `touch /run/user/1000/loa-idle-on-battery`.
- An installed `hypridle.conf` is never replaced by an update: `tools/overlay-install.sh`
  lists it as `differs from the default`, and the owner copies the new default over it
  (it applies from the next boot).

## Prebuilt helper binaries

Ten ELF binaries are tracked in git. `tools/check-helpers.sh` (the `helpers`
job of `.github/workflows/build-image.yml`, part of the `ci` check) fails when
a tracked ELF file is missing from this table or its sha256 differs, when
busybox differs from the Ubuntu package binary (only warns when no mirror has
the package any more), and, on a pull request, when a
source and the binary built from it do not change together. The sha256 column is
the file as committed.

| Binary | Source | Toolchain | Build command | sha256 |
|---|---|---|---|---|
| `boot/busybox-static` | Ubuntu `busybox-static` 1:1.36.1-6ubuntu3.1 (arm64), BusyBox 1.36.1, unmodified | Ubuntu's own build | extract `usr/bin/busybox` from `http://ports.ubuntu.com/ubuntu-ports/pool/main/b/busybox/busybox-static_1.36.1-6ubuntu3.1_arm64.deb` (deb sha256 `d96535e0402c011e0ee43449799df2f4504d44b842e4f2b3a6cbc845508eaafc`); once the version is superseded the mirrors drop it: the package page is `https://launchpad.net/ubuntu/+source/busybox/1:1.36.1-6ubuntu3.1` (a direct download from there was not established) | `52151e7f322f926b64049cdaa1410dc3ea6485525e0624b05813791c219ae933` |
| `rootfs-overlay/usr/lib/loa/busybox` | same file as `boot/busybox-static` | same | same | `52151e7f322f926b64049cdaa1410dc3ea6485525e0624b05813791c219ae933` |
| `boot/initramfs/loa/loa-helper` | `boot/loa-helper.c` | zig cc, Homebrew build on macOS (`.comment`: Homebrew clang 21.1.8); zig version not recorded | `tools/build.sh c`: `zig cc -target aarch64-linux-musl -O2 -static -s` | `07530fc75241b0eced959a3e718e92436c5fdfc6595c024aeb6ff1c7bfc5d6b0` |
| `rootfs-overlay/usr/lib/loa/loa-helper` | `boot/loa-helper.c`; `tools/build.sh` copies the boot one, but this file is a different build (30304 bytes against 35456) | same | same | `8e211fe07b0c93905b1f62c027bcd7e5cf04cd3298e8e28929c9f6abb44eba7a` |
| `rootfs-overlay/usr/lib/loa/loa-splash-off` | `tools/src/splash-off/loa-splash-off.c` | same | `tools/build.sh c` | `badc53289d6d6885e85eff67fc78612b5ec4b956e3dd677f017adc820f07c3c8` |
| `rootfs-overlay/usr/lib/loa/loa-xtouch` | `tools/src/xtouch/loa-xtouch.c` | same | `tools/build.sh c` | `c369465289589f3d209e278d47aa516ff609eb292f514b1e743626956a64dc9b` |
| `rootfs-overlay/usr/lib/loa/loa-thp-launcher` | `tools/src/thp-launcher/loa-thp-launcher.c` | Android NDK clang 22.0.1 (`.comment`; based on r584948b), LLD 21.1.8, links Bionic `libdl`/`libc`; the NDK release and API level are not recorded | not in `tools/build.sh`; command not recorded (`aarch64-linux-androidNN-clang -O2 ... -ldl`) | `c0f6e000e5f5684649fc96cf57d76ba15a02458df6746d03bac8bca938efb9ac` |
| `rootfs-overlay/opt/loa-android/loa/lib64/libloa_selinux_stub.so` | `tools/src/selinux-stub/libloa_selinux_stub.c` | Homebrew clang 21.1.8 and Homebrew LLD 21.1.8 (`.comment`), not the NDK that `tools/build.sh` names | `tools/build.sh ndk` line `aarch64-linux-android31-clang -O2 -fPIC -shared -nostdlib`, then `llvm-strip --strip-debug` | `2923d66035ab5a26d7c360c998758c20fd2c46f94dd27cc8c67313dd77ec8348` |
| `rootfs-overlay/opt/loa-android/loa/bin/loa-bthci` | `tools/src/loa-bthci/loa-bthci.cpp` | Android NDK r28c (clang 19.0.1); links the tablet's `libbinder_ndk.so` | `tools/fetch-device-libs.sh`, then `tools/build.sh ndk` (`aarch64-linux-android31-clang++ -O2 -std=c++17 -static-libstdc++ ... -lbinder_ndk`) | `50420143585db418e4739a635d9ad4e2bbf8ba0616a13469428663647fe26f56` |
| `rootfs-overlay/opt/loa-android/loa/bin/loa-pal` | `tools/src/loa-pal/loa-pal.cpp` | Android NDK r28c (clang 19.0.1); links the tablet's `libpalclient.so`, headers from CodeLinaro arpal-lx tag `lnx.2.0.r10-rel` | `tools/fetch-device-libs.sh`, then `tools/build.sh ndk` (`aarch64-linux-android35-clang++ -std=c++17 -O2 ... -lpalclient -Wl,--allow-shlib-undefined -static-libstdc++`) | `75b79baca4a4e217fffde0b3ea66a517ebcd3304df4d2c1d6fc606b7f9bc641b` |

Why only busybox is checked by content: a rebuild on a GitHub runner did not
reproduce any of the C helpers bit for bit. With official zig 0.14.1, 0.15.1,
0.15.2, 0.16.0, 0.17.0 and 0.17.1 (aarch64 Linux tarballs, the flags above) no
output matched, and the tracked files differ in layout, not only in metadata:
`boot/initramfs/loa/loa-helper` is 35456 bytes with a 0x1cb0 byte `.text` and a
`.tbss` section, where `boot/loa-helper.c` built today gives 37768 to 39424
bytes with a 0x15a0 byte `.text` and no `.tbss`. The two `loa-helper` copies
also differ from each other, so at least one was built from an older source. The
tracked binaries may therefore predate the current sources. `libloa_selinux_stub.so`
and `loa-thp-launcher` were not built with the NDK that `tools/build.sh` names
(Homebrew clang 21.1.8 and an Android clang 22.0.1 build, newer than NDK r30's
clang 21), and neither NDK r29 nor r30 reproduced them. The two NDK helpers that
link vendor libraries stay prebuilt (their provenance is the row above).

To replace a tracked binary, rebuild it with `tools/build.sh`, commit it in the
same pull request as the source change, update its sha256 here, and test it on a
tablet.
