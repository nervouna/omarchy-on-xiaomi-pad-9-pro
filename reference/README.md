# reference/

Captures from the stock Android build (OS4.0.5.0.XFPCNXM) and from native
crashes. The engineering log relies on them.

- `keyboard-write-cmds.txt`: unique packets Android writes to /dev/nanodev0.
- `logcat-*-excerpt.txt`: keyboard/cover/backlight lines from stock logcat
  (boot, backlight changes, cover close). Full logs weren't kept (personal data).
- `sde-debug.txt`, `drm*-state.txt`, `drmprops-*.txt`, `display-state.txt`:
  display pipeline state, used for the split-plane and first-frame fixes.
- `audio-state.txt`, `touch-state-idle.txt`: audio and touch bring-up (the stock `/vendor/bin/start_subsys.sh` is Qualcomm-proprietary and not included).
- `crashes/`: pstore logs of the two native kernel panics (2026-09-25).
