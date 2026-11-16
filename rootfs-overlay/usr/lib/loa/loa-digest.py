#!/usr/bin/env python3
"""LoA usage digest: what the tablet did in a period, as JSON and a short text.

    loa-digest.py                          digest of the last 24 h (loa-digest.timer)
    loa-digest.py --since T [--until T]    digest of a chosen period (T: 2026-11-15,
                                           "2026-11-15 06:00" or @epoch; local time)
    loa-digest.py --sample                 append one sample line (loa-digest-sample.timer)

Writes /var/lib/loa-digest/<date>.json and <date>.txt, <date> being the day the
period ends in, and deletes digests and samples older than RETAIN_DAYS. The
battery split and the thermal figures come from the samples (one line a minute
in samples/<date>.jsonl, gzipped once the day is over); the rest comes from the
journal. A section whose source is missing is null, with the reason under
"reasons".

Never reads /sys/kernel/debug/qcom_cpuss_sleep_stats: a read hung a core (#60).
No window titles, command lines, file names under /home, URLs, SSIDs, MAC or IP
addresses, serial numbers or typed text: every journal string goes through
scrub() before it reaches the output.
"""
import argparse
import collections
import datetime
import glob
import gzip
import json
import os
import re
import subprocess
import sys
import time

DIR = "/var/lib/loa-digest"
RETAIN_DAYS = 35
TOP_ERRORS = 30
PS = "/sys/class/power_supply"
DPMS = "/sys/class/drm/card0-DSI-1/dpms"
UPDATE_VERSION = "/var/lib/loa-update/version"
BUILD_PACKAGES = "/var/lib/loa-build-packages.txt"   # written by the image build
UNIT_RESULT_ID = "d9b373ed55a64feb8242e02dbe79a49c"  # "<unit>: Failed with result ..."
DOCUMENTED_SIGN = 1      # battery/current_now > 0 means discharging (docs/maintenance.md)
NOMINAL_GB = (4, 6, 8, 12, 16, 24, 32, 64)
MAX_SLEEP_S = 7 * 86400  # larger jumps are clock changes, not sleeps
MAX_AWAKE_GAP_S = 600    # longer awake gaps between samples: the sampler was not running


def rd(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return None


def num(path):
    try:
        return int(rd(path).split()[0])
    except (AttributeError, ValueError, IndexError):
        return None


# ---------------------------------------------------------------- privacy

_URL = re.compile(r"(?i)\b[a-z][a-z0-9+.-]*://\S+|\bwww\.\S+")
_HOME = re.compile(r"/home/\S*")
_SSID = re.compile(r"(?i)\b(e?ssid)\b.*")
_MAC = re.compile(r"(?i)(?<![0-9a-z*])[0-9a-f*]{2}(?:[:-][0-9a-f*]{2}){5}(?![0-9a-z*])")
_IP4 = re.compile(r"(?<![\d.])\d{1,3}(?:\.\d{1,3}){3}(?!\.?\d)")
_IP6 = re.compile(r"(?i)(?<![\w:])[0-9a-f]{0,4}(?::[0-9a-f]{0,4}){2,7}(?![\w:])")
_EMAIL = re.compile(r"(?i)[\w.+-]+@[\w-]+(?:\.[\w-]+)*\.[a-z]{2,}\b")
_SERIAL = re.compile(r"(?i)\bserial(?:no|_?number)?\b\s*[:=]?\s*\S+")


def _ip6(m):
    s = m.group(0)
    return "<ip>" if "::" in s or s.count(":") == 7 else s


def scrub(s):
    """Removes what must not leave the tablet from one string."""
    s = _URL.sub("<url>", s)
    s = _HOME.sub("/home/<path>", s)
    s = _SSID.sub(lambda m: m.group(1) + " <removed>", s)
    s = _MAC.sub("<mac>", s)
    s = _EMAIL.sub("<email>", s)
    s = _IP4.sub("<ip>", s)
    s = _IP6.sub(_ip6, s)
    s = _SERIAL.sub("serial <removed>", s)
    return s


def scrub_all(x):
    if isinstance(x, str):
        return scrub(x)
    if isinstance(x, list):
        return [scrub_all(v) for v in x]
    if isinstance(x, dict):
        return {scrub(k) if isinstance(k, str) else k: scrub_all(v) for k, v in x.items()}
    return x


# ---------------------------------------------------------------- journal

def text(v):
    """journalctl -o json gives MESSAGE as a string, a byte list or null."""
    if isinstance(v, list):
        return bytes(v).decode("utf-8", "replace")
    return v if isinstance(v, str) else ""


def journal(args, fields):
    r = subprocess.run(["journalctl", "--no-pager", "-q", "-o", "json",
                        "--output-fields=" + ",".join(fields), *args],
                       capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        raise RuntimeError("journalctl: " + (r.stderr.strip() or "exit %d" % r.returncode))
    out = []
    for line in r.stdout.splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            pass
    return out


def span(since, until):
    return ["--since", "@%d" % since, "--until", "@%d" % until]


# ---------------------------------------------------------------- errors

_PACKET = re.compile(r"\[xiaomi-keyboard\].*\b(rawdata_show|keyboard_ipc_loop|ipc_data_parse|indication_cb)\b")


def normalise(s):
    """One message -> its dedup key: private parts removed, numbers and addresses masked."""
    s = scrub(s)
    s = re.sub(r"(?i)\b0x[0-9a-f]+\b", "H", s)
    s = re.sub(r"(?i)\b(?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])[0-9a-f]{6,}\b", "H", s)
    s = re.sub(r"\d+", "N", s)
    return re.sub(r"\s+", " ", s).strip()[:200]


def errors_section(kernel_lines, failed_messages):
    """kernel_lines: MESSAGE texts at priority err and above; failed_messages: failed-unit texts."""
    raw = collections.Counter()
    dropped = 0
    for line in kernel_lines:
        if _PACKET.search(line):
            dropped += 1
            continue
        raw[re.sub(r"\d", "0", line)] += 1   # cheap first pass; digit by digit keeps addresses detectable
    for line in failed_messages:
        raw[re.sub(r"\d", "0", line)] += 1
    keys = collections.Counter()
    for line, n in raw.items():
        keys[normalise(line)] += n
    keys.pop("", None)
    return {
        "kernel_messages": len(kernel_lines) - dropped,
        "failed_unit_messages": len(failed_messages),
        "touchpad_lines_dropped": dropped,
        "distinct": len(keys),
        "top": [{"count": n, "message": m} for m, n in keys.most_common(TOP_ERRORS)],
    }


# ---------------------------------------------------------------- suspend

_RESUMED = re.compile(r"^resumed: wake irq (\S+), fired: (.*?)(?:, battery \S+)?$")
_REFUSED = re.compile(r"^suspend refused \(([^)]*)\): failed dev (.*) at (\S*)$")
_FIRED = re.compile(r"(.+?)\+(\d+)(?:, |$)")


def wake_sources(fired):
    if fired.strip() in ("", "-"):
        return []
    return [m.group(1) for m in _FIRED.finditer(fired)]


def suspend_section(entries, mode=None):
    """entries: loa-sleepd journal records (MESSAGE, _BOOT_ID, __REALTIME_TIMESTAMP,
    __MONOTONIC_TIMESTAMP) in time order. The monotonic clock stops in s2idle and the
    real-time clock does not, so the step of their difference at a "resumed:" line is
    the time asleep in the suspend that line closes."""
    cycles, asleep = 0, 0.0
    refused, wakes, irqs = collections.Counter(), collections.Counter(), collections.Counter()
    last_off = {}
    for e in entries:
        msg = text(e.get("MESSAGE"))
        boot = e.get("_BOOT_ID")
        try:
            off = int(e["__REALTIME_TIMESTAMP"]) / 1e6 - int(e["__MONOTONIC_TIMESTAMP"]) / 1e6
        except (KeyError, ValueError):
            off = None
        m = _RESUMED.match(msg)
        if m:
            cycles += 1
            irqs[m.group(1)] += 1
            for w in wake_sources(m.group(2)):
                wakes[w] += 1
            if off is not None and boot in last_off:
                step = off - last_off[boot]
                if 0 < step < MAX_SLEEP_S:
                    asleep += step
        else:
            m = _REFUSED.match(msg)
            if m:
                refused[(m.group(2), m.group(3))] += 1
        if off is not None:
            last_off[boot] = off
    return {
        "mode": mode,
        "cycles": cycles,
        "asleep_h": round(asleep / 3600, 2),
        "refused": [{"device": d, "step": s, "count": n} for (d, s), n in refused.most_common()],
        "wake_sources": dict(wakes.most_common()),
        "wake_irqs": dict(irqs.most_common()),
    }


# ---------------------------------------------------------------- samples

def take_sample():
    def mili(path, div=1000):
        v = num(path)
        return None if v is None else round(v / div)

    s = {"t": round(time.time()), "b": (rd("/proc/sys/kernel/random/boot_id") or "")[:8],
         "sl": round(max(0.0, time.clock_gettime(time.CLOCK_BOOTTIME) - time.clock_gettime(time.CLOCK_MONOTONIC)), 1),
         "c": num(f"{PS}/battery/capacity"), "q": mili(f"{PS}/battery/charge_counter"),
         "i": mili(f"{PS}/battery/current_now"), "v": mili(f"{PS}/battery/voltage_now"),
         "u": num(f"{PS}/usb/online"), "ui": mili(f"{PS}/usb/current_now"),
         "uv": mili(f"{PS}/usb/voltage_now"), "s": 1 if rd(DPMS) == "On" else 0}
    cpu = None
    for z in glob.glob("/sys/class/thermal/thermal_zone*"):
        typ = rd(f"{z}/type") or ""
        # cpu-hw-trip-* report the trip threshold, not a temperature.
        if typ.startswith("cpu-") and not typ.startswith("cpu-hw-trip"):
            t = num(f"{z}/temp")
            if t is not None and (cpu is None or t > cpu):
                cpu = t
        elif typ == "quiet_therm":
            t = num(f"{z}/temp")
            s["qt"] = None if t is None else round(t / 1000, 1)
    s["cpu"] = None if cpu is None else round(cpu / 1000, 1)
    cd = []
    for c in glob.glob("/sys/class/thermal/cooling_device*"):
        typ = rd(f"{c}/type") or ""
        # The backlight's cooling device reads its brightness level, not a throttle.
        if "backlight" not in typ and (num(f"{c}/cur_state") or 0) > 0:
            cd.append(typ)
    if cd:
        s["cd"] = sorted(cd)
    return s


def day(ts):
    return time.strftime("%Y-%m-%d", time.localtime(ts))


def write_sample(d):
    os.makedirs(f"{d}/samples", exist_ok=True)
    s = take_sample()
    with open(f"{d}/samples/{day(s['t'])}.jsonl", "a") as f:
        f.write(json.dumps(s, separators=(",", ":")) + "\n")


def load_samples(d, since, until):
    out = []
    first, last = day(since - 86400), day(until + 86400)
    for p in sorted(glob.glob(f"{d}/samples/*.jsonl*")):
        name = os.path.basename(p)[:10]
        if not first <= name <= last:
            continue
        try:
            opener = gzip.open if p.endswith(".gz") else open
            with opener(p, "rt") as f:
                for line in f:
                    try:
                        s = json.loads(line)
                    except ValueError:
                        continue
                    if since <= s.get("t", 0) < until:
                        out.append(s)
        except (OSError, EOFError):
            continue
    out.sort(key=lambda s: s["t"])
    return out


def pairs(samples):
    """Consecutive samples of one boot, with the interval and the time asleep in it."""
    for a, b in zip(samples, samples[1:]):
        dt = b["t"] - a["t"]
        if a.get("b") != b.get("b") or dt <= 0:
            continue
        dsl = (b.get("sl") or 0) - (a.get("sl") or 0)
        if dsl < 0 or dt - dsl > MAX_AWAKE_GAP_S:
            continue
        yield a, b, dt, min(dsl, dt)


def current_sign(samples):
    """+1 when a positive battery current goes with a falling charge counter."""
    s = 0
    for a, b, _, _ in pairs(samples):
        if a.get("i") is not None and a.get("q") is not None and b.get("q") is not None:
            s += a["i"] * (b["q"] - a["q"])
    if s < 0:
        return 1, "measured"
    if s > 0:
        return -1, "measured"
    return DOCUMENTED_SIGN, "documented"


def battery_section(samples, charge_full_mah):
    caps = [s["c"] for s in samples if s.get("c") is not None]
    if not caps:
        return None, "no samples with a battery reading in the period"
    sign, sign_src = current_sign(samples)
    buckets = {k: [0.0, 0.0] for k in ("screen_on", "screen_off_awake", "s2idle")}  # hours, %
    on_batt = 0.0
    for a, b, dt, dsl in pairs(samples):
        if a.get("u") != 0 or b.get("u") != 0:
            continue
        on_batt += dt
        if dsl > dt / 2:
            k = "s2idle"
        elif a.get("s") == 1 and b.get("s") == 1:
            k = "screen_on"
        elif a.get("s") == 0 and b.get("s") == 0:
            k = "screen_off_awake"
        else:
            continue
        if charge_full_mah and a.get("q") is not None and b.get("q") is not None:
            pct = 100.0 * (a["q"] - b["q"]) / charge_full_mah
        elif a.get("c") is not None and b.get("c") is not None:
            pct = float(a["c"] - b["c"])
        else:
            continue
        buckets[k][0] += dt / 3600
        buckets[k][1] += pct
    drain, why = {}, {}
    for k, (h, pct) in buckets.items():
        if h >= 0.25:
            drain[k] = round(pct / h, 2)
        else:
            drain[k] = None
            why[k] = "%.0f min on battery in this state (needs 15)" % (h * 60)
    charge_w = [-sign * s["i"] * s["v"] / 1e6 for s in samples
                if s.get("i") is not None and s.get("v") is not None]
    input_w = [s["ui"] * s["uv"] / 1e6 for s in samples
               if s.get("u") == 1 and s.get("ui") is not None and s.get("uv") is not None]
    peak = max(charge_w, default=0)
    return {
        "samples": len(samples),
        "start_pct": caps[0], "end_pct": caps[-1], "min_pct": min(caps), "max_pct": max(caps),
        "hours_on_battery": round(on_batt / 3600, 2),
        "drain_pct_per_h": drain,
        "drain_null_reasons": why,
        "peak_charge_w": round(peak, 1) if peak > 0 else None,
        "peak_input_w": round(max(input_w), 1) if input_w else None,
        "current_sign": sign_src,
    }, None


def p95(vals):
    v = sorted(vals)
    return v[int(round(0.95 * (len(v) - 1)))]


def thermal_section(samples):
    cpu = [s["cpu"] for s in samples if s.get("cpu") is not None]
    qt = [s["qt"] for s in samples if s.get("qt") is not None]
    if not cpu and not qt:
        return None, "no samples with a temperature in the period"
    cool = collections.Counter()
    active = 0
    for s in samples:
        if s.get("cd"):
            active += 1
            cool.update(s["cd"])
    return {
        "samples": len(samples),
        "cpu_peak_c": max(cpu) if cpu else None, "cpu_p95_c": p95(cpu) if cpu else None,
        "quiet_therm_peak_c": max(qt) if qt else None, "quiet_therm_p95_c": p95(qt) if qt else None,
        "samples_cooling_active": active,
        "cooling_devices": dict(cool.most_common()),
    }, None


# ---------------------------------------------------------------- crashes

def hyprland_restarts(starts, since):
    """starts: (boot, time) of every "Welcome to Hyprland!" since the start of the
    earliest boot in the period. A start in the period is a restart unless it is
    the first one of its boot."""
    first, n = {}, 0
    for boot, t in sorted(starts, key=lambda x: x[1]):
        if boot in first and t >= since:
            n += 1
        first.setdefault(boot, t)
    return n


def crashes_section(coredump_exes, failed_units, hypr_restarts, failed_now):
    return {
        "coredumps": dict(collections.Counter(os.path.basename(e or "?") for e in coredump_exes).most_common()),
        "failed_units": dict(collections.Counter(failed_units).most_common()),
        "failed_now": failed_now,
        "hyprland_restarts": hypr_restarts,
    }


# ---------------------------------------------------------------- versions

def nominal_gb(mem_kb):
    gib = mem_kb / 1048576
    return next((n for n in NOMINAL_GB if gib <= n), round(gib))


def boots(since, until):
    r = subprocess.run(["journalctl", "--list-boots", "-o", "json", "--no-pager"],
                       capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise RuntimeError("journalctl --list-boots: " + r.stderr.strip())
    all_boots = json.loads(r.stdout or "[]")
    overlap = [b for b in all_boots if b["first_entry"] / 1e6 < until and b["last_entry"] / 1e6 >= since]
    return overlap, sum(1 for b in all_boots if since <= b["first_entry"] / 1e6 < until)


def versions_section(n_boots):
    mem_kb = int((rd("/proc/meminfo") or "x 0").split()[1])
    r = subprocess.run(["pacman", "-Q", "omarchy"], capture_output=True, text=True)
    built = os.path.getmtime(BUILD_PACKAGES) if os.path.exists(BUILD_PACKAGES) else None
    return {
        "kernel": os.uname().release,
        "omarchy": r.stdout.split()[1] if r.returncode == 0 and len(r.stdout.split()) > 1 else None,
        "loa_update": rd(UPDATE_VERSION),
        "image_build": day(built) if built else None,
        "ram_gb": nominal_gb(mem_kb),
        "mem_total_mib": mem_kb // 1024,
        "uptime_h": round(float((rd("/proc/uptime") or "0").split()[0]) / 3600, 1),
        "boots_in_period": n_boots,
    }


# ---------------------------------------------------------------- digest

def section(d, name, fn):
    try:
        val, why = fn()
    except Exception as e:  # a missing tool or file must not cost the other sections
        val, why = None, "%s: %s" % (type(e).__name__, e)
    d[name] = val
    if val is None:
        d["reasons"][name] = why


def build(since, until, sdir):
    d = {"digest": 1, "since": since, "until": until,
         "period": "%s -> %s" % (time.strftime("%Y-%m-%d %H:%M", time.localtime(since)),
                                 time.strftime("%Y-%m-%d %H:%M %Z", time.localtime(until))),
         "reasons": {}}
    samples = load_samples(sdir, since, until)
    bl = []

    def versions():
        b, n = boots(since, until)
        bl.extend(b)
        return versions_section(n), None

    def battery():
        full = num(f"{PS}/battery/charge_full")
        return battery_section(samples, full / 1000 if full else None)

    def suspend():
        e = journal(["-u", "loa-sleepd", *span(since, until)],
                    ["MESSAGE", "_BOOT_ID", "__REALTIME_TIMESTAMP", "__MONOTONIC_TIMESTAMP"])
        m = re.search(r"\[(\w+)\]", rd("/sys/power/mem_sleep") or "")
        return suspend_section(e, m.group(1) if m else None), None

    failed = []

    def failed_records():
        if not failed:
            failed.append(journal(["MESSAGE_ID=" + UNIT_RESULT_ID, *span(since, until)],
                                  ["MESSAGE", "UNIT", "USER_UNIT"]))
        return failed[0]

    def errors():
        r = subprocess.run(["journalctl", "--no-pager", "-q", "-o", "cat", "_TRANSPORT=kernel",
                            "-p", "err", *span(since, until)],
                           capture_output=True, text=True, errors="replace", timeout=120)
        if r.returncode != 0:
            raise RuntimeError("journalctl: " + r.stderr.strip())
        f = failed_records()
        return errors_section(r.stdout.splitlines(), [text(x.get("MESSAGE")) for x in f]), None

    def crashes():
        r = subprocess.run(["coredumpctl", "list", "--json=short", "--no-pager", *span(since, until)],
                           capture_output=True, text=True, timeout=60)
        if r.returncode != 0 and "No coredumps found" not in r.stderr:
            raise RuntimeError("coredumpctl: " + r.stderr.strip())
        exes = [c.get("exe") for c in json.loads(r.stdout)] if r.stdout.strip() else []
        units = [x.get("UNIT") or x.get("USER_UNIT") or "?" for x in failed_records()]
        start = min([b["first_entry"] / 1e6 for b in bl] + [since])
        h = journal(["_COMM=Hyprland", "MESSAGE=Welcome to Hyprland!", *span(start, until)],
                    ["_BOOT_ID", "__REALTIME_TIMESTAMP"])
        starts = [(x.get("_BOOT_ID"), int(x["__REALTIME_TIMESTAMP"]) / 1e6) for x in h]
        fr = subprocess.run(["systemctl", "--failed", "--plain", "--no-legend"],
                            capture_output=True, text=True, timeout=30)
        now = [l.split()[0] for l in fr.stdout.splitlines() if l.strip()] if until >= time.time() - 300 else None
        return crashes_section(exes, units, hyprland_restarts(starts, since), now), None

    section(d, "versions", versions)
    section(d, "battery", battery)
    section(d, "thermals", lambda: thermal_section(samples))
    section(d, "suspend", suspend)
    section(d, "errors", errors)
    section(d, "crashes", crashes)
    return scrub_all(d)


def render(d):
    def null(k):
        return "%-9s null: %s" % (k, d["reasons"].get(k, "?"))

    def f(v, unit=""):
        return "-" if v is None else "%s%s" % (v, unit)

    out = ["LoA usage digest, " + d["period"]]
    v = d.get("versions")
    out.append(null("versions") if v is None else
               "versions  kernel %s, omarchy %s, update %s, image %s, %s GB, up %s h, %s boot(s)" % (
                   v["kernel"], f(v["omarchy"]), f(v["loa_update"]), f(v["image_build"]),
                   v["ram_gb"], v["uptime_h"], v["boots_in_period"]))
    b = d.get("battery")
    if b is None:
        out.append(null("battery"))
    else:
        dr = b["drain_pct_per_h"]
        out.append("battery   %s%% -> %s%% (min %s, max %s), %s h on battery, peak charge %s (input %s)" % (
            b["start_pct"], b["end_pct"], b["min_pct"], b["max_pct"], b["hours_on_battery"],
            f(b["peak_charge_w"], " W"), f(b["peak_input_w"], " W")))
        out.append("          drain %%/h: screen on %s, screen off awake %s, s2idle %s" % (
            f(dr["screen_on"]), f(dr["screen_off_awake"]), f(dr["s2idle"])))
    t = d.get("thermals")
    if t is None:
        out.append(null("thermals"))
    else:
        cd = ", ".join("%s %d" % kv for kv in t["cooling_devices"].items())
        out.append("thermals  CPU peak %s, p95 %s; quiet_therm peak %s, p95 %s; cooling active in %d of %d samples%s" % (
            f(t["cpu_peak_c"], " C"), f(t["cpu_p95_c"], " C"), f(t["quiet_therm_peak_c"], " C"),
            f(t["quiet_therm_p95_c"], " C"), t["samples_cooling_active"], t["samples"], " (%s)" % cd if cd else ""))
    s = d.get("suspend")
    if s is None:
        out.append(null("suspend"))
    else:
        ref = ", ".join("%s at %s x%d" % (r["device"], r["step"], r["count"]) for r in s["refused"]) or "none"
        wk = ", ".join("%s %d" % kv for kv in list(s["wake_sources"].items())[:6]) or "none"
        out.append("suspend   %s, %d cycle(s), %s h asleep; refused: %s" % (
            f(s["mode"]), s["cycles"], s["asleep_h"], ref))
        out.append("          wake sources: %s" % wk)
    e = d.get("errors")
    if e is None:
        out.append(null("errors"))
    else:
        out.append("errors    %d kernel message(s) at err or above, %d failed-unit message(s), %d distinct; top:" % (
            e["kernel_messages"], e["failed_unit_messages"], e["distinct"]))
        out.extend("  %7d  %s" % (x["count"], x["message"][:150]) for x in e["top"][:10])
    c = d.get("crashes")
    if c is None:
        out.append(null("crashes"))
    else:
        j = lambda m: ", ".join("%s x%d" % kv for kv in m.items()) or "none"
        out.append("crashes   coredumps: %s; failed units: %s; Hyprland restarts: %d%s" % (
            j(c["coredumps"]), j(c["failed_units"]), c["hyprland_restarts"],
            "; failed now: %s" % (", ".join(c["failed_now"]) or "none") if c["failed_now"] is not None else ""))
    return "\n".join(out) + "\n"


def atomic_write(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(data)
    os.replace(tmp, path)


def housekeeping(d, now):
    cutoff = day(now - RETAIN_DAYS * 86400)
    today = day(now)
    for p in glob.glob(f"{d}/*.json") + glob.glob(f"{d}/*.txt") + glob.glob(f"{d}/samples/*.jsonl*"):
        name = os.path.basename(p)[:10]
        if re.fullmatch(r"\d{4}-\d\d-\d\d", name) and name < cutoff:
            os.unlink(p)
    for p in glob.glob(f"{d}/samples/*.jsonl"):    # finished days: gzip
        if os.path.basename(p)[:10] < today:
            with open(p, "rb") as src, gzip.open(p + ".gz.tmp", "wb") as dst:
                dst.write(src.read())
            os.replace(p + ".gz.tmp", p + ".gz")
            os.unlink(p)


def parse_time(s):
    if s.startswith("@"):
        return float(s[1:])
    return datetime.datetime.fromisoformat(s).timestamp()   # naive = local time


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--sample", action="store_true", help="append one sample and exit")
    p.add_argument("--since", help="start of the period (default: 24 h before --until)")
    p.add_argument("--until", help="end of the period (default: now)")
    p.add_argument("--dir", default=DIR)
    a = p.parse_args()
    if a.sample:
        write_sample(a.dir)
        return
    now = time.time()
    until = parse_time(a.until) if a.until else now
    since = parse_time(a.since) if a.since else until - 86400
    if since >= until:
        sys.exit("--since must be before --until")
    os.makedirs(a.dir, exist_ok=True)
    d = build(since, until, a.dir)
    name = day(until - 1)
    atomic_write(f"{a.dir}/{name}.json", json.dumps(d, indent=1) + "\n")
    atomic_write(f"{a.dir}/{name}.txt", render(d))
    housekeeping(a.dir, now)
    print(f"{a.dir}/{name}.json")


if __name__ == "__main__":
    main()
