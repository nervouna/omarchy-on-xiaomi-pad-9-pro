#!/usr/bin/env python3
"""Screen auto-brightness from the SSC ambient light sensor (stk3bcx).

- Lux (loa_ssc, ambient_light, on-change reports) -> backlight via a log curve.
- Smoothed (EMA on log10 lux) and faded, so small light changes don't flicker.
- Manual changes win: if the backlight value differs from what we last wrote
  (brightness keys / Omarchy OSD / brightnessctl), the ratio becomes a user bias
  applied to the whole curve (persisted in /var/lib/loa/autobrightness.json).
- Never writes while the panel is off (DRM connector dpms != On).
- Disable temporarily: `touch /run/loa-autobrightness-off` (or stop the unit).
"""
import json, math, os, sys, time
sys.path.insert(0, "/usr/lib/loa")
from loa_ssc import GLib, SSC, SUID_UID, MSG_SUID_RESP, MSG_MEASUREMENT, parse_suid_response, floats_field1

BL = "/sys/class/backlight/panel0-backlight"
DPMS = "/sys/class/drm/card0-DSI-1/dpms"
STATE = "/var/lib/loa/autobrightness.json"
OFF_FLAG = "/run/loa-autobrightness-off"
MAX = int(open(BL + "/max_brightness").read())
# (lux, fraction of max): roughly Android's default curve, a bit darker at night.
CURVE = [(0, 0.012), (3, 0.03), (10, 0.06), (30, 0.10), (100, 0.18),
         (300, 0.30), (1000, 0.50), (3000, 0.75), (10000, 1.0)]
MIN_RAW = 20

def curve(lux):
    lux = max(lux, 0.0)
    if lux <= CURVE[0][0]:
        return CURVE[0][1]
    for (l0, f0), (l1, f1) in zip(CURVE, CURVE[1:]):
        if lux <= l1:
            a, b = math.log10(l0 + 1), math.log10(l1 + 1)
            t = (math.log10(lux + 1) - a) / (b - a)
            return f0 + t * (f1 - f0)
    return CURVE[-1][1]

def read_bl():
    return int(open(BL + "/brightness").read())

def write_bl(v):
    with open(BL + "/brightness", "w") as f:
        f.write(str(v))

def panel_on():
    try:
        return open(DPMS).read().strip() == "On"
    except OSError:
        return True

try:
    bias = float(json.load(open(STATE)).get("bias", 1.0))
except Exception:
    bias = 1.0
state = {"loglux": None, "written": None, "target": None}

def save_bias():
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    json.dump({"bias": bias}, open(STATE, "w"))

def target_raw():
    lux = 10 ** state["loglux"] - 1
    return max(MIN_RAW, min(MAX, int(round(curve(lux) * bias * MAX))))

def step():
    """Fade toward the target a little every 100 ms; detect manual changes."""
    global bias
    if state["loglux"] is None or os.path.exists(OFF_FLAG) or not panel_on():
        state["written"] = None          # re-sync once we are allowed to write again
        return True
    cur = read_bl()
    if state["written"] is not None and abs(cur - state["written"]) > 2:
        # Someone else changed the brightness: learn it as a bias on the curve.
        lux = 10 ** state["loglux"] - 1
        base = max(curve(lux) * MAX, 1)
        bias = min(8.0, max(0.125, cur / base))
        save_bias()
        print("manual brightness %d at %.0f lux -> bias %.2f" % (cur, lux, bias), flush=True)
        state["written"] = cur
        return True
    tgt = target_raw()
    if state["written"] is None:
        state["written"] = cur
    if abs(tgt - cur) <= max(2, cur // 50):
        return True
    nxt = cur + max(1, abs(tgt - cur) // 6) * (1 if tgt > cur else -1)
    write_bl(nxt)
    state["written"] = nxt
    return True

def on_event(uid, msg_id, ts, msg):
    if uid == SUID_UID and msg_id == MSG_SUID_RESP:
        dtype, uids = parse_suid_response(msg)
        if uids:
            names[uids[0]] = dtype
            ssc.enable(uids[0])                      # on-change reports
            print("ambient light sensor %016x%016x" % (uids[0][1], uids[0][0]), flush=True)
    elif msg_id == MSG_MEASUREMENT and names.get(uid) == "ambient_light":
        v = floats_field1(msg)
        if not v:
            return
        ll = math.log10(max(v[0], 0.0) + 1)
        state["loglux"] = ll if state["loglux"] is None else 0.8 * state["loglux"] + 0.2 * ll
        try:                                         # shared with loa-keyboard (backlight)
            with open("/run/loa-lux.tmp", "w") as f:
                f.write("%.1f\n" % (10 ** state["loglux"] - 1))
            os.replace("/run/loa-lux.tmp", "/run/loa-lux")
        except OSError:
            pass

names = {}
loop = GLib.MainLoop()
ssc = SSC(loop, on_event, lambda s: s.lookup("ambient_light"))
GLib.timeout_add(100, step)
print("auto-brightness: max %d, bias %.2f" % (MAX, bias), flush=True)
loop.run()
