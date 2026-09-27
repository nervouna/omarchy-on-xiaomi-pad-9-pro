#!/usr/bin/env python3
"""Xiaomi Focus Pencil Pro (P81C) as a pointing device (NOTES / engineering log 2026-09-27).

How the pen works on this tablet (captured from stock Android):
  - Strokes come from the touch IC as the kernel device "NVTCapacitivePenP81c", but only
    while the pen is connected over Bluetooth LE (HID) and the touch driver has been
    told so through xiaomi_touch modes (Android's TouchFeature):
        connected:    20=24, 29=0, 22=1, 22=259, 29=0, 37=1, 29=1
        disconnected: 20=8, 37=0
  - Its two buttons arrive over Bluetooth as KEY_F19 / KEY_KPENTER on
    "Xiaomi Focus Pen Pro Keyboard".
  - Pairing: attaching the pen makes it advertise briefly; plain BLE Just Works pairing.

What this daemon does:
  - grabs the NVT pen devices (so libinput doesn't treat them as a tablet: Hyprland
    doesn't turn tablet tips into clicks) and re-emits a virtual ABSOLUTE MOUSE
    ("LoA Pen Pointer"): hover moves the cursor to the tip, tip contact = left button;
    after tip-down the cursor stays at the touch point until the tip has moved more
    than DRAG_PX, so the tiny slide of a landing pen doesn't turn a tap into a drag;
  - grabs the pen's Bluetooth "button" device (the Pro senses gestures, no buttons):
      double tap (KEY_KPENTER) = right click. Pinch (KEY_F19, held while squeezed) and
      swipe up/down (KEY_KP9/KEY_KP3) are swallowed for now: pinch-to-scroll and
      swipe-for-history were tried (2026-09-27) and dropped until the pen's
      accelerometer/gyro stream is understood;
    and grabs + discards its other Bluetooth HID devices: "Xiaomi Focus Pen Pro" sends
    KEY_KPPLUS repeatedly while the tip is down (typed "++++"), "... Mouse" is unused;
  - sends the touch modes above whenever the pen's Bluetooth HID appears / goes away;
  - pairs a newly attached, unknown pen: the wireless charger logs
    "POWER_SUPPLY_PEN_MAC=<12 hex>" to the kernel log every ~10 s while a pen is attached
    (not exposed in sysfs; wireless_master/tx_mac stays empty), so follow /dev/kmsg.
"""
import fcntl, os, re, select, struct, subprocess, time

XTOUCH = "/usr/lib/loa/loa-xtouch"
MODES_ON = [(20, 24), (29, 0), (22, 1), (22, 259), (29, 0), (37, 1), (29, 1)]
MODES_OFF = [(20, 8), (37, 0)]
PAIR_RETRY_S = 60              # at most one pairing attempt per pen per minute
KEY_DOUBLETAP = 96            # KP Enter (pinch F19 = 189, swipes KP9 = 73 / KP3 = 81: unused)
BTN_RIGHT = 0x111
DRAG_PX = 16                  # tip movement (panel px, ~1.3 mm) before a tap becomes a drag
PANEL_W, PANEL_H = 3200, 2136

EV_SYN, EV_KEY, EV_ABS = 0, 1, 3
ABS_X, ABS_Y = 0, 1
BTN_LEFT, BTN_TOUCH, BTN_TOOL_PEN = 0x110, 0x14a, 0x140
FMT = "llHHi"; SZ = struct.calcsize(FMT)
EVIOCGRAB = 0x40044590
def EVIOCGABS(a): return 0x80184540 + a
UI_SET_EVBIT, UI_SET_KEYBIT, UI_SET_ABSBIT, UI_SET_PROPBIT = 0x40045564, 0x40045565, 0x40045567, 0x4004556e
UI_DEV_CREATE = 0x5501
INPUT_PROP_POINTER = 0

def log(*a):
    print(*a, flush=True)

def name_of(ev):
    try:
        return open(f"/sys/class/input/{ev}/device/name").read().strip()
    except OSError:
        return ""

def instance(ev):
    """Kernel input instance ("input42"): unique per device creation, unlike eventN,
    which gets reused when a device is re-created (Bluetooth reconnect, touch driver
    re-init at boot) -- tracking eventN kept dead handles and missed the new device."""
    try:
        return os.path.basename(os.readlink(f"/sys/class/input/{ev}/device"))
    except OSError:
        return ""

def find(pred):
    return sorted(e for e in os.listdir("/sys/class/input") if e.startswith("event") and pred(name_of(e)))

def absmax(fd, axis):
    buf = bytearray(24)
    fcntl.ioctl(fd, EVIOCGABS(axis), buf)
    return struct.unpack("6i", buf)[2]

def xtouch(pairs):
    for m, v in pairs:
        subprocess.run([XTOUCH, "set", str(m), str(v)], capture_output=True)
        time.sleep(0.3)

class Pointer:
    """uinput absolute mouse in panel pixel coordinates."""
    def __init__(self):
        self.fd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
        fcntl.ioctl(self.fd, UI_SET_EVBIT, EV_KEY)
        fcntl.ioctl(self.fd, UI_SET_EVBIT, EV_ABS)
        for b in (BTN_LEFT, BTN_RIGHT):
            fcntl.ioctl(self.fd, UI_SET_KEYBIT, b)
        fcntl.ioctl(self.fd, UI_SET_ABSBIT, ABS_X)
        fcntl.ioctl(self.fd, UI_SET_ABSBIT, ABS_Y)
        fcntl.ioctl(self.fd, UI_SET_PROPBIT, INPUT_PROP_POINTER)
        absmax_ = [0] * 64; absmin = [0] * 64
        absmax_[ABS_X], absmax_[ABS_Y] = PANEL_W - 1, PANEL_H - 1
        # struct uinput_user_dev: name[80], input_id (4 x u16), ff_effects_max u32,
        # absmax[64], absmin[64], absfuzz[64], absflat[64] (s32)
        dev = struct.pack("80sHHHHI", b"LoA Pen Pointer", 0x06, 0x2717, 0x5042, 1, 0)
        dev += struct.pack("64i", *absmax_) + struct.pack("64i", *absmin) + bytes(4 * 64 * 2)
        os.write(self.fd, dev)
        fcntl.ioctl(self.fd, UI_DEV_CREATE)
        self.buttons = set()

    def click(self, code):
        self.button(code, True); self.button(code, False)

    def emit(self, events):
        data = b"".join(struct.pack(FMT, 0, 0, t, c, v) for t, c, v in events)
        os.write(self.fd, data + struct.pack(FMT, 0, 0, EV_SYN, 0, 0))

    def move(self, x, y):
        self.emit([(EV_ABS, ABS_X, x), (EV_ABS, ABS_Y, y)])

    def button(self, code, down):
        if down == (code in self.buttons):
            return
        (self.buttons.add if down else self.buttons.discard)(code)
        self.emit([(EV_KEY, code, 1 if down else 0)])

    def release_all(self):
        for b in list(self.buttons):
            self.button(b, False)

class PenDevice:
    """One grabbed NVT pen evdev; tracks raw X/Y and tip."""
    def __init__(self, ev):
        self.ev = ev
        self.inst = instance(ev)
        self.fd = os.open(f"/dev/input/{ev}", os.O_RDONLY | os.O_NONBLOCK)
        fcntl.ioctl(self.fd, EVIOCGRAB, 1)
        self.xmax, self.ymax = absmax(self.fd, ABS_X), absmax(self.fd, ABS_Y)
        self.x = self.y = None
        self.tip = False
        self.anchor, self.dragging = None, False     # tap-vs-drag state while the tip is down

    def screen(self):
        # Raw X spans the panel's short side, top = max; raw Y the long side, left = 0
        # (same layout as the touchscreen; Hyprland transform 3).
        sx = self.y * (PANEL_W - 1) // max(1, self.ymax)
        sy = (self.xmax - self.x) * (PANEL_H - 1) // max(1, self.xmax)
        return sx, sy

def paired(mac):
    out = subprocess.run(["bluetoothctl", "info", mac], capture_output=True, text=True).stdout
    return "Paired: yes" in out

def pair(mac):
    log("pairing new pen", mac)
    scan = subprocess.Popen(["bluetoothctl", "--timeout", "40", "scan", "le"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(40):
            if mac in subprocess.run(["bluetoothctl", "devices"], capture_output=True, text=True).stdout:
                break
            time.sleep(1)
        for cmd in (["--agent", "NoInputNoOutput", "--timeout", "20", "pair", mac], ["trust", mac],
                    ["--timeout", "15", "connect", mac]):
            r = subprocess.run(["bluetoothctl"] + cmd, capture_output=True, text=True)
            res = [l for l in r.stdout.splitlines() if re.search(r"successful|succeeded|Failed|Error|not available", l)]
            log("bluetoothctl", cmd[-2], "->", (res or ["no result"])[-1].strip()[:80])
    finally:
        scan.terminate()

def main():
    ptr = Pointer()
    pens = {}                 # fd -> PenDevice
    keys = None               # (fd, ev, instance) of the Bluetooth button device
    muted = {}                # fd -> (ev, instance) of grabbed-and-ignored Bluetooth HID devices
    kmsg = os.open("/dev/kmsg", os.O_RDONLY | os.O_NONBLOCK)
    os.lseek(kmsg, 0, os.SEEK_END)   # only new kernel messages
    tried = {}                # pen MAC -> monotonic time of the last pairing attempt
    connected = False
    last_scan = 0
    log("loa-pen: pointer ready")
    while True:
        now = time.monotonic()
        if now - last_scan > 2:
            last_scan = now
            resend = False
            for fd, p in list(pens.items()):
                if instance(p.ev) != p.inst:                   # gone or re-created
                    log("pen device changed", p.ev); pens.pop(fd); resend = True
                    try: os.close(fd)
                    except OSError: pass
            have = {p.ev for p in pens.values()}
            for ev in find(lambda n: n.startswith("NVTCapacitivePen")):
                if ev not in have:
                    try:
                        p = PenDevice(ev); pens[p.fd] = p; log("grabbed", ev, name_of(ev))
                    except OSError as e:
                        log("grab", ev, "failed:", e)
            bt = find(lambda n: n == "Xiaomi Focus Pen Pro Keyboard")
            if bt and connected and resend:
                log("pen devices re-created (touch driver re-init?) -> touch modes on again")
                xtouch(MODES_ON)
            resend = False
            if bt and not connected:
                connected = True
                log("pen connected over Bluetooth -> touch modes on")
                xtouch(MODES_ON)
            elif not bt and connected:
                connected = False
                log("pen disconnected -> touch modes off")
                xtouch(MODES_OFF)
                if keys:
                    try: os.close(keys[0])
                    except OSError: pass
                    keys = None
                ptr.release_all()
            # Silence the pen's other Bluetooth HID devices (KP+ flood while writing, unused mouse).
            for fd, (ev, inst) in list(muted.items()):
                if instance(ev) != inst:
                    muted.pop(fd)
                    try: os.close(fd)
                    except OSError: pass
            for ev in find(lambda n: n in ("Xiaomi Focus Pen Pro", "Xiaomi Focus Pen Pro Mouse")):
                if ev not in [e for e, _ in muted.values()]:
                    try:
                        fd = os.open(f"/dev/input/{ev}", os.O_RDONLY | os.O_NONBLOCK)
                        fcntl.ioctl(fd, EVIOCGRAB, 1); muted[fd] = (ev, instance(ev)); log("muted", ev, name_of(ev))
                    except OSError as e:
                        log("mute", ev, "failed:", e)
            if bt and (keys is None or keys[1] != bt[0] or keys[2] != instance(bt[0])):
                if keys:
                    try: os.close(keys[0])
                    except OSError: pass
                try:
                    fd = os.open(f"/dev/input/{bt[0]}", os.O_RDONLY | os.O_NONBLOCK)
                    fcntl.ioctl(fd, EVIOCGRAB, 1)
                    keys = (fd, bt[0], instance(bt[0])); log("grabbed pen buttons", bt[0])
                except OSError as e:
                    log("pen buttons", bt[0], "failed:", e)
        fds = list(pens) + list(muted) + ([keys[0]] if keys else []) + [kmsg]
        r, _, _ = select.select(fds, [], [], 1.0)
        if kmsg in r:
            # One record per read; drain everything that is pending.
            while True:
                try:
                    rec = os.read(kmsg, 8192).decode(errors="replace")
                except BlockingIOError:
                    break
                except OSError:          # EPIPE: records overwritten while we slept
                    continue
                m = re.search(r"POWER_SUPPLY_PEN_MAC=([0-9a-fA-F]{12})", rec)
                if m:
                    mac = ":".join(re.findall("..", m.group(1).upper()))
                    if time.monotonic() - tried.get(mac, -PAIR_RETRY_S) >= PAIR_RETRY_S:
                        tried[mac] = time.monotonic()
                        if not paired(mac):
                            pair(mac)
            r = [fd for fd in r if fd != kmsg]
        for fd in r:
            try:
                data = os.read(fd, SZ * 64)
            except OSError:
                if fd in pens:
                    log("pen device gone", pens.pop(fd).ev)
                elif fd in muted:
                    muted.pop(fd)
                elif keys and fd == keys[0]:
                    keys = None
                try: os.close(fd)
                except OSError: pass
                continue
            if fd in muted:
                continue
            for i in range(0, len(data) - SZ + 1, SZ):
                _, _, t, c, v = struct.unpack_from(FMT, data, i)
                if keys and fd == keys[0]:
                    if t != EV_KEY or v not in (0, 1):
                        continue
                    if v == 1 and c == KEY_DOUBLETAP:
                        ptr.click(BTN_RIGHT)
                    continue
                p = pens[fd]
                if t == EV_ABS and c == ABS_X:
                    p.x = v
                elif t == EV_ABS and c == ABS_Y:
                    p.y = v
                elif t == EV_KEY and c == BTN_TOUCH:
                    p.tip = v == 1
                elif t == EV_SYN and c == 0:
                    if p.x is None or p.y is None:
                        continue
                    sx, sy = p.screen()
                    if p.tip and p.anchor is None:
                        p.anchor, p.dragging = (sx, sy), False          # tip just landed
                    elif not p.tip:
                        p.anchor = None
                    if p.anchor is not None and not p.dragging:
                        if abs(sx - p.anchor[0]) + abs(sy - p.anchor[1]) > DRAG_PX:
                            p.dragging = True                            # a real drag
                        else:
                            sx, sy = p.anchor                            # hold the tap point
                    ptr.move(sx, sy)
                    ptr.button(BTN_LEFT, p.tip)

if __name__ == "__main__":
    main()
