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
DPMS became safe once the first frame after continuous splash stopped failing
(AQ_DRM_FORCE_MODE_ID, NOTES.md)."""
import fcntl, glob, json, os, select, struct, subprocess, time
KEY_POWER, EV_KEY = 116, 1
HOLD = 0.7
EVIOCGRAB = 0x40044590
TOUCH = "nvtcapacitivetouchscreen-1"
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

def screen_on():
    try:
        out = as_user("hyprctl", "monitors", "-j")
        return all(m.get("dpmsStatus", True) for m in json.loads(out))
    except Exception as exc:
        print("dpms query failed:", repr(exc), flush=True)
        return last_on

def set_screen(on):
    global last_on
    last_on = on
    lua = "true" if on else "false"
    act = "enable" if on else "disable"
    if on:
        as_user("hyprctl", "eval", f'hl.dispatch(hl.dsp.dpms({{ action = "{act}" }}))')
        as_user("hyprctl", "eval", f'hl.device({{ name = "{TOUCH}", enabled = {lua} }})')
    else:
        as_user("hyprctl", "eval", f'hl.device({{ name = "{TOUCH}", enabled = {lua} }})')
        as_user("hyprctl", "eval", f'hl.dispatch(hl.dsp.dpms({{ action = "{act}" }}))')
    print("screen", act, flush=True)

def menu():
    if not screen_on():
        set_screen(True)
    as_user("omarchy-menu", "toggle", "system", wait=False)
    print("system menu toggled", flush=True)

def run(dev):
    print("listening on", dev, flush=True)
    fd = os.open(dev, os.O_RDONLY)
    fcntl.ioctl(fd, EVIOCGRAB, 1)
    lid_dev = find("xiaomi-hall")      # keyboard cover magnet: SW_LID 1 = closed
    lid = os.open(lid_dev, os.O_RDONLY) if lid_dev else None
    lid_closed = lid_is_closed(lid) if lid is not None else False
    power_on_while_closed = False       # the user woke it with the power key on purpose
    print("lid", lid_dev, "closed" if lid_closed else "open", flush=True)
    try:
        down = None  # monotonic press time while the key is held and undecided
        while True:
            if down is not None:
                timeout = max(0.0, down + HOLD - time.monotonic())
            else:
                timeout = None if (last_on and not lid_closed) else 1.0
            fds = [fd] + ([lid] if lid is not None else [])
            ready = select.select(fds, [], [], timeout)[0]
            if not ready:
                if down is not None:
                    down = None; menu()                # held long enough
                elif screen_on():
                    if lid_closed and not power_on_while_closed:
                        set_screen(False)              # a key under the cover woke it
                    elif not last_on:
                        set_screen(True)               # woken by another input
                continue
            if lid is not None and lid in ready:
                e = os.read(lid, SZ)
                _, _, t, c, v = struct.unpack(FMT, e)
                if t == EV_SW and c == SW_LID and bool(v) != lid_closed:
                    lid_closed = bool(v); power_on_while_closed = False
                    print("cover", "closed" if lid_closed else "opened", flush=True)
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
        os.close(fd)
        if lid is not None:
            os.close(lid)

while True:
    dev = find()
    if not dev:
        time.sleep(2); continue
    try:
        run(dev)
    except Exception as exc:
        print("error:", exc, flush=True); time.sleep(1)
