# Native Omarchy on Xiaomi Pad 9 Pro (shuntian) — working log

Ground rules (user, 2026-09-25): never lose Fastboot; goal = Omarchy boots
automatically on power-up; don't give up while options remain; document key
changes here.

## Layout
The lab material from the bring-up (stock images, probe init sources, captured
Android display state, one-off test tools) is not part of this repository; paths
like `probe/` or `stock-android/` below refer to it. `reference/` keeps the
excerpts that matter.

## Device state changes
- 2026-09-25: `init_boot_b` = Magisk-patched stock init_boot (temporary, for
  diagnostics). Magisk app installed; shell (uid 2000) granted root.
  **Undo:** `fastboot flash init_boot_b images/init_boot-stock-OS4.0.5.0.img`,
  uninstall `com.topjohnwu.magisk`.

## Findings
### Display "top strip + gray" = MDP underrun caused by one 3200-px-wide plane
- Native V13 logs: `sde_encoder_underrun_callback ... DSI-69 underrun` every frame;
  stock Android: 0 underruns.
- Stock HWC never feeds one pipe across the dual-LM (2×1600) boundary: every
  full-width layer is two planes, left half src/dst x=0 w=1600, right half
  x=1600 w=1600 (`stock-android/sde-debug.txt`).
- Reproduced on stock Android with composer stopped (`loa-kmstest`):
  - `-l single` (plane 98 covering 3200 px): underruns immediately.
  - `-l split` (planes 98+131, 1600 px each): no new underruns.
- => Hyprland/Aquamarine must never put a >1600-px-wide plane on this CRTC.

## Incidents
- 2026-09-25 ~02:44 (device time): kernel panic -> CrashDump (Qualcomm ramdump
  mode). The user put the tablet back into Fastboot by hand; Fastboot was fine.
  Cause (pstore `crashes/2026-09-25-kms-split-panic.txt`): Xiaomi
  `hang_detect.c:1454` BUG. It fires deliberately when the framework stays
  down: SurfaceFlinger/system_server had been stopped for about 4 minutes during the KMS
  hold. The display test itself did not cause it.
  **Rule:** on Android, keep compositor-stopped tests under 60 s and always
  restart `vendor.qti.hardware.display.composer` + `surfaceflinger` afterwards.

### 2026-09-25: split layout visually confirmed by the user
`loa-kmstest -l split -r 120` (planes 98+131, each 1600x2136, dumb XRGB8888 BO)
on stock Android: whole panel correct (bars, border, 256-row lines to the
bottom), 0 underruns. The display blocker is solved at the KMS level; what's
left is making the compositor use this layout.

## Native boot design (2026-09-25, Claude)
- Root filesystem: ext4 on the `ramdump` partition (17 GiB, label `omarchy`, moved
  to its own 64 GiB `omarchy` partition on 2026-09-27, see below;
  user-approved). It was all zeros and wasn't used by the stock build. No GPT change.
  Populated from `omarchy-native-v18.erofs`, then `pacman -Syu` (Hyprland 0.56.2,
  Aquamarine 0.15.1 patched and installed from source, `IgnorePkg = aquamarine`).
- On Android, `tools/devroot.sh mount` mounts it at /data/local/omarchy-dev as a
  chroot; `tools/dchroot` runs scripts in it. Android blocks sockets for uids
  >= 10000 without AID_INET; the build user is uid 5000 in group aid_inet (3003).
- Stock modules: system_dlkm + vendor_dlkm + vendor-ramdisk modules copied to
  /usr/lib/modules/<kver>/{kernel,vendor,ramdisk}; `depmod` search order in
  /etc/depmod.d/loa-android.conf; Android load order in /usr/lib/loa/modules/*.load.
  Firmware: /vendor/firmware + /odm/firmware -> /usr/lib/firmware,
  /vendor/firmware_mnt/image -> /usr/lib/firmware/image (firmware_class.path).
- `images/init_boot-omarchy.img` (built by `boot/build-init-boot.py`): stage-1
  busybox init (`boot/initramfs/init`):
  - loads the proven V9 module set;
  - sets `qcom_dload_mode.download_mode=0` so a panic reboots instead of
    going to CrashDump;
  - mounts PARTNAME=ramdump;
  - boot counter `/loa/boot-attempts`: after 3 failures -> USB rescue shell
    (300 s) -> Fastboot;
  - optional `/loa/dev-watchdog` (seconds) -> Fastboot unless
    `/run/loa-watchdog-disarm`;
  - then switch_root to systemd.
- Stage 2 units (`rootfs-overlay/`): loa-mdev (mdev -df), loa-modules
  (Android order, blocklist incl. hangdetect), loa-subsys (start ADSP/CDSP),
  loa-usb-gadget (ACM + ECM), sshd (key `keys/loa_shuntian`; `tools/tssh`),
  serial-getty@ttyGS0 autologin, seatd, loa-desktop (Hyprland,
  AQ_DRM_SPLIT_PRIMARY=1, llvmpipe for now), loa-boot-ok (clears the counter).

## 2026-09-25 native boot results
- First native boot from `init_boot-omarchy.img`: systemd + sshd over USB ECM worked.
  Fixed live: helper files missing their exec bit (overlay tar); seatd needs
  `SEATD_VTBOUND=0` (drop-in `seatd.service.d/novt.conf`, no VT in the GKI kernel).
- Second boot: fully automatic. Desktop active in under 1 min, split planes
  98+159, 0 underruns. **User confirmed the full display.**
- Touch = Xiaomi THP. The NT36536 sends raw frames through /dev/xiaomi-touch,
  and coordinates are computed in userspace (on Android, inside
  vendor.xiaomi.hw.touchfeature-service). Natively, `loa-thp.service` runs GPT's
  bundle (/opt/loa-thp, Bionic chroot, `.cfg` -> `.ini`).
  **Verified with the user touching:** 3001 IRQs and 120 KB of events on
  NVTCapacitiveTouchScreen in 25 s. Hyprland lists it as a touch device.
  Android maps raw axes with a plain scale (no rotation), so no calibration matrix.
- Testing lesson: an idle panel generates about 1 IRQ/s. Only capture touch while
  the user explicitly says they are touching (the early "no touch" results were
  capture-window misses).
- `tools/xtouch/loa-xtouch`: xiaomi_touch ioctl ABI (select id = _IO('T',3);
  mode = _IOWR('T',0,1032) {u8 id,u8 cmd,u16 mode,u16 len,u16 pad,s32 data[256]}).
  Turned out not to be needed.
- Rebooting to Fastboot from native: `systemd-run --on-active=2 /usr/lib/loa/loa-helper bootloader`.

- Touch axes are SWAPPED. Grouped corner-tap calibration: top-left raw (u=.80, v=.12),
  top-right (.79, .88), bottom-left (.17, .13), so screen x = v and screen y = 1 - u.
  **Hyprland always sets the libinput calibration matrix itself**, overriding a
  udev LIBINPUT_CALIBRATION_MATRIX (the udev rule had no effect: observed mapping
  == identity). Fix: `input.touchdevice.transform = 3` (matrix {0,1,0,-1,0,1}),
  output DSI-1, in hypr/input.lua. The udev rule is kept as the default for other
  libinput users. Two early mistakes: a 180-deg guess (ungrouped taps) and
  trusting the udev matrix.
- Android GKI has no user namespaces: units with `PrivateUsers=yes` fail with
  217/USER (upower, uuidd). Drop-ins set `PrivateUsers=no`.
- 2026-09-25: dev watchdog removed (/loa/dev-watchdog deleted). A clean reboot
  came up by itself: desktop, THP touch, upower, boot counter reset to 0,
  `systemctl is-system-running` = running. **User confirmed touch works.**
- `tools/apply-overlay.sh` re-applies rootfs-overlay/ over SSH (the overlay is
  the source of truth for everything LoA-specific in the root filesystem;
  /opt/loa-thp comes from probe/native-thp-v1.tar).
- Clock: no RTC write and no network, so the tablet started about 13 days behind. Set from the host (`tools/tssh "date -u -s @$(date +%s)"`); timesyncd clock file = floor for later boots. Needs Wi-Fi/NTP (or USB network sharing) to stay right.

## Wi-Fi (2026-09-25)
- WPSS remoteproc (99f00000, `wcn7750/wpss.mdt`) must be started (`echo start`),
  as for ADSP/CDSP. Now in start-subsys.sh.
- The qca_cld3 probe failed (-1) because /usr/lib/firmware/wlan/qca_cld/wcn7750/
  `WCNSS_qcom_cfg.ini` and `wlan_mac.bin` were dangling Android symlinks. Real
  files installed: the ini from the stock vendor.img (/etc/wifi/wcn7750), the MAC
  copied from the persist partition (/dev/sdf8, mounted read-only;
  wlan0=XXXXXXXXA7A9). The icnss2 "DMS QMI connection not established" message is
  harmless (Android logs it too).
- iwd is unusable: the GKI kernel lacks AF_ALG (CRYPTO_USER_API_*) and
  KEY_DH_OPERATIONS. Using NetworkManager + wpa_supplicant (userspace crypto,
  like Android). Packages were fetched on the Mac via `pacman -Sp` URLs (the
  tablet had no network). Don't `scp` files whose names contain ':' (epoch);
  use tar over SSH.
- Connected to the home Wi-Fi (NetworkManager profile on the tablet); NTP synced via 0.arch.pool.ntp.org.

## Audio (2026-09-25)
Speakers work through the stock Qualcomm AudioReach stack, running natively in an
"Android service island" (`/opt/loa-android`, `tools`: android-parts.sh,
android-chroot.sh, android-run):
- Stock system_b/vendor_b/odm_b are mapped **read-only** out of `super` with
  dm-linear (extents from lpdump; `dmsetup mknodes`, no udev). dsp_b (ext4) is
  mounted read-only as /vendor/dsp (DSP dynamic modules, e.g. CFCM.so.1). The
  runtime + i18n APEX payloads are loop-mounted at their zip offset. The
  property area is a snapshot of `/dev/__properties__` from a live Android
  boot (`android-props.tar.gz`). `loa-logd.py` is a stand-in logd, so stock
  daemon logs land in the journal (`journalctl -u loa-logd`).
  `libloa_selinux_stub.so` (LD_PRELOAD) answers libselinux calls with "allowed"
  (no SELinux policy loaded natively; servicemanager aborted in Access()).
- Boot chain: loa-subsys (ADSP up) -> loa-android -> loa-pd-mapper (stock
  service locator; without it the static audio PD returns ENOTCONN) ->
  loa-audiopd (`audioadsprpcd audiopd adsp`; needs libdl_android from the
  APEX; the ASoC card `alor-mtp-snd-card` then registers) -> loa-binder
  (binderfs) -> loa-servicemanager -> loa-suspend (agmplay takes a wakelock) ->
  loa-audiohal (`audiohalservice.qti` hosts `vendor.qti.hardware.agm.IAGM`;
  libaudiocorehal fails to load, which isn't needed).
- Speaker = backend TDM-LPAIF-RX-PRIMARY (6 ch, 48 kHz, 32-bit), six Awinic
  aw882xx amps (`aw_dev_N_switch=Enable`, `aw_dev_N_prof=Music`).
  `agmplay file.wav -D 100 -d 100 -num_intf 1 -i TDM-LPAIF-RX-PRIMARY`.
  **User confirmed loud and clear.**
- PipeWire: pipe-tunnel sink "Speakers" -> /run/loa-audio/speaker.fifo ->
  loa-audio-relay.py (starts agmplay on a streaming-WAV FIFO when audio
  arrives, stops after 3 s idle so the amps and DSP graph power down). WirePlumber:
  the ASoC ALSA device is disabled. **The V4L2 + libcamera monitors are
  disabled**, because the msm_vidc V4L2 nodes hang the v4l2 create-device hook
  and that stalled WirePlumber's whole event queue (no stream was ever linked).
  The user heard a tone from `pw-play`.
- Still open: vndservicemanager ("Could not become context manager"; not
  needed so far), microphones, headset jack, volume keys -> PipeWire volume.
- Full stock audio HAL now loads natively once the i18n APEX (libandroidicu) and
  /vendor/lib64/hw, /odm/lib64/hw are on LD_LIBRARY_PATH. Registered: audio core
  IModule, effect IFactory, BT audio provider, AGM, **PAL (IPAL)**, PAL event
  notifier. Its "AHAL init took more than 30 S, rebooting" watchdog is harmless
  (no property service to request the reboot).
- Volume: PipeWire applies the Speakers sink volume in software before the relay
  (measured). Omarchy's `omarchy-audio-output-volume` works. Physical buttons:
  gpio-keys = KEY_VOLUMEUP, pmic_resin = KEY_VOLUMEDOWN, pmic_pwrkey = power;
  all are Hyprland keyboards (the Omarchy XF86Audio bindings apply).
- Microphones: PARKED. Mixer path = `usr/lib/loa/mic-path.sh` (stock
  handset-dmic-endfire). `agmcap -D 100 -d 101 -i CODEC_DMA-LPAIF_RXTX-TX-3`:
  graph opens with dkv 0xA3000001/3/4 but graph_start fails inside the ADSP
  (no kernel error; GSL "CKVs mismatched 3 vs 4"). The right fix is a small PAL
  client (PAL derives the ckv/dkv), which needs a Bionic toolchain (NDK).
  mm-audio-ftm is legacy tinyalsa-only.

## Android / Omarchy selection at power-on (2026-09-25)
- init_boot-omarchy.img now also carries the stock Android first-stage ramdisk
  (its /init as /init.android; built by boot/build-init-boot.py from the stock
  init_boot). Stage 1 hands PID 1 to it (unmounting everything it mounted) when:
  - **Volume Up is held** during about 2 s early in boot (`loa-helper keys 2000`).
    Press it right after releasing Power, when the logo appears. Power+VolUp
    together is Xiaomi's recovery combo, and Power+VolDown is Fastboot; both
    are handled by the bootloader before our code, so they're unaffected.
  - `/loa/next-boot-android` exists (one-shot). Omarchy command:
    `reboot-to-android` (loa-reboot-android.service + polkit rule for omarchy).
- Verified: Omarchy -> reboot-to-android -> stock Android (boot_completed=1)
  -> `adb reboot` -> Omarchy (audio and Wi-Fi up). The Volume Up path is untested
  (needs the user).
- PRoot leftover: hypr/looknfeel.lua exported PULSE_SERVER=tcp:127.0.0.1:4715 (Android PulseAudio bridge) + DISPLAY=:0 for the whole session -> volume keys/pactl apps failed. Removed (file now in overlay).
- **Microphones work (2026-09-25).** `tools/loa-pal/loa-pal.cpp`: a small PAL
  client built with NDK r28c (toolchains/ndk-r28c) against the device's
  libpalclient.so and CodeLinaro arpal-lx `lnx.2.0.r10-rel` headers. Vendor PAL
  device ids differ from upstream: 30 (0x1e) = handset-dmic-endfire (built-in
  mics), 33 (0x21) = headset-mic. This libpalclient dereferences both
  pal_stream_set_buffer_size configs (null -> SIGSEGV). Note that
  `android-run` uses `env -i`, so pass options as arguments, not environment.
  PipeWire source "Built-in Microphones" (pipe-tunnel, /run/loa-audio/mic.fifo)
  is fed by loa-mic-relay.py, which runs `loa-pal record 0 30` only while
  PipeWire drains the FIFO (4 KiB pipe; stops after 2 s full). Verified: pw-record
  captures the speaker tone (440 Hz 17 -> 3453).

## Power button / sleep (2026-09-25)
- logind: `HandlePowerKey=ignore` (its default would power off). Hyprland binds
  XF86PowerOff -> `loa-power-button` (bindings.lua override).
- **DPMS off/on (and aborted s2idle) crash the SoC natively.** Reproduced twice
  (`crashes/2026-09-25-dpms-reenable.txt`): mi_disp "Panel not ready / failed to
  set esd irq", then on re-enable the ESD check reports PANEL_DEAD,
  mca_adsp_glink write timeouts, KGSL GMU boot fails, `kernel BUG at
  rpmh-rsc.c:1090`, panic, watchdog bite, reboot. The safety net worked:
  download_mode=0 gives a clean reboot straight back to Omarchy.
- s2idle is also blocked while USB/charging is attached (charger_wakelock and
  a600000.ssusb wakeup sources, same as Android).
- Current power key = *safe* screen-off: backlight 0 + touchscreen disabled via
  `hl.device({ name = "nvtcapacitivetouchscreen", enabled = false })`; the
  display pipeline stays on. udev rule makes the backlight writable by group video.
- Open: find how Android sequences panel off/on (SDE power modes LP1/LP2/OFF via
  HWC, mi_disp, display RSC/CESTA votes) before attempting DPMS or suspend again.
- 2026-09-25 later: **backlight sysfs has no effect natively** (the KTZ8866
  register dump never changes, and the user sees no change). The first commit
  after continuous splash always logs "DMS not supported on first frame" /
  "Panel not ready" (Aquamarine picked modes[1] = 144 Hz. Fixed: fall back to the
  kernel-preferred mode, fixed the inverted current-mode memcmp, and added
  AQ_DRM_PREFERRED_ONLY). A commit on the splash CRTC 208 in the same mode is
  rejected with EINVAL, so AQ_DRM_IGNORE_BOOT_CRTC=1 allocates a fresh CRTC
  (284): the display comes up at boot without a restart, but the kernel still
  logs the first-frame DMS error (CRTC change). Whether that error is what
  blocks backlight/DPMS is unproven.
- Found: ldconfig had re-pointed libaquamarine.so.14 to a backup file left in
  /usr/lib (.split-only), so Hyprland ran an old build. Backups now live in
  /root/aq-backups. Never leave extra libfoo.so.* files in /usr/lib.
- Safety: sleep.conf.d AllowSuspend=no (etc.). Power key -> Omarchy system
  menu via loa-power-key.py (evdev), no screen-off for now.
- Android comparison (Magisk): brightness setting -> sysfs panel0-backlight ->
  KTZ8866 registers follow; a direct sysfs write also works on Android. So
  natively the SDE connector never reaches "allow_bl_update" because the first
  bridge enable fails (DSI prepare -22 after continuous splash); brightness
  writes stay parked. Next experiment: one-shot clean splash-off before
  Hyprland (connector CRTC_ID=0, CRTC ACTIVE=0) so its first commit is a full enable.
- Android -> Recovery regression: misc BCB kept "boot-recovery" (written when
  Recovery was entered with Volume Up; left via adb reboot instead of its menu).
  Android's init honours it, our stage 1 doesn't. Cleared the first 864 bytes of
  misc (backup: stock-android/misc-bcb-backup-2k.bin). reboot-to-android works again.

## Display power / brightness: current understanding (2026-09-25, parked)
Source: CodeLinaro display-drivers `display-kernel.lnx.12.13.r1-rel` (src/display-drivers).
- Backlight path: sysfs -> sde_backlight_device_update_status (gates:
  FB_BLANK_UNBLANK, allow_bl_update [set true only in bridge_enable, or by
  writing 0 to /sys/class/drm/sde-conn-2-DSI-1/twm_enable],
  thermal_max_brightness) -> dsi_display_set_backlight, which needs
  **dsi_panel_initialized()**, only true after a *successful* panel enable.
- Natively the first enable after continuous splash always fails:
  dsi_display_prepare "DMS not supported on first frame" (the DSI_MODE_FLAG_DMS
  check runs while is_cont_splash_enabled is set). Tried:
  144 Hz on a new CRTC, 120 Hz on a new CRTC, 144 Hz on the splash CRTC 208
  (all DMS error); 120 Hz on CRTC 208 (EINVAL, even with dsc_mode=1);
  splash-off commit before Hyprland (still DMS); connector dsc_mode=1 on a new
  CRTC (still DMS). Android's first commit (fps 0->120) succeeds, so HWC sets
  something we don't yet (candidates: connector LP=ON, other SDE connector/CRTC
  props, the plane layout / order on CRTC 208).
- Consequences: no brightness control; DPMS off/on crashes (the panel was never
  "enabled", so disable/enable mis-sequences -> ESD PANEL_DEAD, then an RPMh BUG).
- SDE connector has an `LP` property (ON/LP1/LP2/OFF) = Android's doze/off path.
  Use it for screen-off once the first enable succeeds.
- Next step: capture Android HWC's first commit (property set) with DRM debug in
  Magisk Android (echo 0x1e > /sys/module/drm/parameters/debug before
  starting SurfaceFlinger) and replicate it in Aquamarine.
- Current boot config (stable, live at boot): AQ_DRM_PREFERRED_ONLY=1
  AQ_DRM_IGNORE_BOOT_CRTC=1 AQ_DRM_CONNECTOR_PROPS=dsc_mode=1, 120 Hz.
- hyprlock installed (Omarchy locks via its Quickshell lock screen; the lock path has no DPMS). hypridle deliberately NOT installed (its idle DPMS-off hits the crash path). omarchy-brightness-display only DPMS-offs on the explicit "off" argument.

### 2026-09-25 evening: brightness fixed (first-frame DMS solved)

- Debugging: DRM debug needs mask 0x1f (DSI_DEBUG is DRM_UT_CORE) and a
  *privileged* ExecStartPre (`ExecStartPre=+...`); loa-desktop runs as omarchy,
  so an unprivileged hook silently can't write /sys/module/drm/parameters/debug.
- Disassembled the device's msm_drm.ko (Xiaomi build differs from CLO source):
  `_dsi_bridge_mode_validate_and_fixup` ORs DSI_MODE_FLAG_DMS (bit 3) whenever
  the new mode does not FULL_TIMINGS-match the CRTC's *old* mode and
  (`!active_changed || is_cont_splash_enabled`). `dsi_display_prepare` then
  refuses DMS on the first frame -> panel never "initialized" -> backlight
  writes ignored (and, likely, the DPMS crash).
  - Fresh CRTC (AQ_DRM_IGNORE_BOOT_CRTC): old mode is empty -> always DMS.
  - Splash mode (debugfs state before Hyprland): CRTC 208 enable=1 active=1,
    "3200x2136x120vid" 1020143 kHz = exactly our preferred mode.
  - Reusing CRTC 208 failed with "active without enabled" because Aquamarine
    omits MODE_ID when the mode is unchanged (AQ trace confirmed).
- Fix: Aquamarine `AQ_DRM_FORCE_MODE_ID=1` always sends MODE_ID on modeset.
  gpu.conf now: `AQ_DRM_DMA_HEAP=/dev/dma_heap/system AQ_DRM_PREFERRED_ONLY=1
  AQ_DRM_FORCE_MODE_ID=1` (no IGNORE_BOOT_CRTC, no CONNECTOR_PROPS). Result:
  commit on CRTC 208, no DMS error, KTZ8866 reg 0x05 follows
  panel0-backlight (readable via
  /sys/devices/virtual/mi_display/disp_feature/disp-DSI-0/ktz8866_reg_rw).
  User confirmed dimming works.
- Note: `Environment=VAR=` (empty) still counts as set for getenv() checks in
  our patch; remove the variable instead.
- Patch regenerated: patches/aquamarine-0001-shuntian-split-primary-dmaheap-initial-mode.patch.
  Previous lib backed up in /root/aq-backups/*.before-forcemodeid.

### 2026-09-25: notification pile-up

- 96 stacked notifications: Omarchy first-run tips (Learn Keybindings, Update
  System, Setup Wi-Fi) re-sent every login, plus "Screensaver only runs in
  Alacritty, Foot, Ghostty, or Kitty" on every idle timeout.
- Cleared with `omarchy-shell notifications dismissAll` / `clear` as omarchy
  (needs OMARCHY_PATH=/usr/share/omarchy, else it silently no-ops with -q).
- Cause 1: omarchy-provision-first-run fails at enable-user-units.sh because
  the Omarchy user units (bt-agent, sleep-lock, crash-watch, fcitx5, ...) were
  never installed to /usr/lib/systemd/user and their binaries are not in
  /usr/bin (partial Omarchy install; no bluez/fcitx5). Marked done with
  `omarchy-done mark first-run-user`. Revisit when Bluetooth lands:
  `omarchy-provision-first-run --force`.
- Cause 2: xdg-terminal-exec (in omarchy-base.packages) was missing. Installed
  it with pacman; it resolves to foot.desktop.

### 2026-09-25: DPMS works, power key = screen off/on

- With the first-frame fix in place, Hyprland DPMS off/on no longer crashes:
  1 x 6 s + 5 x 3 s cycles, no PANEL_DEAD / "Panel not ready" / kernel BUG;
  ESD irq disables/re-enables cleanly. Each wake logs a harmless WARN
  "llcc: Slice 16 is still active" (llcc_slice_putd from _disp_cache_state_set).
- loa-power-key.py rewritten: short press toggles DPMS (touchscreen
  `nvtcapacitivetouchscreen-1` disabled while off), hold >= 0.7 s opens the
  Omarchy system menu (waking the screen first). User confirmed all three.
- Pitfall: Omarchy sets `key_press_enables_dpms = true`, so Hyprland woke DPMS
  on the power key press itself and the release handler read "on" and blanked
  again (screen stuck off). Fix: EVIOCGRAB pmic_pwrkey so only the daemon sees
  it; while off, poll `hyprctl monitors -j` each second and re-enable touch if
  another input woke the screen.
- Suspend is still disabled (sleep.conf.d); not attempted yet.

### 2026-09-25: idle behaviour (user decision: no lock, screen off at 5 min)

- Omarchy idle = screensaver 150 s, lock 300 s (quickshell idle service). The
  lock can never be unlocked here: PAM service `omarchy-lock-password` is not
  installed in /etc/pam.d, the omarchy account password is `!`, and there is
  no on-screen keyboard. Lock pushed out: ~/.config/omarchy/shell.json
  idle.lock = 2000000 (0 would mean "lock immediately"; must stay < 2^31 ms).
  Backup: /root/shell.json.before-idle.
- Screen off at 300 s via hypridle (installed with pacman), config
  rootfs-overlay/home/omarchy/.config/hypr/hypridle.conf, started from
  autostart.lua (now also in the overlay).
- Screensaver: omarchy-screensaver needs `ttfx` (omarchy-base.packages, from
  Omarchy's own repo; source github.com/omacom/ttfx, Rust, no arm64 binary).
  Without it the screensaver terminal shows "command not found". Disabled via
  toggle ~/.local/state/omarchy/toggles/screensaver-off until ttfx is built.
- Touch cannot wake the screen: while DPMS is off the Xiaomi panel notifier
  suspends the touch IC (0 bytes on event6 during 15 s of tapping; gesture
  type 0). Wake = power key (or keyboard cover). Tap-to-wake would need the
  xiaomi_touch gesture mode (double-tap) enabled, as Android does. Open item.
- Pitfall: `pkill -f`/`pgrep -f` over tssh match the ssh command line itself.

### 2026-09-25: headset jack deferred

- No wired headphones at hand. Jack = event16 "alor-mtp-snd-card Headset Jack"
  (EVIOCGSW all zero with nothing plugged). Plan: relay picks the route per
  stream (jack switch set -> `loa-pal play <id>`, else agmplay speakers) and
  ends the stream on jack change. Vendor PAL input ids are upstream+3
  (headset mic 33); the output ids (upstream WIRED_HEADSET 4 / HEADPHONE 5)
  still need a listening test.

### 2026-09-26: Bluetooth controller works (stock HAL + PTY bridge)

- Chip: WCN7750 BT side, SoC "orn" (persist.vendor.qcom.bluetooth.soc=orne),
  UART /dev/ttyHS0, power via /dev/btpower. Upstream btqca doesn't know it and
  GKI has no hci_vhci, so: stock HAL does power + firmware, a bridge feeds BlueZ.
- Chain: loa-thermalhal (android.hardware.thermal-service.qti; the BT HAL
  blocks forever in waitForService(IThermal) without it) -> loa-bthal
  (android.hardware.bluetooth@aidl-service-qti) -> loa-bluetooth
  (/usr/lib/loa/bt-bridge.sh: `loa-bthci` in the island + `btattach -P h4`)
  -> hci0 -> bluetoothd (pulled in via Wants=; bluetooth.target is never
  triggered by udev here). Adapter auto-powers (AutoEnable default).
- tools/loa-bthci/loa-bthci.cpp (NDK r28c, linked against the device's
  libbinder_ndk.so; LLNDK functions declared by hand): IBluetoothHci client
  (stable AIDL V1, methods alphabetical: close=1, initialize=2, sendAclData=3,
  sendHciCommand=4, sendIsoData=5, sendScoData=6; callbacks acl=1, event=2,
  initializationComplete=3, iso=4, sco=5; callback binder needs
  AIBinder_markVintfStability). After init it opens a PTY (keeps the slave
  open: a master with no slave reads EIO) and relays H4 frames.
- Island additions (android-parts.sh / android-chroot.sh): bluetooth_b (vfat)
  -> /vendor/bt_firmware; persist mounted **ro,noload** -> /mnt/vendor/persist
  (real BD address from bluetooth/.bt_nv.bin: XX:XX:XX:XX:CE:B9); /dev/pts
  bound into the island (posix_openpt); /data/vendor/{bluetooth,bsplog/bt/
  ssr_dump,mac_addr}. Without a writable /data/vendor/bluetooth the HAL fails
  "Failed to Store Calibration data", SSRs and kills itself.
- Verified: firmware download + SoC calibration OK, hci0 = BT 6.0 (version 14,
  Qualcomm), scan finds 15+ devices, survives reboot unattended.
- Not verified (no device at hand): pairing, A2DP audio (PipeWire bluez5 plugin
  and Omarchy's a2dp auto-connect rule are present).
- Pitfall: killing a HAL instance releases btpower and powers the chip off,
  even under a newer HAL; always stop all BT processes before a rerun.

### 2026-09-26: Bluetooth audio works (user-verified with Bluetooth headphones, clean tone)

- "a2dp-sink profile connect failed: Protocol not available": WirePlumber never
  registered A2DP endpoints. Its BlueZ monitor waits for the logind seat to be
  "active"; our session (loa-desktop + seatd) has no seat -> "online" forever.
  Fix: wireplumber.conf.d/52-loa-bluez-no-seat.conf, profile feature
  `monitor.bluez.seat-monitoring = disabled` (0.5.17: a *profile feature*, not
  a wireplumber.settings key; the settings form is silently ignored).
- Then "Connection refused (111)": the UI showed paired but BlueZ had
  Paired/Bonded: no (no default agent -> no link key). Omarchy's bt-agent unit
  was never installed (bluez-tools missing, first-run failure). Installed
  bluez-tools; /etc/systemd/user/bt-agent.service -> Omarchy's unit, enabled via
  ~omarchy/.config/systemd/user/default.target.wants (graphical-session.target
  is never reached here); drop-in bt-agent.service.d/loa.conf waits for
  bluetoothd instead of ExecCondition skipping. Re-paired with an agent ->
  Bonded: yes, bluez_output sink, 440 Hz tone heard clearly.

### 2026-09-26: Xiaomi pogo keyboard + touchpad work (user-verified, survives reboot + reattach)

- Path: keyboard MCU -> pogo -> ADSP sensor PD firmware -> QMI -> kernel
  xiaomi_keyboard_driver_shuntian -> HID input devices (Xiaomi Keyboard/Touch/
  Mouse/Consumer) + /dev/nanodev0 chardev. Status: /sys/devices/virtual/
  keyboard/keypad/version (Connected/Power/POGOPIN).
- Natively it stayed Connected=[0]: (1) the ADSP sensor PD needs its userspace
  `sscrpcd sensorspd adsp`; (2) Android's MiuiKeyboardManager (system_server)
  wakes the keyboard by writing packets to /dev/nanodev0 through the
  keyboardnanoapp HAL. Found by booting stock Android and reading logcat
  (stock-android/logcat-keyboard-boot.txt; unique packets in
  stock-android/keyboard-write-cmds.txt). Needed packets:
    32004E318038A10101DA...  MCU status request
    32004E308018010100 18... enable keyboard (0x18)
    32004E308038010100 38... enable touchpad (0x38)
  Written directly to /dev/nanodev0 (30 bytes each) -> A2 packet ->
  Connected=[1] Power=[1] POGOPIN=[OK], keyboard fw 24, touchpad fw 201.
  vndservicemanager / the nanoapp HAL / chre are NOT needed.
- Units: loa-sscrpcd.service, loa-keyboard.service (loa-keyboard.py re-sends
  the enable packets every 5 s while not connected: boot and reattach).
- Touchpad moved nothing although events arrived: pressure range 0..65535 vs
  libinput's absolute palm threshold 130 -> every finger a palm. Fix:
  /etc/libinput/local-overrides.quirks disables ABS_(MT_)PRESSURE for
  "Xiaomi Touch" (Hyprland must restart to reload quirks).
- Super sends KEY_LEFTMETA, Enter KEY_ENTER (correct). "Super+Return does
  nothing / apps don't launch" was unrelated: /usr/local/bin/uwsm-app (PRoot
  leftover) execs /usr/bin/uwsm-app, which was never installed (exit 127).
  Installed `uwsm` (in omarchy-base.packages); the user manager already has
  the Wayland/GPU environment via Omarchy's autostart import-environment.

### 2026-09-26: random black screen (cursor only) for a few seconds -- fixed

- Symptom = the Omarchy shell (quickshell; draws wallpaper + bar) dying and
  being relaunched by omarchy-launch-shell ("exited with status 137"), 13x in
  ~10 min. No crash report, no OOM, nothing logged before each kill.
- ftrace `signal/signal_generate` (filter sig==9) + `stacktrace` trigger:
  SIGKILL generated in quickshell's own thread "sq0", code=128, stack
  posix_cpu_timers_work -> send_signal = RLIMIT_RTTIME exceeded.
- /proc/<quickshell>/limits: "Max realtime timeout 0 0 us" (wireplumber too),
  while pipewire, Hyprland and the launcher are unlimited -> set by
  libpipewire-module-rt in PipeWire *clients*: RTKit is unusable here
  (PIDFD_GET_PID_NAMESPACE unsupported) and the fallback leaves RTTIME = 0.
  Xiaomi's kernel scheduler boosts busy UI/render threads to RT on its own
  (trace: stop_mi_rt_active_migration ... quickshell:sq0), so the first boost
  -> instant SIGKILL.
- Fix: ~/.config/pipewire/client.conf.d/60-loa-no-client-rt.conf
  (context.properties module.rt = false). quickshell now "unlimited"; no kill
  in the following 5+ minutes of use. WirePlumber still gets 0 (its own config
  loads module-rt unconditionally) but is not affected so far.
- Also: xiaomi_keyboard debug_level 5 -> 0 (loa-keyboard.py) to stop ~8 kernel
  log lines per touchpad packet.

### 2026-09-26: keyboard cover close/open = screen off/on (user-verified)

- The cover magnet trips the tablet's own hall sensor, not the keyboard:
  xiaomi-hall (event15) lid_hall -> EV_SW SW_LID, 1 = closed, 0 = open
  (irq 427 close / 426 open). Standard Linux lid switch; logind saw it and
  defaulted to suspend (refused by sleep.conf.d).
- loa-power-key.py now also watches xiaomi-hall: close -> set_screen(False)
  (DPMS off + touch disabled), open -> set_screen(True). Initial state via
  EVIOCGSW. While closed, if something other than the power key wakes the
  screen (key_press_enables_dpms + keys pressed through the cover) it is
  blanked again on the next 1 s poll; the power key still wakes it on purpose.
- logind.conf.d/50-loa-power-key.conf: HandleLidSwitch{,ExternalPower,Docked}=ignore
  (applied with `systemctl reload systemd-logind`, no session restart).
- Not handled yet: keyboard folded behind the tablet (Android computes a hinge
  "Angle" from the keyboard's 0x22 accel packets + the tablet's gravity sensor;
  xiaomi-hall's table_hall = code 1 never fired in tests).

### 2026-09-26: Chromium wouldn't launch (exit 21) -- fixed

- omarchy-browser-*.service exit 21 = Chromium RESULT_CODE_PROFILE_IN_USE.
  ~/.config/chromium/SingletonLock -> "localhost-7149" (left by the PRoot era,
  Sep 24), while the machine's name is now transient and changes with the
  network ("archlinux" at boot, "bogon" from DHCP/DNS; no /etc/hostname).
  Chromium treats a lock from another host as "profile in use elsewhere".
- Fix: removed the stale Singleton{Lock,Cookie,Socket}; static hostname
  `shuntian` (/etc/hostname, in the overlay) so the name no longer drifts and
  future locks stay valid. Launch + relaunch verified by the user.

### 2026-09-26: udiskie, Chromium sandbox back on, Chromium on native Wayland

- "Command not found: udiskie": Omarchy autostart runs it; package (in
  omarchy-base.packages) was never installed. Installed.
- Chromium "unsupported command-line flag --disable-gpu-sandbox":
  ~/.config/chromium-flags.conf was the PRoot version. Natively the setuid
  /usr/lib/chromium/chrome-sandbox works without user namespaces (headless
  test OK; renderers Seccomp: 2), so --no-sandbox and --disable-gpu-sandbox
  were removed; GPU process still holds /dev/kgsl-3d0.
- Native Wayland: Chromium 153 turns Vulkan / Skia-Vulkan on by default and
  logs "'--ozone-platform=wayland' is not compatible with Vulkan" (harmless
  once GL is used). Working set: --ozone-platform=wayland --use-gl=angle
  --use-angle=gl --disable-features=Vulkan,VulkanFromANGLE,DefaultANGLEVulkan,
  SkiaGraphite. GPU process maps Mesa libEGL_mesa/libgallium (kgsl) + dri_gbm,
  holds /dev/kgsl-3d0; Hyprland shows xwayland: 0. User: "about the same" as
  X11, works with their profile. File in overlay; X11 version backed up at
  /root/chromium-flags.conf.x11 on the tablet.
- Pitfall (again): pgrep -f over tssh matches the ssh shell's own command line;
  use pidof + /proc/<pid>/cmdline instead.

### 2026-09-26: sudo for the omarchy user

- omarchy had no password (`!`), wasn't in wheel, and sudoers only allowed
  root. Added omarchy to wheel and /etc/sudoers.d/10-loa-wheel
  (`%wheel ALL=(ALL:ALL) ALL`, 0440 root, visudo-checked). apply-overlay.sh
  now enforces mode/owner, runs visudo -c and `usermod -aG wheel omarchy`.
- The password itself is set by the user (not stored anywhere in the
  workspace): `tools/tssh -t passwd omarchy`. Autologin (loa-desktop
  User=omarchy + PAMName=login) does not depend on it.
- Password set by the user. First `sudo` still said "may not run sudo": the
  running session (Hyprland and every terminal) kept its pre-usermod group list.
  Fix = new session: `systemctl restart loa-desktop` (Omarchy's Logout would end
  Hyprland cleanly and loa-desktop, Restart=on-failure, would not come back).

### 2026-09-27: Chinese input (fcitx5 Pinyin) -- user-verified in Chromium + terminal

- Packages: fcitx5 fcitx5-gtk fcitx5-qt fcitx5-configtool fcitx5-chinese-addons
  fcitx5-pinyin-zhwiki (all new; pulls qt6-webengine, KF6 bits; no upgrades).
- Mirrors: mirror.archlinuxarm.org ran at ~29 KB/s from here; TUNA/USTC
  archlinuxarm ~42 MB/s. /etc/pacman.d/mirrorlist now lists
  mirrors.tuna.tsinghua.edu.cn and mirrors.ustc.edu.cn first (backup
  /root/mirrorlist.before-china). Their packages were newer than the Sep 24
  sync db -> 404s; did `pacman -Sy` then checked with --print that the install
  only added new packages (qt6-base equal) before installing. The system is
  now 6 packages behind the db: do NOT install further packages without a
  deliberate `pacman -Syu` review (aquamarine is IgnorePkg/patched; a Hyprland
  bump would need a matching Aquamarine rebuild). A killed pacman left a stale
  /var/lib/pacman/db.lck (removed only after checking no pacman runs).
- Environment: loa-desktop.service.d/im.conf (XMODIFIERS=@im=fcitx,
  QT_IM_MODULE=fcitx, SDL_IM_MODULE=fcitx; Hyprland's autostart imports them
  into the user manager).
- Startup: Omarchy's omarchy-fcitx5.service linked into /etc/systemd/user and
  default.target.wants; drop-in waits for WAYLAND_DISPLAY in the user manager
  instead of Omarchy's ConditionEnvironment (which would skip it at boot).
- ~/.config/fcitx5/profile: keyboard-us + pinyin; toggle Ctrl+Space.
- Chromium: --enable-wayland-ime --wayland-text-input-version=3.

### 2026-09-27: full system upgrade (pacman -Syu) -- clean

- Pending were 6: systemd/systemd-libs/systemd-sysvcompat 261.3 -> 262,
  hyprtoolkit 0.5.4 -> 0.6.0, hyprland-guiutils rebuild, libdwarf. Hyprland and
  Aquamarine (IgnorePkg) unchanged.
- Reviewed systemd 262 README/NEWS: kernel 6.12 far above baseline (5.10);
  incompatible changes irrelevant here except Type=notify-reload now strict
  (non-systemd users: sshd, polkit, dbus-broker -- current Arch builds).
- Rollback: the package cache is wiped by a post-transaction hook
  (package-cleanup.hook) and ALARM has no archive, so a file-level rollback
  was made: /root/rollback/pre-syu-2026-09-27.tar (all files owned by the six
  old packages + their /var/lib/pacman/local entries; only man pages absent),
  versions in /root/rollback/versions.txt. Restore = `tar -xpf ... -C /`
  after removing the newer local/ db entries.
- Result: systemd 262 as PID 1, cold boot to `running`, no failed units; user
  verified touch, audio, keyboard/touchpad, Pinyin, Chromium. System is fully
  up to date against the TUNA/USTC mirrors.
- Procedure for future updates: pacman -Sy; pacman -Qu; check anything
  touching hyprland (needs a matching Aquamarine rebuild with our patch),
  systemd, mesa/glvnd, pipewire/wireplumber, NetworkManager, bluez;
  make a rollback tar; pacman -Su; reboot test.

### 2026-09-27: app launcher entries (no icons / not launching) -- fixed

- Omarchy is not a pacman package here: the PRoot builder copied it to
  /usr/share/omarchy and linked its commands into /usr/local/bin (441 links,
  fine). What a real package install provides but this rootfs lacked:
  - Icons: entries use names (Icon=basecamp, disk-usage, omarchy-discord...)
    that a real package installs into /usr/share/icons/hicolor. New
    /usr/lib/loa/install-omarchy-icons.sh copies
    /usr/share/omarchy/applications/icons/*.png (512x512) to
    hicolor/512x512/apps under Omarchy's own safe_icon_name() names and
    refreshes the icon cache (apply-overlay.sh runs it).
  - Programs: 98 of 147 omarchy-base.packages were missing (e.g. dua-cli for
    "Disk Usage"). User chose "everything available": 65 packages (215 with
    deps, 427 MB; list in notes-omarchy-base-installed-2026-09-27.txt)
    installed after a --print check (no upgrades). Excluded on purpose: sddm,
    plymouth, kernel-modules-hook (normal-Arch boot/kernel pieces), ufw (could
    cut the USB link), docker/docker-buildx/docker-compose (user: skip).
    26 more are not in the ALARM repos (Omarchy's own repo / x86-only), e.g.
    nvim, yay, obsidian, localsend, ttfx, omacalc/omacut/omawrite, aether.
- Docker launcher entry hidden (NoDisplay=true in the user's Docker.desktop).
- Basecamp/web apps themselves were fine once uwsm + the Chromium lock fix
  were in; user verified icons + launching (Disk Usage, web apps).
- Tool: /root/audit-apps.py (checks every visible .desktop entry's command and
  icon resolution); scratch copy of the script is not in the repo.

### 2026-09-27: sensors -- working proof of concept, then shelved (user: always uses the keyboard)

- Sensors live on the ADSP sensor PD (needs loa-sscrpcd, already running for
  the keyboard). ssc_sensor_info lists them: lsm6dso accel/gyro, qmc6308 mag,
  stk3bcx ambient light/proximity/RGB/CCT, sip1328 back ALS/flicker, fused
  device_orient, gravity, rotation vectors, etc. (/root/ssc_sensor_info.txt).
- see_workhorse/USTA can't stream: retail firmware ships only 1 of the SEE
  .proto files USTA loads at runtime (and no descriptor.proto); the binaries
  use protobuf-lite, so nothing to extract.
- Working route: QMI service SSC (400) over QRTR via libqmi's Qmi.ClientSsc
  (pacman libqmi + libqrtr-glib, Python GI), payloads hand-encoded from the
  libssc project's reverse-engineered protos (src/libssc, codeberg
  DylanVanAssche/libssc, GPLv3; used as reference only).
  rootfs-overlay/usr/lib/loa/loa_ssc.py: SUID lookup (uid 0xABAB.., msg 512 ->
  768), enable 513 (continuous, float sample_rate) / 514 (on-change), events
  1025 with repeated float field 1. Verified: accel ~(9.46,-0.05,2.96) m/s^2
  in normal keyboard landscape, ambient_light 46 lux (+ raw channels),
  device_orient on-change [1, 1, ...]. `python3 /usr/lib/loa/loa_ssc.py
  [types...]` prints 10 s of samples.
- Not done: mapping orientations to Hyprland monitor/touch transforms
  (auto-rotate), auto-brightness daemon. Shelved at the user's request.
- Note: "AHAL init took more than 30 S, rebooting..." is logged by the stock
  audio HAL at ~54 s on every boot; harmless (its reboot request goes to
  Android init, which doesn't exist; loa-audiohal NRestarts=0, audio fine).

### 2026-09-27: screen auto-brightness (works) + keyboard backlight (blocked)

- loa-autobrightness.service / usr/lib/loa/loa-autobrightness.py: SSC
  ambient_light (on-change) -> log-lux curve -> panel0-backlight (0..4095),
  EMA smoothing + stepped fade every 100 ms, skips while
  /sys/class/drm/card0-DSI-1/dpms != On. Manual changes (brightness keys,
  brightnessctl) are learned as a bias on the curve (/var/lib/loa/
  autobrightness.json). Pause: touch /run/loa-autobrightness-off. User: works well.
- Keyboard packet format (from captures): 32 00 | 4E/4F | 30 (hub) or 31
  (keyboard) | 80 | 18/38 | CMD | LEN | DATA | CHK, CHK = sum(bytes[2..]) & 0xFF.
- Backlight = CMD 0x23, one byte level 0..100 (Android: "set back light: N",
  logcat stock-android/logcat-keyboard-backlight.txt). 0x2E is NOT backlight.
- Natively nothing reacts: 0x23 at any level, alone or after replaying
  Android's full connect order (A1, hub 18, 21 01 01, 52 <BT MAC>, 2E FC/F3,
  31 "MIAUTH", 25 01 01, hub 38). Reading /dev/nanodev0 yields only the
  keyboard's 0x22 accel packets; no reply to any command (Android gets e.g.
  24 31 38 80 31 ... in reply to MIAUTH). So keyboard->host works,
  host->keyboard gets no answer. Unknown gate; also Xiaomi auth
  (midevauthd, QSEE TrustZone TA via libQSEEComAPI, driven by the Java
  framework's MiuiKeyboardManager/MiDevAuthService) may be required.
  Next steps if resumed: disassemble xiaomi_keyboard_driver_shuntian
  chardev_fops_write / ipc path; check what Android's nanoapp HAL does besides
  relaying (it holds nanodev0 open and reads).

### 2026-09-27: suspend -- findings so far (loa-sleepd written, NOT enabled yet)

- Kernel offers mem (s2idle / deep). Use **s2idle**: with deep, resume fails to
  restore PMIC registers (spmi-temp-alarm "invalid TEMP_DAC trip / init
  failed" on every PMIC, pm8550 GPIO restore write failed), the panel often
  stayed dark after the power key, and three ADC thermistor channels
  (pm8550 conn_therm2 + ScreenPmic_therm, pm7550ba charger_therm0) came back
  ~+26 C -> connector anti-burn tripped (cuts VBUS + data, stops charging, USB
  role flips to HOST; a latched hw anti-burn needed a full power-off). s2idle
  reaches CX collapse + DDR self-refresh (qcom_stats cxsd/ddr durations), no
  PMIC errors; ADC rebind (unbind/bind qcom-spmi-adc5-gen3) repairs offsets
  if they ever appear (kept as a safety net when the 2 conn thermistors
  disagree > 15 C).
- Blockers found with a wakeup_sources before/after diff:
  - Bluetooth: HCI traffic at suspend keeps the BT UART (qup_uart) busy; the
    stock HAL wedges if BlueZ talks to it across suspend -> stop
    bluetooth/loa-bluetooth/loa-bthal before, start after the screen is on.
  - Wi-Fi: without WoWLAN, cfg80211 disconnects inside the suspend path and
    raced the driver -> kernel oops (kworker) during a real suspend. With
    WoWLAN (iw ... disconnect magic-packet) the association survives but the
    firmware wakes every 3-5 s (PATTERN_MATCH_FOUND): the router converts IPv6
    multicast neighbor solicitations (for other hosts) to unicast; Android
    drops them with APF. WCNSS ini gEnableWoW=1 (magic only) makes the WPSS
    firmware crash -> kernel panic (NEVER set it; left commented in the ini).
    -> radio off via `nmcli radio wifi off` before suspend, on with the screen
    (NM persists "off" across reboots: always turn it on at daemon start).
  - SSC sensors must be registered non-wakeup (loa_ssc.py suspend_mode=1).
  - USB gadget: never unbind/rebind it around suspend -- the orphaned usb0
    netdev made a proxy core's netlink dump oops the kernel (nla_put_string).
  - dwc3 refuses suspend while a cable is attached (like Android): only
    suspend on battery.
  - OPEN: with the keyboard cover closed, the folded keyboard's touchpad/keys
    touch the screen glass and stream packets over QMI -> qrtr_ws wakes s2idle
    immediately (10 attempts, 0.038 s asleep). Android presumably disables
    keyboard/touchpad reporting on hall close -> capture needed.
- Also fixed today: udev's 60-persistent-v4l.rules masked (v4l_id opened the
  CAM-ICP subdevice at boot -> cam_icp_subdev_open oops -> panic).
- loa-sleepd.py (rootfs-overlay/usr/lib/loa): screen-off grace 10 s, battery
  only, no audio, /run/loa-nosleep inhibit, radios off/on, s2idle, re-sleep
  after stray wakes, logs fired wakeup sources per cycle. Disabled at boot
  until the cover issue is solved.

### 2026-09-27 (later): keyboard commands need 66-byte writes; suspend enabled

- **Root cause of "the keyboard ignores our commands" (backlight, touchpad
  off, etc.)**: xiaomi_keyboard_driver_shuntian chardev_fops_write copies
  min(count, 66) bytes and calls xiaomi_keyboard_data_write() only if
  count >= 0x42 (66). The logged "write cmd -> [[[...]]]" shows 30 bytes, so
  we wrote 30 -> silently dropped. Pad packets to 66 bytes and everything
  works (backlight 23 01 N verified by the user). The earlier "enable" writes
  never reached the keyboard either: it connects once sscrpcd runs.
- New commands (stock Android cover-close capture, stock-android/
  logcat-cover-close.txt): 21 01 00 = touchpad reporting off (keys stay),
  21 01 01 = on. Android also fades the backlight to 0 on close.
- loa-keyboard.py rewritten: 66-byte packets; touchpad off + backlight off
  while the cover is closed (xiaomi-hall SW_LID) or the screen is off; keyboard
  backlight auto (on while typing below 50 lux, off after 30 s idle; lux from
  loa-autobrightness via /run/loa-lux) and `loa-kbd-backlight auto|on [N]|off`
  (/var/lib/loa/kbd-backlight, world-writable). No uleds in GKI, so no
  /sys/class/leds kbd_backlight for Omarchy's own keyboard-brightness command.
- Cover closed + s2idle: with the touchpad off, 32 s + 152 s asleep in a 276 s
  test (qcom_stats cxsd ~183 s) -- before, qrtr_ws woke it instantly.
- Cover-open wake does NOT work: lid_hall_open/close (irq 426/427) arrive from
  the ADSP over smp2p, and the DSP holds the event while the AP sleeps (it was
  delivered after a later wake). Registering SSC 'oem_hall' in WAKEUP mode
  (loa_ssc.py now supports wakeup=True per request) gave no events and no
  wake -> dropped. Keyboard key presses and the power key wake it.
- loa-sleepd enabled at boot (s2idle, radios off/on, conditional ADC rebind,
  per-cycle "fired" wakeup sources in the journal).

### 2026-09-27: Setup menu opened nothing -- neovim missing

- Omarchy's Setup entries run omarchy-launch-editor, which falls back to
  `nvim` (no ~/.local/state/omarchy/defaults/editor); omarchy-base lists
  "nvim" (Omarchy repo, not in ALARM) so no editor was installed and the
  launcher exited after the notification. Installed Arch `neovim` 0.12.5
  together with 5 pending minor updates (pacman -Syu; nothing touching
  Hyprland/systemd/graphics). Plain Neovim: Omarchy's LazyVim setup comes from
  the omarchy-nvim package (not available for aarch64). User: Setup works.

### 2026-09-27: Omarchy default-agent picker (mise) -- fixed

- Omarchy manages coding agents only through mise (`mise where <agent>` to
  detect, `mise use -g <agent>` to install); mise-bin isn't in ALARM, so
  picking an agent failed ("could not find mise"), and agents installed with
  their own installers were never recognized.
- Installed mise (official GitHub linux-arm64 binary, sha256 checked against
  SHASUMS256.txt and the GitHub digest) to /usr/local/bin/mise, and moved the
  agents to mise so Omarchy stays stock (pacman -Qkk clean).
- Pitfall: mise's registry may resolve "latest" to an older release than a
  self-installed one, and Omarchy calls `mise use -g` without a version; an agent's
  newer on-disk data can be unreadable by the older release. Back up agent state first.
- Desktop PATH (loa-desktop.service.d/path.conf) gains the mise shims --
  Omarchy's env-bootstrap does that for uwsm sessions, which we don't use.
  Terminals get mise from Omarchy's bash init.
- Update agents with `mise up` (Omarchy alias `mup`), not their self-updaters.
### 2026-09-27: Omarchy root moved to a 64 GiB `omarchy` partition (user-approved)

- Why: `ramdump` (17 GiB) was 89% full. It also belongs to the crash-dump
  path. The bootloader passes androidboot.ramdump=enable, and the QTI USB gadget
  HAL can expose the partition as mass storage so a PC can pull dumps. A full dump
  never landed there (the 09-25 Android panic left it all zeros; storage dumps
  need emmc_dload=1 via persist.vendor.sys.rawdump_copy=1), but the Omarchy root
  shouldn't depend on that.
- The user decided that nothing on Android was worth keeping (test device). Backups first:
  - full root tar on the Mac: ~/LoA-backups/omarchy-root-2026-09-27.tar.zst
    (5.8 GB, mode 600, holds secrets, outside the workspace; zstd -t ok,
    221725 entries);
  - GPT: backups-gpt/sda-2026-09-27.sfdisk plus raw primary/backup GPT sectors.
- GPT (LUN0 = sda, 4 KiB sectors, 64-entry table), via sfdisk --force
  --no-reread, then partx -u/-a:
  - new sda34 `omarchy` (Linux fs type): start 8474112, 16777216 sectors
    (64 GiB), right after `ramdump`;
  - sda33 `userdata` keeps its number, type, GUID and name: start 25251328,
    5560827 sectors (21.2 GiB), same end as before.
  - Partitions added by partx have no PARTNAME until reboot, so I guarded by
    start sector.
- Copy: fsfreeze -f / (consistent, journal flushed), then dd of the whole
  sda32 to sda34 (17 GiB, 44 s), then unfreeze, e2fsck -f clean, tune2fs -U
  random, resize2fs to 64 GiB. The old fs was relabelled `omarchy-old` and
  left intact as a rollback.
- Stage 1: ROOT_PARTS="omarchy ramdump", the first that exists and mounts
  wins. Built init_boot-omarchy.img (sha256 b4f0b242...) and dd'd it to
  init_boot_b (sde68) from Omarchy, verified by read-back. The previous image
  is kept as images/init_boot-omarchy-ramdump-root.img (sha256 1574b025...).
  Booted: "root partition omarchy = /dev/sda34", 62.9G, 47.7G free.
- Android: blkdiscard userdata plus zeroed the first 64 MiB of it and of `metadata`
  (sda18). Both are `formattable` in fstab.qcom, so Android should format them on
  its next boot (fallback: `fastboot -w`). Expect Xiaomi/Google account
  activation on setup.
- Rollback:
  - `fastboot flash init_boot_b images/init_boot-omarchy-ramdump-root.img`
    boots the old root on `ramdump` (state as of 11:05);
  - or rename/delete the `omarchy` partition, and the fallback finds `ramdump`.
- Later: once the new root has proven itself, `ramdump` can be zeroed so
  it's a plain dump partition again.
- Unrelated and pre-existing: power-profiles-daemon fails with 217/USER on
  every boot (start-limit-hit), so systemd reports "degraded".

### 2026-09-27: "freezes" = out of memory, not the keyboard log storm

- The symptom: the tablet froze twice (boots ending 11:33 and 12:01) and the user
  had to reboot. A coding agent blamed the xiaomi-keyboard journal storm.
- Log storm, real but harmless:
  - the keyboard + xiaomi_qmi drivers print ~7 INFO lines per touchpad packet:
    30-49K lines/min while typing or touching, ~500/min idle;
  - disassembly shows `debug_level` only gates the touchpad edge filter and
    chardev paths (and sends cmd 0x27 to the MCU). rawdata_show,
    keyboard_ipc_loop, ipc_data_parse and indication_cb always print, so no
    knob can turn them off;
  - journald used 3 s CPU in 34 min, and storms at full rate (11:50-56,
    12:16-24) passed without freezes. The only real cost is disk: the journal
    reached 2.1G.
- Real cause: RAM exhaustion. Both freezes started right after launching
  a heavy Electron app (at 11:21/11:22 and at 11:57:02):
  - 2 s later journald logged "Under memory pressure" every 1-2 s, then silence;
    hyprctl timed out and the log lagged 4.5 min;
  - MemTotal 7.3 GiB, a Qt chat app ~1.8 GiB, no swap and no OOM daemon, so the
    kernel thrashed page cache instead of killing anything.
- Fixes:
  1. zram swap: package zram-generator; /etc/systemd/zram-generator.conf
     (ram/2 = 3.6G, zstd, prio 100); sysctl 99-loa-zram.conf (swappiness
     150, page-cluster 0). The vendor zram.ko/zsmalloc.ko modprobe fine.
  2. OOM killer:
     - systemd-oomd is impossible here: the bootloader cmdline has
       `cgroup_disable=pressure`, so there are no memory.pressure files
       and oomctl monitors nothing. Tried it, then removed it.
     - Instead: package earlyoom, /etc/default/earlyoom. It acts at avail
       < 8% and swap free < 10%, prefers Chromium/Electron, and
       avoids the desktop, python3 (LoA daemons, Android island), HALs
       (comm is truncated to 15 chars: "android.hardwar"), network and
       audio. Use [.] instead of \. (systemd strips backslashes).
  3. journald cap: journald.conf.d/50-loa-size.conf, SystemMaxUse=500M.
- apply-overlay.sh enables earlyoom. The two packages must be installed first.

### 2026-09-27: golden image built (repo tools/make-image.sh --clean)

- images/omarchy-clean-20260927.img.zst: 3.5 GiB compressed, 17 GiB raw ext4,
  10.5 GiB used, sha256 06f29801... Staged on this tablet's `ramdump`, so the
  pre-move rollback copy (`omarchy-old`) is gone. `ramdump` now holds the
  golden image (label omarchy); stage 1 still prefers `omarchy`.
- Audit of the staged fs: no NM/Bluetooth/proxy/agent/browser data, /root
  only has .ssh/authorized_keys, omarchy password locked (!), empty
  machine-id, no wlan_mac.bin, boot counter 0.

### 2026-09-27: second tablet (12 GB) installed by a Haiku sub-agent from the runbook

- Steps 2-5 went through: product shuntian, unlocked, slot b, OS4.0.5.0.XFPCNXM;
  install.sh flashed ramdump + init_boot_b; personalize.sh gave it its own
  Wi-Fi MAC (XXXXXXXXF371), machine-id and SSH keys; MemTotal 11.2 GiB.
- Bug found: the rootfs never had the archlinuxarm-keyring package, so
  personalize.sh (rm -rf gnupg; populate archlinuxarm) left pacman with no
  trusted keys. Repaired on the new tablet: archlinuxarm-keyring
  20240419-2 fetched on the Mac from TUNA and USTC (identical sha256
  3cb36869...), keyrings populated, package installed with pacman -U (184 keys).
  personalize.sh now populates all installed keyrings and refuses to reset
  the keyring if archlinuxarm.gpg is missing.
- Auto mode blocked the sub-agent from running repartition --apply; the owner
  then approved it: tools/repartition.sh 192 --apply (256 GB model: userdata
  212.4 -> 20.4 GiB). Copy 25 s, reboot: "root partition omarchy =
  /dev/sda34", 188.8G, 169G free.
- Bug found: zram never started at boot. On this port PID 1 gets no udev device
  events: device units are only "tentative" (from mounts/swaps), so
  zram-generator's dev-zram0.swap waited forever (udevadm trigger didn't help).
  Replaced by loa-zram.service + usr/lib/loa/zram-setup.sh (modprobe, zstd,
  RAM/2, mkswap, swapon -p 100) and masked the generator
  (/etc/systemd/system-generators/zram-generator -> /dev/null). Reboot-tested
  on the new tablet: 5.6G zram at boot. The first tablet needs
  tools/apply-overlay.sh (connect it alone).
- Same root cause, not fixed yet: serial-getty@ttyGS0 (USB serial fallback
  console) waits forever for dev-ttyGS0.device.
- Two more golden-image bugs, reported by the owner on the new tablet (apps failing to
  create their lock/log dirs, terminal "create_dir_all" errors): make-image's whitelist
  copy (tar -T) created ~/.config, ~/.local, ~/.local/share, ~/.local/state
  (+ .config/git, .config/mise) as root; and an over-broad /var/lib exclude dropped a
  system service's binary (203/EXEC restart loop). Fixed on the tablet (chown,
  reinstall) and in make-image.sh.
- Wi-Fi on the new tablet asked for the admin password on every scan/connect:
  the loa-desktop session is active and local but seatless, so polkit's
  allow_active defaults never apply (nmcli general permissions: auth/no). The first
  tablet never showed it because its Wi-Fi was set up as root. New overlay rule
  polkit-1/rules.d/50-loa-networkmanager.rules grants omarchy all
  org.freedesktop.NetworkManager.* actions; all permissions now "yes".
  Other polkit-guarded desktop actions (udisks mounts etc.) may need the same.
- Same seatless-session cause: the Omarchy menu's reboot asked for the admin password
  (reboot-multiple-sessions whenever SSH sessions are open). 50-loa-suspend.rules
  now also allows reboot/power-off (+ -multiple-sessions) for omarchy;
  pkcheck against Hyprland's pid: all yes.
- First tablet brought up to date (tools/apply-overlay.sh from the repo): NM +
  power polkit rules (pkcheck yes), zram-generator masked + loa-zram enabled
  (the running zram swap is kept), archlinuxarm-keyring installed with pacman -S
  (single package, 184 keys). It's now ready for a fresh
  `make-image.sh --clean --apply`.
- Golden image rebuilt from the updated first tablet (sha256 858e0f99..., 3.6 GiB
  compressed). Audit: 0 root-owned files in the home, archlinuxarm-keyring installed, zram-generator masked, all three polkit
  rules, no personal data, password locked, empty machine-id, no wlan_mac.bin.

### 2026-09-27: root cause of "systemd sees no devices": PID 1's udev monitor was off

- Symptom: device units only "tentative" (from mounts), jobs waiting on devices
  hang (zram via zram-generator, serial-getty@ttyGS0), hot-added devices never
  appear, while `udevadm monitor --udev` receives everything. A daemon-reload
  re-enumerates the udev db, which hid the problem on the first tablet (298
  device units after the oomd experiment's reloads).
- /proc/net/netlink: PID 1's NETLINK_KOBJECT_UEVENT socket had Groups 00000000.
  sd-device-monitor disables the udev group when, at PID 1 startup,
  /run/udev/control doesn't exist AND /dev isn't a devtmpfs (container
  heuristic). Our /dev is tmpfs + mdev (no devtmpfs in GKI) and udevd starts
  later, so it was always off.
- Proof: `systemctl daemon-reexec` (control exists now) -> Groups 00000002, and a
  hot-added zram1 appears as dev-zram1.device immediately.
- Fix: stage 1 creates /run/udev/io.systemd.Udev (empty file) + control symlink
  before switch_root (systemd-udevd-varlink.socket unlinks the stale file on bind;
  same symlink target). init_boot-omarchy.img sha256 889c9579...; previous one
  kept as images/init_boot-omarchy-b4f0b242.img. Flashed to the first tablet's
  init_boot_b (verified by read-back). Reboot test: PID 1 uevent socket Groups
  00000002 from boot, 298 device units without any reload, serial-getty@ttyGS0,
  loa-zram, power-profiles-daemon all active. Newly device-triggered:
  systemd-rfkill (radios stay unblocked). One-off "degraded" after this boot with
  NFailedUnits=0 and no failure in the journal; reset-failed -> running.
- Serial console verified after the reexec: root shell on /dev/ttyGS0
  (Mac: /dev/cu.usbmodemLOA_RAM_PROBE1).
- power-profiles-daemon: 217/USER = PrivateUsers (no user namespaces), drop-in
  PrivateUsers=no like upower/uuidd; now active (balanced / power-saver,
  placeholder driver), and systemctl is-system-running = running.
- Second tablet: new stage 1 (889c9579...) flashed to init_boot_b + overlay applied.
  First reboot showed zram missing: `loa-zram` had After=local-fs.target, and
  tmp.mount is After=swap.target, which loa-zram is Before -> ordering cycle;
  systemd deleted loa-zram's job (it had come up on earlier boots only because
  the cycle was broken elsewhere). Now After=loa-mdev.service only. Reboot: no
  cycle, 5.6G zram, is-system-running = running. The earlier one-off
  "degraded" on the first tablet was very likely the same cycle; the first tablet
  needs this fix too (apply-overlay).
- Golden image rebuilt again (17:14, sha256 cdfded49..., UUID 4375f44d...) with the
  zram/ppd fixes; its ext4 UUID matches the first tablet's ramdump. make-image.sh
  now carries the staged UUID into the stream step and refuses to stream if the
  tablet on the USB link changed (the first attempt hit the owner's tablet swap
  at its initial check; tested with a wrong UUID: refused, 0 bytes).

### 2026-09-27: slow charging = no batterysecret (battery auth) -> fixed

- Symptom: charging "ridiculously slow". On the Mac port: 4.9 V x 1.1 A in, battery
  0.92 A. xm_power/charger/charge_interface showed ichg_limit "batt_auth 2000" and
  iin_limit "volt_limit 1500"; fuelgauge/strategy_fg/authentic = 0,
  quick_charge_type 0, pd_verified 0.
- Android starts /vendor/bin/batterysecret on sys.boot_completed (battery digest via
  fuelgauge/strategy_fg, Xiaomi PD adapter auth via typec/strategy_pd_auth). Runs fine
  in the island: authentic -> 1, ichg cap -> volt_thermal_limit 3000.
  New unit loa-batterysecret.service (android-run, Restart=always), enabled by
  apply-overlay.sh.
- Test with the owner's Xiaomi charger (logger /var/log/loa-charge-test.log every 5 s):
  PD_PPS, adapter=true, apdo_max 55; charge pumps at ~9.0-9.15 V (cp_ibus ~2.05 A on
  the master), battery -7.84 A at 4.3 V (~34 W), SoC 64 -> 75 % in 8 min, 25.8 -> 30.9 C.
  pd_verified stays 0 (adapter handshake not completed; probably why it stays below
  the 55 W offered). The Mac port is 5 V only: ~5 W max there regardless.

### 2026-09-27: Xiaomi adapter authentication (pd_verified) -- investigated, not solved

- Charging at ~34 W with the owner's Xiaomi 55 W adapter (apdo_max 55); pd_verified stays 0.
- Flow (strace of batterysecret + MCA logs at charge_log log_level 5 /
  console_log_level 5, which make the __mca_log_info lines visible):
  PD_PPS -> "verify_pd_digest start, type 11" -> verify_process 1 -> current_state
  SNK_Ready -> write "dfp" to strategy_pd_auth/data_role. mca_pd_auth turns that
  into protocol_class_pd_request_vdm_cmd(port, cmd 200, data 2), i.e. an ADSP
  request for a data-role swap to DFP. batterysecret then polls data_role
  (ADSP glink prop 0x2100d) every 100 ms: it stays 1 (UFP) until unplug -> "pd-auth: 0".
  The ADSP accepts the request but never swaps; no error anywhere.
- Tried and failed: (1) `echo host > /sys/class/typec/port0/data_role` -> EOPNOTSUPP
  (ucsi-glink port isn't DRP: no port_type attribute), (2) releasing the dwc3
  forced "peripheral" mode (mode=none) while the adapter is connected: no swap
  either; (3) feeding ro.product.name/persist.vendor.region.charger to
  charger_common/property as init.batterysecret.rc does (only sets is_eu_model 0; kept
  in loa-batterysecret ExecStartPre).
- Open: whether stock Android verifies this adapter at all (compare on Android),
  and what makes the ADSP perform the DR swap there. Also seen: mca_thermal
  "strategy_fail_work" (mi_thermald absent).

## 2026-09-27: recap of the two-day push (owner-requested)

### Done
- Base: autoboot into native Omarchy via our stage 1 on the stock GKI kernel (Android
  still reachable: Volume Up / reboot-to-android). Root moved from ramdump (17 GiB) to
  its own `omarchy` partition (first tablet 64 GiB, second 192 GiB).
- Stability: OOM freezes -> zram + earlyoom (+ journal cap); PID 1 had no udev
  events (no devtmpfs) -> stage 1 pre-creates /run/udev/control (fixed the serial
  console, zram, device units); power-profiles-daemon (PrivateUsers=no).
- Hardware working: display 3200x2136@120, brightness + auto-brightness, DPMS; touch;
  keyboard cover (keys, touchpad, backlight, close = screen off); power key; speakers,
  mics; Bluetooth + A2DP; Wi-Fi; s2idle suspend; fast charging ~34 W (batterysecret).
- Desktop: Chromium native Wayland, fcitx5 Pinyin, sudo, launcher icons + 65 missing
  base packages, Setup editor (neovim), agents via mise, polkit rules
  for Wi-Fi and reboot (seatless session).
- Reproducibility: this repo, golden image (audited twice), second
  tablet installed by a Haiku sub-agent from the runbook (found real bugs, all fixed).

### What worked as a method
- Capture stock Android behaviour first and replay it (keyboard packets, cover-close,
  batterysecret, init.rc actions); run stock vendor daemons unmodified in the island.
- Measure before theorising: ftrace (quickshell SIGKILL = RLIMIT_RTTIME), strace
  (batterysecret handshake), /proc/net/netlink (PID 1 udev group), wakeup_sources
  diffs (suspend), disassembly of Xiaomi modules (66-byte keyboard writes,
  unconditional printk, pd_auth cmd 200).
- Safety nets before risky steps: boot counter -> Fastboot, download_mode=0, backups
  + frozen copies + rollback partition, Wi-Fi SSH fallback, tablet identity checks
  (MemTotal / fs UUID) because both tablets share the USB address.
- Overlay as the source of truth + reboot test after each change (caught the zram
  ordering cycle); testing the runbook with a weaker model.

### Didn't work / detours
- Deep suspend (PMIC resume errors, +26 C ADC offsets -> anti-burn) -> s2idle.
  gEnableWoW=1 crashes WPSS; cfg80211 disconnect inside suspend oopses -> radio off.
- iwd impossible (no AF_ALG) -> NetworkManager; systemd-oomd impossible
  (cgroup_disable=pressure) -> earlyoom; USTA sensor streaming -> own QMI client.
- A coding agent's "keyboard log storm" diagnosis was wrong (the cause was memory).
- Own bugs, caught and fixed: golden image root-owned home dirs and a service
  binary dropped by an over-broad exclude; personalize.sh wiped the pacman keyring; loa-zram
  ordering cycle; make-image could stream from a swapped tablet.
- Unsolved: cover-open doesn't wake from suspend (ADSP holds the hall event);
  Xiaomi adapter auth (ADSP never performs the DR swap) -- in progress.

### Not started / open
- Cameras, modem; headset jack (no headphones yet); tap-to-wake; auto-rotate (skipped).
- Screensaver (ttfx) and 26 Omarchy packages not built for aarch64 (omarchy-nvim, yay,
  obsidian, ...). Docker skipped by choice.
- Overnight battery drain unmeasured; one unexplained self-reboot during the suspend
  work; wallpaper vanished once after a reboot; Android props snapshot carries the
  first tablet's serial.
- Repo not pushed; clone-image path only (no from-scratch rootfs build); slot-a
  untested.
- Second tablet: batterysecret applied 2026-09-27 (authentic=1, ichg cap 3000 mA).

### 2026-09-27: overlay overwrote the owner's Hyprland settings -> restructured

- apply-overlay.sh untarred the whole overlay, which contained full copies of
  ~/.config/hypr/{bindings,input,looknfeel,monitors,autostart}.lua, hypridle.conf,
  chromium-flags.conf and the fcitx5 profile. On the new tablet it reset the owner's
  Super+Shift+S screenshot, Super+A agent, Caps<->Ctrl/Compose-RAlt and natural
  scrolling (made through a coding agent). Recovered the exact edits from the agent's
  session transcripts (a raw-disk grep found them) and restored them.
- New layout:
  - device settings in rootfs-overlay/usr/share/loa/hypr/loa.lua (monitor/scale,
    Virtual-1/2 off, touch transform, XF86PowerOff unbind, Super+Space global
    menu, voxtype/hypridle autostart, and the look/render/env block carried
    over unchanged, TODO review natively: vfr=false, cursor, LANG=C.UTF-8);
  - `dofile("/usr/share/loa/hypr/loa.lua")` right after
    require("default.hypr.omarchy") in hyprland.lua (added by apply-overlay);
  - personal hypr files = Omarchy template + the owner's own lines only;
  - user-defaults/ (hypridle.conf, chromium-flags.conf, fcitx5/profile) seeded only if
    missing;
  - PipeWire/WirePlumber LoA drop-ins moved to /etc/pipewire, /etc/wireplumber
    (legacy home copies removed by apply-overlay);
  - apply-overlay: --diff mode, backups of replaced files in
    /var/backups/loa-overlay/<time>/, user files created as omarchy.
- Verified on the new tablet after a reboot: no config errors, DSI-1 3200x2136@120
  scale 2, the owner's settings intact, hypridle once each, Speakers + mic sinks
  once each, is-system-running = running.
- Pending: the first tablet (check for lost settings in its .bak files / agent
  transcripts, migrate its personal files the same way).
- First tablet migrated the same way. The agent transcripts on it
  showed three of the owner's edits that earlier overlay runs had reset: kb_options
  "ctrl:swapcaps,compose:ralt,shift:both_capslock_cancel" (10:30), touchpad
  natural_scroll (11:25), Super+Shift+S screenshot (11:56). Restored exactly (no Super+A
  here; that was only asked for on the second tablet). Personal files = template + those
  lines; apply-overlay added the loa.lua line, audio drop-ins in /etc, legacy home
  copies removed. Verified: no config errors, DSI-1 scale 2, settings live, PipeWire
  restarted with one speaker + one mic device, no root-owned files in the home. Charging
  test leftovers (logs, failed loa-chglog2 unit) cleaned up; backups removed at the owner's request.
- Next: rebuild the golden image from the migrated first tablet.

### 2026-09-27: Xft.dpi for X11 (XWayland) apps

- A coding agent on the second tablet noticed: fcitx5's candidate window in X11 apps was half size.
  Omarchy sets xwayland force_zero_scaling = true, so X11 clients render at 1x and
  scale from Xft.dpi, which nothing set (xrdb wasn't even installed) -> 96 DPI.
  Omarchy itself has no Xft.dpi handling (it relies on native Wayland apps).
- Preset: /usr/share/loa/X11/Xresources (Xft.dpi: 192 = 96 x scale 2), loaded at
  session start by /usr/lib/loa/loa-xresources.sh (from loa.lua): waits for
  XWayland, `xrdb -nocpp -merge` the preset, then merges ~/.Xresources if present (the
  user wins), then `fcitx5-remote -r` so fcitx5 picks up the DPI. -nocpp because
  apostrophes in comments trip xrdb's C preprocessor.
- Package: xorg-xrdb (+ libxmu), installed on the first tablet. GTK apps mostly run
  on native Wayland (GDK_BACKEND=wayland,...), so there's no GDK_SCALE double-scaling concern.
- Verified on the first tablet: xrdb -query shows Xft.dpi 192 in the live session.
  Pending: the owner's visual check in an X11 app; the second tablet (xorg-xrdb +
  apply-overlay; first check what the agent set there); golden image rebuild.

### 2026-09-27: fonts split (UI vs terminal) + Omarchy icon font was never installed

- Second tablet: an agent had pointed every generic family (sans-serif, serif, system-ui,
  sans) and gtk-font-name at the owner's monospace font. Owner's own config
  (~/.config/fontconfig/fonts.conf, gtk-3.0/4.0 settings.ini, gsettings) now:
  monospace -> the owner's terminal font; sans-serif/sans -> Noto Sans + Noto Sans CJK SC;
  serif -> Noto Serif + Noto Serif CJK SC; system-ui, -apple-system,
  BlinkMacSystemFont -> assign_replace Noto Sans + CJK SC (Omarchy's
  50-omarchy.conf aliases them to Liberation Sans). Terminals unchanged. Testing
  tip: fc-match needs `system\-ui` (a bare dash is pattern syntax).
- The bar's menu logo (U+E900) and the agent/app menu icons (iconFont "omarchy") use
  Omarchy's own font, /usr/share/omarchy/default/fonts/omarchy/omarchy.ttf, which a real
  install places at /usr/share/fonts/omarchy/omarchy.ttf. Never installed here, so the
  glyphs fell back to whatever font; the new rules made the logo render as tiny
  letters. New /usr/lib/loa/install-omarchy-font.sh (symlink + fc-cache), run by
  apply-overlay. fc-match omarchy -> omarchy.ttf; shell restarted.
- Second tablet also got xorg-xrdb + the Xft.dpi preset (the agent had only discussed it:
  no ~/.Xresources existed); xrdb -query = 192.
- First tablet: gets the font fix with its next apply-overlay.

### 2026-09-27: global Xft.dpi 192 reverted -- it double-scaled a heavy X11 app

- With Xft.dpi 192, a Chromium/Electron-based X11 app came up "humongous": it already
  scales itself 2x (it picks up GDK_SCALE=2), so the DPI doubled it again. Only fcitx5's
  X11 candidate window needed it. Lesson: test a heavy X11 app before changing a global
  X setting.
- Reverted: xrdb -remove in the live session; the preset and loa-xresources.sh dropped
  from the overlay; apply-overlay step 4a deletes them from tablets that got them.
- Dead ends for the fcitx5 X11 popup: classicui PerScreenDPI (no effect under XWayland);
  Font "Sans 20" + ForceWaylandDPI=48 (a Qt app's client-side panel went 4x). Note
  `fcitx5-remote -r` only reloads the config; classicui font/DPI changes need
  `systemctl --user restart omarchy-fcitx5`.
- fcitx5 DebugInfo (busctl --user call org.fcitx.Fcitx5 /controller
  org.fcitx.Fcitx.Controller1 DebugInfo) shows the path per app: foot/Chromium use
  wayland_v2 (popup drawn by fcitx5 on Wayland: 2x, right); Qt apps with the fcitx5
  plugin draw their own panel (2x); X11 apps go through the xcb popup at 96 DPI under
  force_zero_scaling (1x).
- Fix: run Chromium/Electron apps as native Wayland clients
  (--ozone-platform=wayland --enable-wayland-ime --wayland-text-input-version=3), e.g.
  with a user override in ~/.local/share/applications/ (package updates don't touch it).
  fcitx5 back to its default classicui config.
- Golden image rebuilt (sha256 3216b4c1...). Audit: new layout (loader line;
  autostart/looknfeel/monitors = templates), audio drop-ins only in /etc, no Xft.dpi
  preset, omarchy.ttf linked, 0 root-owned files in the home, no personal data, password
  locked, empty machine-id, no wlan_mac.bin. `--reset-hypr` resets the personal hypr
  files to Omarchy's templates for a tablet that isn't yours.

### 2026-09-27: Xiaomi Focus Pencil Pro (P81C) works as a pointing device

- Captured on stock Android (adb logcat + getevent; reference/logcat-pen-pairing-excerpt.txt,
  reference/getevent-pen-excerpt.txt):
  - attach: hall on, wireless charger reports the pen (kernel "PEN_MAC=xxxxxxxxb753",
    SoC); com.xiaomi.bluetooth MiuiBleOobHelperService scans for that MAC (the pen
    advertises for a short time after being attached), createBond over LE: despite the
    name, no OOB data (oob_data:0), Just Works (pairing type 3);
  - Bluetooth HID (HOGP) + Battery; three input devices "Xiaomi Focus Pen Pro"
    (+ Keyboard, + Mouse);
  - TouchFeature setModeValue on HID connect: 20=24, 29=0, 22=1, 22=259, 29=0, 37=1,
    29=1; on disconnect: 20=8, 37=0 (36/20036 toggle while drawing = probably palm rejection);
  - strokes: kernel "NVTCapacitivePenP81c": X 0..213599 (short side), Y 0..319999,
    100 units/px, pressure 0..16383, tilt +-60, ABS_BRAKE +-180 (barrel rotation);
  - pen firmware OTA over SPOTA GATT (0.0.28 -> 0.0.32).
- Native: the touch modes alone don't make the pen report strokes; it has to be connected
  over BLE. BlueZ Just Works pairing works (bluetoothctl --agent NoInputNoOutput pair,
  trust, connect) within 3 s of attaching.
- libinput rejected the NVT pen devices ("missing tablet capabilities: btn-stylus
  resolution"): hwdb 61-loa-pen.hwdb (EVDEV_ABS_00/01=::1212, panel 264.0x176.2 mm) +
  quirk AttrEventCode=+BTN_STYLUS. Then pressure never produced a tip (the driver toggles
  BTN_TOOL_PEN between hover and contact, so libinput treats the contact pressure as the
  offset); hiding ABS_PRESSURE/ABS_DISTANCE made BTN_TOUCH the tip. The tablet transform
  is 3 (the first test didn't apply it: Hyprland doesn't watch loa.lua).
- But Hyprland only forwards tablet tips via tablet-v2 (no pointer emulation), so taps
  didn't click in most apps. The owner wants a pointing device -> loa-pen.service
  (/usr/lib/loa/loa-pen.py):
  - grabs the NVT pen devices, emits uinput "LoA Pen Pointer" (absolute mouse, udev
    ID_INPUT_MOUSE): hover moves, tip = left button; tap/drag threshold DRAG_PX 16;
  - gestures from "Xiaomi Focus Pen Pro Keyboard" (the Pro has no buttons): pinch F19
    (held while squeezed): quick = middle click, hold + move = scroll (natural,
    hi-res); double tap KP Enter = right click; swipe up KP9 = Forward, down KP3 =
    Back;
  - mutes "Xiaomi Focus Pen Pro" (KEY_KPPLUS flood with sensor values while writing ->
    "++++" typed) and the unused "... Mouse";
  - touch modes on BT HID connect/disconnect; pairs an unknown attached pen (tx_mac).
- Owner feedback: works; scrolling "on the edge of losing control", swipes hard to
  trigger. The model is kept as is while the owner decides. Open: haptic feedback on
  gestures (Android writes to the pen's vendor GATT service; needs an HCI snoop capture),
  pressure/tilt (lost in pointer mode), palm rejection (modes 36/20036), other pen models
  (22=259 is P81C-specific), and auto-pairing via tx_mac on attach (untested).
- Wrap-up (owner decision): keep double tap = right click; drop pinch (middle click /
  pinch-hold scroll) and swipes (back/forward) until they have a better use. Observed:
  swipes (and hover-based scrolling) only work while the pen is in hover range, but
  browsing happens with the pen away from the screen. Tap/drag threshold kept.
- Next (owner: "I foresee trouble"): the pen has an accelerometer + gyro. The
  "Xiaomi Focus Pen Pro" HID device's KEY_KPPLUS flood carries values like 292 / 16384
  / 16384 (16384 = 1 g at +-2 g, 16-bit): likely IMU data misparsed by hid-input. Plan:
  read the report descriptor from its /dev/hidraw*, record raw reports (idle, waving,
  pinched, near/far), find out when it streams; if it needs enabling, capture Android's
  vendor-GATT writes with the HCI snoop log (same session as haptics). Goal: air
  gestures that work away from the screen (e.g. pinch-hold + rotate = scroll).
- Second tablet: overlay applied (loa-pen, hwdb, quirk, tablet mapping), loa-pen started.
  Automatic pairing fixed: wireless_master/tx_mac stays empty, the pen MAC only appears in
  the kernel log ("POWER_SUPPLY_PEN_MAC=xxxxxxxxb753" every ~10 s while attached) ->
  loa-pen follows /dev/kmsg (from the end), pairs an unknown pen at most once a minute.
  Tested for real: bluetoothctl remove, re-attach -> the daemon paired, trusted, connected
  and sent the touch modes by itself (~30 s). The pen is now bonded to the SECOND tablet;
  moving it back to the first one = attach it there (its daemon has the same auto-pairing).
- Second tablet after a reboot: no hover/tap/double tap although loa-pen was running,
  the pen was connected and the touch modes were set; raw NVT pen events did arrive with
  the daemon stopped. Also the "++++" came back after the pen's Bluetooth reconnect.
  Cause: loa-pen tracked devices by eventN, and eventN numbers get reused when a device is
  re-created (BT HID reconnect; pen devices re-created at boot), so it kept dead handles and
  thought the new devices were already grabbed/muted. Fix: track the kernel instance
  (/sys/class/input/eventN/device -> inputM), re-grab when it changes, and re-send the touch
  modes if the pen devices are re-created while the pen is connected. Reboot test: pen
  connected 54 s after boot, everything automatic; owner: "complies fully".
- First tablet still runs an older loa-pen (tx_mac pairing, eventN tracking): apply-overlay
  next time it is plugged in.

### 2026-09-28: spontaneous resets on USB-C dock/monitor attach; crash capture

- Symptom (owner, a full working day on the 12 GB tablet): connecting a monitor or
  the office USB-C dock sometimes resets the tablet. Four events: first direct
  USB-C->DP at home, first attach of the dock, a re-plug at 15:46 (screen on, log
  ends ~4 s after the plug while the dock's USB devices enumerate), and 21:12->21:18
  (on battery, screen off, s2idle cycling; the next boot starts with the dock
  attached, so most likely plugged into the sleeping tablet).
- PMIC PON log: `Reset Trigger: PS_HOLD` = the SoC reset itself (panic/watchdog/
  firmware), not a power loss. Common factor: a Type-C attach entering DP Alt Mode.
  Not the DP link-rate change (events 1-2 predate it), not the dock's NIC (event 1
  had no dock), not suspend (event 3 was with the screen on). Root cause still open.
- No panic text anywhere: pstore empty, systemd-pstore disabled, the 500M journal
  held ~5 hours (driver log storm) and synced every 5 min, so the last seconds
  before a reset never reached disk.
- Crash capture, tested with `echo c > /proc/sysrq-trigger`:
  - reboot mode warm (/sys/kernel/reboot/mode; tmpfiles rule) alone: PMIC shows
    WARM_RESET, but the ramoops console is still wiped;
  - + download_mode=1 (opt-in loa-crashdump.service, flag /etc/loa/crashdump-on-panic):
    panic -> Apps watchdog bite -> warm reset with RAM kept -> normal boot, and
    systemd-pstore archived console-ramoops-0 with the marker and "Kernel panic -
    not syncing". No CrashDump screen this time, no buttons needed.
  - journald: SystemMaxUse 2G (about a day), SyncIntervalSec 10s.
  Armed on the 12 GB tablet. Next: reproduce with the dock (screen on, then asleep).
- The owner's Codex session changes, reviewed: golden image gets btop, yay-bin and
  fakeroot-tcp (the GKI has no SysV IPC, /proc/sysvipc absent, so stock fakeroot and
  makepkg fail; AUR packages repacked from the installed files into images/pkgs/,
  git-ignored) and Omarchy's [omarchy] pacman repo (setup-omarchy-repo.sh, re-run by
  personalize.sh after its keyring reset). Kept out: the 12 GiB zram override + swap
  file (sized to one tablet), dp-hbr3.service (raises the vendor DP link cap
  540000->810000 for 4K60 over 2-lane docks; revisit after the reset bug) and all
  personal preferences. make-image.sh now excludes those and dereferences dotfiles
  that are symlinks into a repo outside the home whitelist.

### 2026-09-28/29: from-scratch root image builder

- Inventory of a working root (files no package owns, not in the overlay): Omarchy
  copied to /usr/share/omarchy (= upstream 158e8cf + the 3 omarchy-android PRoot
  patches, inactive natively since OMARCHY_PROOT is unset, + one audio-slider fix
  -> patches/omarchy/), Mesa-KGSL in /opt/omarchy-android/mesa (built by the PRoot
  pipeline), 4 runtime scripts in /usr/local/bin (Xwayland -shm wrapper, voxtype,
  dbus helper), and device blobs: 980 kernel modules, 184 MB firmware, the THP
  chroot. /opt/omarchy-android/{hyprland,aquamarine} were dead PRoot leftovers.
- Every blob can come from the tablet itself: system_dlkm/vendor_dlkm (mapped out
  of super, like the island's partitions), vendor/odm/modem firmware, the runtime
  APEX (Bionic) + odm touch libs. Verified byte-identical against the working
  system. -> loa-vendor-import.service (import-vendor.sh) before loa-modules, and
  stage 1 copies the first-stage modules (only visible in the vendor ramdisk).
- builder/build-image.sh: disposable build root compiles Mesa (pinned lfdevs fork,
  KGSL), Aquamarine 0.15.1 + our patch and ttfx 0.5.0 (packaged without makepkg:
  stock fakeroot needs SysV IPC); clean target root gets builder/packages.txt,
  Omarchy, the overlay via tools/overlay-install.sh (split out of
  apply-overlay.sh), user/locale/keyring; privacy checks; mkfs.ext4 -d. ~30 min on
  the 12 GB tablet, 2.3 GiB compressed.
- Pitfalls: pacstrap/arch-chroot need devtmpfs (absent in GKI) -> own chroot setup
  with the host's /dev bound; pacman CheckSpace needs / to be a mount point ->
  self-bind; that self-bind joined the host's shared peer group, and unmounting the
  build's /sys and /dev binds UNMOUNTED THE HOST'S cgroup2, /dev/pts, /dev/shm,
  debugfs, binderfs... (journald could no longer restart: "Failed to create
  cgroup"). Reboot fixed it; the builder now runs in a private mount namespace
  (unshare --mount --propagation private). Also: macOS fastboot fails on a 16 GiB
  raw file ("Failed reading from ramdump") -> tools/img2simg.py (sparse, verified
  bit-exact); install.sh uses it.
- Tested on the 8 GB tablet without touching its system: image on ramdump +
  init_boot-omarchy-test-ramdump.img (stage 1 prefers ramdump). First boot:
  465 ramdisk modules, 974 modules, 184M firmware, THP chroot imported; desktop,
  touch, audio, Bluetooth, keyboard, pen up; after personalize.sh Wi-Fi works.
  Fixed from the test: loa-zram raced the import (depmod) -> ordered after it;
  WCNSS ini now imported; mimeapps.list seeded; Omarchy branding defaults
  (screensaver.txt, about.txt) seeded; ttfx built (Omarchy ships it x86_64 only),
  so the screensaver works (the old tablets had it toggled off as a workaround).
- Open: publishing images (CI on ARM runners), first-login password, property
  snapshot without Magisk, Omarchy 4's own install/config + install/user steps
  (neither the old tablets nor this image ran them).

### 2026-10-22: battery ran flat twice -> loa-sleepd powers off at 3 %

- 12 GB tablet, two brown-outs (PMIC PON: UVLO / SMPL). The kernel's "Trigger Android
  shutdown for CAPACITY_LEVEL_CRITICAL" had no listener.
  - 2026-09-30: a single 27.3 h s2idle sleep (xiaomi_power "suspend for 98411750 ms")
    went from 100 % to 0 %; only the battery current limiter (bcl-lvl0, IRQ 36) woke it.
  - 2026-10-11: awake all along. From 10-10 13:42 dwc3 refused every suspend ("failed
    dev a600000.dwc3 at prepare", 3236 times) with no USB power; ~3.5 %/h, screen off.
  - UPower recorded 2 % -> 1 % -> 0 % (/var/lib/upower/history-charge-*) but
    CriticalPowerAction=Auto never acted (logind: CanHibernate/CanHybridSleep "no").
- loa-sleepd: battery discharging at <= 3 % (checked every 30 s and before every
  suspend) -> critical notification, power-off after 30 s unless a charger shows up
  (the RTC alarm is cleared first so it can't power the tablet on). Every suspend arms
  an RTC wake alarm (rtc-pm8xxx; its counter starts at 1970 but "+N" works): 30 min,
  10 min at <= 10 %. The "resumed:" line now logs the battery level.
- Tested with a copy that reports 2 % after 240 s of discharging and uses 60 s alarms:
  - awake: powered off cleanly (PON "Reset Type: SHUTDOWN"; plugging the cable in boots
    it via USB_CHARGER);
  - asleep: RTC wakes every ~76 s ("wake irq 32, fired: ...rtc@6100"), and the check
    right after one of them powered it off.
- Found on the way: Omarchy's screensaver relit a screen switched off with the power
  key. loa-power-key grabs the key, so Omarchy's idle timer still counted from the last
  touch; at 150 s the idle service launched the screensaver, which turned DPMS back on
  and counted as activity (restarting hypridle's 5 min screen-off). ->
  patches/omarchy/0005: omarchy-launch-screensaver does nothing while every display is
  off (checked: exit 1, DPMS stays off, no screensaver process). Not fixed: a
  screensaver that is already up when the screen goes off keeps animating until the next
  suspend; killing it would relight the screen (the idle service then runs
  omarchy-system-wake -> DPMS on).
- Idle timers (Omarchy's, hypridle's) only count awake time; a resume from s2idle is not
  reported as activity.
- Deployed by hand on the 12 GB tablet (loa-sleepd, patch applied in /usr/share/omarchy).
- Open: s2idle drains ~3.7 %/h, about the same as staying awake with the screen off;
  the dwc3 suspend refusal.

### 2026-10-22: Omarchy from its own packages; `omarchy update` follows upstream

- Why the tablets could not follow upstream: Omarchy was a copy of commit 158e8cf
  (4.0.0.alpha, 2026-08-29) in /usr/share/omarchy that no package owned, 974 commits
  behind. Omarchy 4 now ships as pacman packages with an aarch64 stable channel:
  `omarchy` + `omarchy-settings` 4.0.6 at pkgs.omarchy.org/stable/aarch64, and
  Omarchy's Arch Linux ARM snapshot at arm-stable-mirror.omarchy.org (about a day
  behind ALARM; 2.7 MB/s from here, TUNA 30 MB/s).
- Found broken on the 12 GB tablet first: on 10-21 the copied tree's
  `omarchy-refresh-pacman` had copied the **x86_64** template over /etc/pacman.conf
  ([multilib], stable-mirror.omarchy.org, no [alarm], IgnorePkg gone); its
  `pacman -Syyuu` failed at the sync, so nothing was installed. 4.0.6's
  refresh-pacman still does this on ARM (upstream master has per-platform templates).
- Upstream's `omarchy-hw-platform` reports this tablet as `aarch64-qualcomm` (the
  Android device tree's root is `qcom,alor-mtp qcom,alor ...`), i.e. a Snapdragon X
  laptop: its Qualcomm install steps (Windows firmware extraction, UKI device trees,
  blacklisting qcom_q6v5_pas, Limine kernel parameters) must never run here.
- Reviewed the 30 migrations between 158e8cf and 4.0.6. One is dangerous here:
  1788124236 disables sshd when the Omarchy user has no authorized key (our SSH is
  root, key-only) -> skipped. 1787865477 drops the user from `input`: fine, Hyprland
  opens input devices through seatd (`LIBSEAT_BACKEND=seatd`). The Limine, kernel and
  NVIDIA ones exit on this hardware.
- The KGSL Mesa in /opt links `libLLVM.so.22.1` (llvmpipe); this upgrade brings
  llvm-libs 23, which drops it, and the GPU stack would have failed to load. A copy of
  the old library now sits in /opt/omarchy-android/mesa/root/usr/lib (on the session's
  LD_LIBRARY_PATH; versioned soname, no clash), and 20-loa-mesa-keep-llvm.hook does
  that by itself before any llvm-libs upgrade (simulated: copies it). The builder now
  builds Mesa without LLVM. SPIRV-Tools is used only through its C API, unaffected.
- The switch (12 GB tablet): root tar to /var/backups/loa-pre-quattro-20261022.tar.zst
  (9.3 GB); pacman.conf = Omarchy's aarch64 stable template + `IgnorePkg = aquamarine`;
  the 96 migrations of the copied tree marked done; old tree moved to
  /var/backups/omarchy-pinned-158e8cf; one transaction `pacman -Syu omarchy
  omarchy-settings --ask 5 --overwrite ...` (285 packages, 1.7 GB: systemd 262.1,
  Qt 6.12, LLVM 23, Hyprland 0.56.2-7 from [omarchy], Quickshell 0.3.2,
  ttf-jetbrains-mono-nerd -> -basic, plus plymouth, sddm, xorg-server as new
  dependencies). `--ask 5` = remove the conflicting font, and do NOT install an
  IgnorePkg package. First attempt stopped at the file-conflict check
  (/etc/fonts/conf.d/50-omarchy.conf), nothing changed. Then the 29 remaining
  migrations as the user (sudo without password only for that run).
- Device side, in the overlay:
  - 10-loa-aquamarine-guard.hook: aborts any transaction that would replace our
    patched Aquamarine (pacman installs an IgnorePkg package anyway under
    --noconfirm when a dependency needs it). Tested: `pacman -S aquamarine` aborts.
  - 95-loa-omarchy.hook -> omarchy-post-upgrade.sh: re-applies the Omarchy patches
    (now rootfs-overlay/usr/share/loa/omarchy/patches/0003-0005; 0001/0002 were
    PRoot-only and are dropped; none is upstream yet), marks migrations-skip, lists
    pending migrations that touch boot/modules/sshd/groups, removes the copied
    install's /usr/local/bin links. bin/ in the package is links to /usr/bin, so bin/
    patches apply at /usr. Pitfalls: patch's default fuzz applied 0003 a second time
    in another function; `--batch` "un-reverses" a patch by itself and made the
    already-applied check pass on an unpatched file. Now `-f --fuzz=0`, reverse check
    first; verified applied once, idempotent over three runs.
  - setup-omarchy-repo.sh puts back the aarch64 channel when it finds an x86
    template, called by the user hook pre-refresh-pacman.d/loa-device. Tested by
    copying 4.0.6's x86 template in: result identical to before.
  - plymouth (an omarchy-settings dependency) masked: no initramfs or LUKS here, and
    its boot/shutdown units would take DRM master from our stage 1 splash and Hyprland.
- Reboot: all LoA services active, no failed units, Hyprland on Adreno 829 (KGSL
  libgallium + the copied libLLVM 22 mapped), 18 input devices open without the
  `input` group, Wi-Fi up; Omarchy 4.0.6 shell renders. `omarchy-update-available`:
  up to date; no pending migrations.
- Also seen: Wi-Fi was soft-blocked after the earlier reboot (systemd-rfkill restored
  the state loa-sleepd leaves during sleep); two critical "Battery at 2 %" test
  notifications from 21:59/22:08 come back after every reboot (stored, no expiry).
- Builder updated (packages instead of the copied tree, no ttfx build, Mesa without
  LLVM, user config from /etc/skel), **not built yet**. The 8 GB tablet still runs the
  copied tree.
- Patch 0004 (audio output slider) dropped: upstream's `volumeSink` returns `sink`
  when `sink` is empty, so whenever `hasOutput` holds, `!!sink` holds too; the
  patch only mattered on top of the omarchy-android PRoot changes (found while
  preparing the upstream PRs for 0003 and 0005). Reversed on the 12 GB tablet
  (Panel.qml matches the package again).

### 2026-10-23: Super+Space back on Omarchy's own binding (issue #1)

- Symptom (12 GB tablet, after the switch to Omarchy 4.0.6 packages): Super+Space
  did nothing; other SUPER bindings, `hyprctl reload` and `omarchy-menu toggle` by
  hand all worked, so it looked like an input-method problem.
- Cause: loa.lua rebound Super+Space to `hl.dsp.global("omarchy:menu")`. Only the
  dropped PRoot patch 0001 registered that global shortcut (a `GlobalShortcut` in
  shell.qml); the packaged shell has none, so `hyprctl globalshortcuts` lists no
  `omarchy:menu` and the key goes nowhere. 0001 was not PRoot-only after all: the
  overlay depended on that hunk.
- Fix: loa.lua no longer touches Super+Space, so Omarchy's default applies
  (4.0.6: `omarchy-menu toggle`). The issue's workaround (the same command bound in
  ~/.config/hypr/bindings.lua) is redundant now and can stay or go.

### 2026-10-23: empty Apps list in a cloned menu, Omarchy patch 0006 (issue #2)

- Symptom (12 GB tablet, Omarchy 4.0.6 packages): the menu's Apps submenu showed
  "Nothing here yet". The issue suspected Quickshell 0.3.2.r7, upgraded in the same
  transaction.
- Not Quickshell: its DesktopEntries code changed only by trimming lines while
  parsing (0.3.1..2b4501a), and a standalone `quickshell -n` probe run with the shell's
  environment loads 52 entries within 5 s. (Reading `DesktopEntries.applications`
  once starts the scan, so a probe that reads it only once reports 0; upstream
  #15849 fell for that.)
- Cause: the user's config enables a clone of the menu (`omarchy plugin clone
  omarchy.menu`), which disables `omarchy.menu` and takes over `omarchy menu`.
  Since Omarchy 4.0.3 a plugin that isn't first-party gets a scoped shell API,
  and `appLibrary` only when `manifestHasKind(manifest, "menu")` holds.
  The panel Instantiator passes the manifest from `modelData`, where `kinds` is a
  QVariantList; `Array.isArray()` is false for it, so the clone's `appLibrary` is
  null and `mergeAppRows()` returns before adding a row. The copied 158e8cf tree
  predated the scoped API, so the switch to the packages exposed it. Upstream:
  omacom/omarchy#10876, #12881, #15851 and others; fixed on quattro by #13439
  (the delegate reads the manifest from the registry), first in v4.5.0-rc1.
- Patch 0006 (shell/shell.qml): `manifestHasKind()` accepts any indexable list,
  not only a JS array. Applied by the post-upgrade script; a second run is a no-op.
- Verified on the 12 GB tablet with the clone enabled: the shell that was still
  running unpatched showed "Nothing here yet"; after `omarchy-restart-shell` the
  same clone lists the apps. No new warnings in the shell log.
- 0006 still applies cleanly to v4.5.0-rc1 (`manifestHasKind()` is unchanged
  there), so the post-upgrade script will not flag it: drop it by hand once
  Omarchy 4.5 is installed (see docs/maintenance.md).

### 2026-10-23: omarchy-font-set restart reminder, Omarchy patch 0007 (issue #3)

- Symptom (Omarchy 4.0.6 packages): `omarchy-font-set` with Ghostty running prints
  the Ghostty PIDs and then omarchy-notification-send's usage message; the
  "restart Ghostty" reminder never shows. The font itself is set.
- Cause: upstream v4.0.6 passes `-g` with an empty glyph, so the headline is taken
  as the glyph and no headline is left. `pgrep -x` without redirection prints the
  matched PIDs. Upstream restored the glyph (U+E659) on quattro, first in
  v4.5.0-rc1; the pgrep output is unchanged there.
- Patch 0007 (bin/omarchy-font-set, base /usr): the same glyph, and pgrep output
  sent to /dev/null. The glyph lines differ in v4.5.0-rc1 (i18n strings), so the
  post-upgrade script reports 0007 as no longer applying once 4.5 lands: drop it
  then.
- Verified on this tablet: with 0007 applied, pgrep is quiet and the glyph is
  passed, but the reminder still failed with "Call failed: The name is not
  activatable". `omarchy-restart-shell` returns once the shell answers ping, before
  its notification plugin owns org.freedesktop.Notifications; a toast sent right
  after a stock restart reproduces it, and a toast sent 20 s later works.
- Patch 0008 (bin/omarchy-restart-shell, base /usr): backport of upstream 177d572
  and 43b9116. When the service was up before the restart, wait up to 2 s for it
  to return. Verified: restart with the patched script, then a toast succeeds.
  v4.5.0-rc1 restructured the readiness loop, so 0008 stops applying there and the
  post-upgrade script flags it.

### 2026-10-23: Omarchy's user units and avahi into the overlay

An inventory of the 12 GB tablet against the overlay found device-level pieces
that the overlay and the builder didn't provide:
- `bt-agent.service` and `omarchy-fcitx5.service` were enabled by hand
  (2026-09-26/27) through links in `~/.config/systemd/user/default.target.wants`
  to the overlay's `/etc/systemd/user/<unit>`, links into the copied Omarchy
  tree. Omarchy enables both for `graphical-session.target`, which this session
  never reaches, and nothing in the overlay or the builder enabled them, so a
  fresh image had no Bluetooth pairing agent and no input method. The overlay now
  enables the packaged units (`omarchy-settings`, `/usr/lib/systemd/user`) for
  every user in `/etc/systemd/user/default.target.wants` and no longer ships the
  `/etc/systemd/user/<unit>` links, which shadowed the packaged units.
  apply-overlay removes the old links and the per-user enables, but only where
  the packaged units exist (not on a tablet still on the copied tree, which keeps
  its links and needs the package switch anyway). The global enable also
  reaches root's user manager (serial-console autologin, SSH): its bt-agent
  competed for the default agent and its fcitx5 waited forever for a
  WAYLAND_DISPLAY, so the LoA drop-ins add `ConditionUser=!@system`.
- `avahi-daemon` (`<hostname>.local`): Omarchy's installer enables it
  (`install/config/enable-services.sh`), ours doesn't run that installer. Added
  to the overlay's enables (its own command: a missing unit would fail the
  whole list).

### 2026-10-24: Install menu entries that can't work on ARM; Electron sandbox helpers

Installing Bitwarden from the Omarchy menu failed: `target not found: bitwarden`.
Omarchy 4.0.6's menu offers its x86_64 catalogue on every machine, and its
aarch64 stable repository lacks some of it.
- An audit of all 90 Install entries (packages read from each entry's action and
  the scripts it calls, checked with `pacman -Sp`) found 8 that can't install
  here: Bitwarden, Spotify, RetroArch (`libretro-ppsspp`, `libretro-uae-git`),
  Heroic, Minecraft, Lutris and Battle.net (wine, `umu-launcher`), and Edge
  (AUR, x86_64 only). Three more install but can't work: Xbox Controllers
  (`xpadneo-dkms`, no kernel headers for the vendor kernel), the Windows VM
  (no `/dev/kvm`) and GeForce NOW (x86_64 Flatpak).
- Upstream is closing most of it: on `quattro` (4.5) Windows, Edge, Minecraft,
  GeForce NOW, Battle.net and Lutris are shown on x86 only, Spotify becomes its
  web player on ARM, and the edge repository has aarch64 builds of `bitwarden`
  and the two libretro cores (not yet in stable). Heroic is still offered on ARM.
- `/usr/lib/loa/omarchy-menu-audit.py` now does that audit after every Omarchy
  package change (95-loa-omarchy.hook) and on apply-overlay, and hides the
  entries that can't work (`when: false`, original kept in `loaWhen`); the
  device limits are listed in `/usr/share/loa/omarchy/menu-hide`. A hidden entry
  comes back once its packages resolve. It follows `case` branches by argument
  and `if omarchy-hw-...` tests by this machine, so 4.5's Spotify web-player
  path counts as installable. 1.8 s on the 12 GB tablet.
- Bitwarden: installed on the 12 GB tablet from the edge repository
  (`pacman -U https://pkgs.omarchy.org/edge/aarch64/bitwarden-2026.10.1-1-aarch64.pkg.tar.zst`,
  signature checked against Omarchy's key) plus `bitwarden-cli`. No updates
  until stable carries it; the edge repository itself was not added.
- It then aborted at start: "The SUID sandbox helper binary was found, but is not
  configured correctly". The kernel has no user namespaces (`CONFIG_USER_NS` is
  off), so Chromium and Electron rely on the setuid `chrome-sandbox`; Omarchy's
  aarch64 Bitwarden ships it 0755 with all of `/opt/Bitwarden` owned by uid 1001
  (its builder). x86 machines have user namespaces and never notice.
  `30-loa-chrome-sandbox.hook` makes every packaged `chrome-sandbox` setuid
  root and hands a tree owned by another uid to root; apply-overlay does the
  same for what is already installed.
