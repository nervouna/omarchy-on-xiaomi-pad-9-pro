#!/usr/bin/env python3
"""Tablet power key (pmic_pwrkey KEY_POWER), read straight from evdev
(Hyprland's XF86PowerOff binding missed presses).
  short press (< HOLD s): screen off/on (Hyprland DPMS + touchscreen disabled while off)
  hold (>= HOLD s):       screen on if needed, then the Omarchy system menu
The device is grabbed (EVIOCGRAB) so Hyprland never sees the key: Omarchy's
key_press_enables_dpms would otherwise wake DPMS on the press itself and the
release would read "on" and switch the screen off again. While the screen is
off we poll Hyprland; if another key woke it, touch is re-enabled.
Keyboard cover (xiaomi-hall SW_LID): closing turns the screen off, opening turns
it on; while closed, stray key presses under the cover can't keep it awake
(unless the power key woke it deliberately).
Double tap to wake: the touch controller keeps scanning for a double tap while
the panel is off (xiaomi-touch mode 14) and reports it as a key on the
touchscreen's input device. Hyprland has that device disabled while the screen
is off, so the key is read here. The gesture is off while the cover is closed:
the folded keyboard rests on the glass.
DPMS became safe once the first frame after continuous splash stopped failing
(AQ_DRM_FORCE_MODE_ID, NOTES.md)."""
import fcntl, glob, json, os, select, struct, subprocess, time
KEY_POWER, EV_KEY = 116, 1
HOLD = 0.7
EVIOCGRAB = 0x40044590
TOUCH = "nvtcapacitivetouchscreen-1"
TAP_DEV = "NVTCapacitiveTouchScreen"   # kernel name of the same device
KEY_WAKEUP = 143
XTOUCH, DOUBLETAP = "/usr/lib/loa/loa-xtouch", "14"   # Touch_Doubletap_Mode
FMT = "llHHi"; SZ = struct.calcsize(FMT)

def find(name="pmic_pwrkey"):
    for d in glob.glob("/sys/class/input/event*"):
        try:
            if open(d + "/device/name").read().strip() == name:
                return "/dev/input/" + os.path.basename(d)
        except OSError:
            pass

EV_SW, SW_LID = 5, 0
EVIOCGSW = 0x8008451b  # EVIOCGSW(8)

def lid_is_closed(fd):
    import array
    buf = array.array("B", [0] * 8)
    fcntl.ioctl(fd, EVIOCGSW, buf)
    return bool(buf[0] & (1 << SW_LID))

def user_env():
    hy = sorted(glob.glob("/run/user/1000/hypr/*/"), key=os.path.getmtime)
    return {"XDG_RUNTIME_DIR": "/run/user/1000",
            "HYPRLAND_INSTANCE_SIGNATURE": os.path.basename(hy[-1].rstrip("/")) if hy else "",
            "PATH": "/usr/share/omarchy/bin:/usr/local/bin:/usr/bin",
            "OMARCHY_PATH": "/usr/share/omarchy",
            "WAYLAND_DISPLAY": "wayland-1",
            "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus"}

def as_user(*cmd, wait=True):
    argv = ["setpriv", "--reuid=1000", "--regid=1000", "--init-groups", *cmd]
    if not wait:
        subprocess.Popen(argv, env=user_env()); return ""
    return subprocess.run(argv, env=user_env(), capture_output=True, text=True, timeout=5).stdout

last_on = True  # what we last set; used when Hyprland can't be asked
poll_at = 0.0    # next time to ask Hyprland whether something else woke the screen
tap_wake = True  # arm the double-tap gesture for the next screen-off
tap_set = None   # the mode the driver last accepted; None = retry

def arm_tap(on):
    global tap_wake, tap_set
    tap_wake = on
    try:
        r = subprocess.run([XTOUCH, "set", DOUBLETAP, "1" if on else "0"],
                           capture_output=True, text=True, timeout=5)
        ok = r.returncode == 0 and "ret 0" in r.stdout
        err = (r.stdout + r.stderr).strip()
    except Exception as exc:
        ok, err = False, repr(exc)
    if not ok and tap_set is not None:
        print("double tap mode failed:", err, flush=True)
    elif ok and tap_set is None:
        print("double tap mode set", flush=True)
    tap_set = on if ok else None

def screen_on():
    try:
        out = as_user("hyprctl", "monitors", "-j")
        return all(m.get("dpmsStatus", True) for m in json.loads(out))
    except Exception as exc:
        print("dpms query failed:", repr(exc), flush=True)
        return last_on

def set_screen(on):
    global last_on, poll_at
    last_on = on
    poll_at = time.monotonic() + 1.0   # give Hyprland time before asking it
    lua = "true" if on else "false"
    act = "enable" if on else "disable"
    if on:
        as_user("hyprctl", "eval", f'hl.dispatch(hl.dsp.dpms({{ action = "{act}" }}))')
        as_user("hyprctl", "eval", f'hl.device({{ name = "{TOUCH}", enabled = {lua} }})')
    else:
        arm_tap(tap_wake)   # the driver reads the mode when the panel goes off
        as_user("hyprctl", "eval", f'hl.device({{ name = "{TOUCH}", enabled = {lua} }})')
        as_user("hyprctl", "eval", f'hl.dispatch(hl.dsp.dpms({{ action = "{act}" }}))')
    print("screen", act, flush=True)

def menu():
    if not screen_on():
        set_screen(True)
    as_user("omarchy-menu", "toggle", "system", wait=False)
    print("system menu toggled", flush=True)

def run(dev):
    global last_on, poll_at
    print("listening on", dev, flush=True)
    last_on = screen_on()               # a restart may find the screen off
    fd = os.open(dev, os.O_RDONLY)
    fcntl.ioctl(fd, EVIOCGRAB, 1)
    lid_dev = find("xiaomi-hall")      # keyboard cover magnet: SW_LID 1 = closed
    lid = os.open(lid_dev, os.O_RDONLY) if lid_dev else None
    lid_closed = lid_is_closed(lid) if lid is not None else False
    power_on_while_closed = False       # the user woke it with the power key on purpose
    print("lid", lid_dev, "closed" if lid_closed else "open", flush=True)
    arm_tap(not lid_closed)
    tap = None                          # open only while we hold the screen off
    retry_at = time.monotonic() + 5     # the touch driver may load after us
    try:
        down = None  # monotonic press time while the key is held and undecided
        while True:
            if last_on and tap is not None:
                os.close(tap); tap = None
            elif not last_on and tap is None and find(TAP_DEV):
                tap = os.open(find(TAP_DEV), os.O_RDONLY | os.O_NONBLOCK)
            if down is not None:
                timeout = max(0.0, down + HOLD - time.monotonic())
            elif last_on and not lid_closed:
                timeout = None if tap_set is not None else max(0.0, retry_at - time.monotonic())
                if tap_set is None and timeout == 0.0:
                    retry_at = time.monotonic() + 5
                    arm_tap(tap_wake)
                    continue
            else:                                      # poll Hyprland once a second
                timeout = max(0.0, poll_at - time.monotonic())
            fds = [fd] + [f for f in (lid, tap) if f is not None]
            ready = select.select(fds, [], [], timeout)[0]
            # Off a deadline, not the select timeout: touches on the disabled
            # touchscreen keep the tap fd readable.
            if down is None and not (last_on and not lid_closed) and time.monotonic() >= poll_at:
                poll_at = time.monotonic() + 1.0
                if screen_on():
                    if lid_closed and not power_on_while_closed:
                        set_screen(False)              # a key under the cover woke it
                    elif not last_on:
                        set_screen(True)               # woken by another input
            if not ready:
                if down is not None:
                    down = None; menu()                # held long enough
                continue
            if tap is not None and tap in ready:
                try:
                    data = os.read(tap, SZ * 64)
                except BlockingIOError:
                    data = b""
                for i in range(0, len(data) - SZ + 1, SZ):
                    _, _, t, c, v = struct.unpack(FMT, data[i:i + SZ])
                    if t == EV_KEY and c == KEY_WAKEUP and v == 1 and not lid_closed and not last_on:
                        print("double tap", flush=True)
                        set_screen(True)
                if fd not in ready and lid not in ready:
                    continue
            if lid is not None and lid in ready:
                e = os.read(lid, SZ)
                _, _, t, c, v = struct.unpack(FMT, e)
                if t == EV_SW and c == SW_LID and bool(v) != lid_closed:
                    lid_closed = bool(v); power_on_while_closed = False
                    print("cover", "closed" if lid_closed else "opened", flush=True)
                    arm_tap(not lid_closed)
                    if lid_closed and not screen_on():
                        # The driver takes the mode only when the panel goes
                        # off: an armed, dark panel needs one more off.
                        set_screen(True); time.sleep(1)
                    set_screen(not lid_closed)
            if fd not in ready:
                continue
            e = os.read(fd, SZ)
            if len(e) < SZ:
                return
            _, _, t, c, v = struct.unpack(FMT, e)
            if t != EV_KEY or c != KEY_POWER:
                continue
            if v == 1:
                down = time.monotonic()
            elif v == 0 and down is not None:
                down = None
                on = not screen_on()
                power_on_while_closed = lid_closed and on
                set_screen(on)
    finally:
        for f in (fd, lid, tap):
            if f is not None:
                os.close(f)

while True:
    dev = find()
    if not dev:
        time.sleep(2); continue
    try:
        run(dev)
    except Exception as exc:
        print("error:", exc, flush=True); time.sleep(1)
