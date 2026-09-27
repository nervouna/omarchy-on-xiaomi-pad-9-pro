#!/usr/bin/env python3
"""Xiaomi pogo keyboard: link keep-alive, cover handling, backlight.

The keyboard is relayed by the ADSP (sensor PD, needs sscrpcd) to the
xiaomi_keyboard driver over QMI; commands go through /dev/nanodev0.
IMPORTANT: the driver forwards a write to the keyboard only if it is at least
66 bytes long (chardev_fops_write: count >= 0x42); shorter writes are just
logged ("write cmd -> ...") and dropped. Packets are padded to 66 bytes.
Packet: 32 00 4E 31|30 80 38|18 CMD LEN DATA CHK, CHK = sum(bytes[2:]) & 0xFF.
Commands (captured from stock Android, reference/logcat-*-excerpt.txt):
  A1 01 01  MCU status request        hub 01 01 00  enable keyboard(18)/touchpad(38)
  21 01 00  touchpad reporting off    21 01 01      touchpad reporting on
  23 01 N   backlight level 0..100
Behaviour:
  - (re)enable when the driver reports Connected=[0] (boot, reattach);
  - cover closed (xiaomi-hall SW_LID) or screen off: touchpad off + backlight
    off, so the folded keyboard can't stream packets that wake s2idle;
  - backlight: `loa-kbd-backlight auto|on [N]|off` (/var/lib/loa/kbd-backlight);
    auto = on while typing in dim light (< DIM_LUX, lux from loa-autobrightness
    via /run/loa-lux), off after IDLE s without keyboard/touchpad activity.
"""
import fcntl, glob, os, select, struct, time, array

STATUS = "/sys/devices/virtual/keyboard/keypad/version"
DEV = "/dev/nanodev0"
DPMS = "/sys/class/drm/card0-DSI-1/dpms"
LUX = "/run/loa-lux"
CONF = "/var/lib/loa/kbd-backlight"
RETRY, IDLE, DIM_LUX, DEFAULT_LEVEL = 5.0, 30.0, 50.0, 60
EV_KEY, EV_SW, SW_LID = 1, 5, 0
EVIOCGSW = 0x8008451b
FMT = "llHHi"; SZ = struct.calcsize(FMT)

def pkt(cmd, data, target=0x31, sub=0x38, kind=0x4E):
    b = bytearray([0x32, 0x00, kind, target, 0x80, sub, cmd, len(data)]) + bytes(data)
    b.append(sum(b[2:]) & 0xFF)
    return bytes(b) + bytes(66 - len(b))

ENABLE = [pkt(0xA1, [1]), pkt(0x01, [0], target=0x30, sub=0x18), pkt(0x01, [0], target=0x30, sub=0x38)]

def send(*packets):
    fd = os.open(DEV, os.O_RDWR)
    try:
        for p in packets:
            os.write(fd, p)
            time.sleep(0.05)
    finally:
        os.close(fd)

def rd(path, default=""):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return default

def connected():
    return "Connected=[1]" in rd(STATUS)

def find(name):
    for d in glob.glob("/sys/class/input/event*"):
        if rd(d + "/device/name") == name:
            return "/dev/input/" + os.path.basename(d)

def lid_closed(fd):
    buf = array.array("B", [0] * 8)
    fcntl.ioctl(fd, EVIOCGSW, buf)
    return bool(buf[0] & 1)

def conf():
    """-> ('auto'|'on'|'off', level)"""
    w = (rd(CONF) or "auto").split()
    mode = w[0] if w and w[0] in ("auto", "on", "off") else "auto"
    try:
        level = max(0, min(100, int(w[1]))) if len(w) > 1 else DEFAULT_LEVEL
    except ValueError:
        level = DEFAULT_LEVEL
    return mode, level

# The driver logs ~8 kernel lines per touchpad packet at its default level 5.
try:
    open("/sys/devices/virtual/keyboard/keypad/debug_level", "w").write("0")
except OSError as e:
    print("debug_level:", e, flush=True)

def open_inputs():
    """Non-grabbing readers: activity (keyboard, touchpad) and the lid switch."""
    fds = {}
    for name in ("Xiaomi Keyboard", "Xiaomi Touch", "Xiaomi Consumer", "xiaomi-hall"):
        p = find(name)
        if p:
            try:
                fds[os.open(p, os.O_RDONLY | os.O_NONBLOCK)] = name
            except OSError:
                pass
    return fds

def main():
    if not os.path.exists(CONF):                      # user-writable setting file
        os.makedirs(os.path.dirname(CONF), exist_ok=True)
        with open(CONF, "w") as f:
            f.write("auto %d\n" % DEFAULT_LEVEL)
    os.chmod(CONF, 0o666)
    fds = open_inputs()
    hall = next((fd for fd, n in fds.items() if n == "xiaomi-hall"), None)
    closed = lid_closed(hall) if hall is not None else False
    was_conn, last_try = None, 0.0
    last_act = time.monotonic()
    folded = None          # touchpad-off state we last sent
    light = None           # backlight level we last sent
    while True:
        r, _, _ = select.select(list(fds), [], [], 0.5)
        for fd in r:
            try:
                data = os.read(fd, SZ * 64)
            except (BlockingIOError, OSError):
                continue
            for i in range(0, len(data) - SZ + 1, SZ):
                _, _, t, c, v = struct.unpack_from(FMT, data, i)
                if fds[fd] == "xiaomi-hall":
                    if t == EV_SW and c == SW_LID:
                        closed = bool(v)
                elif t == EV_KEY or t == 3:                 # key or touchpad motion
                    last_act = time.monotonic()

        conn = connected()
        if conn != was_conn:
            print("keyboard", "connected" if conn else "not connected", flush=True)
            was_conn = conn
            folded, light = None, None                      # resync after (re)connect
        if not conn:
            if time.monotonic() - last_try > RETRY:
                last_try = time.monotonic()
                try:
                    send(*ENABLE)
                except OSError as e:
                    print("send failed:", e, flush=True)
            continue

        screen = rd(DPMS, "On") == "On"
        want_folded = closed or not screen
        if want_folded != folded:
            try:
                send(pkt(0x21, [0 if want_folded else 1]))
                print("touchpad", "off (cover closed / screen off)" if want_folded else "on", flush=True)
                folded = want_folded
            except OSError as e:
                print("send failed:", e, flush=True)

        mode, level = conf()
        if want_folded or mode == "off":
            want = 0
        elif mode == "on":
            want = level
        else:
            try:
                lux = float(rd(LUX, "1000"))
            except ValueError:
                lux = 1000.0
            active = time.monotonic() - last_act < IDLE
            want = level if (active and lux < DIM_LUX) else 0
        if want != light:
            try:
                send(pkt(0x23, [want]))
                light = want
            except OSError as e:
                print("send failed:", e, flush=True)

if __name__ == "__main__":
    main()
