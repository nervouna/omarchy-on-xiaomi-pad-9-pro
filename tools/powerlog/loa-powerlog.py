#!/usr/bin/env python3
"""Whole-device power logger for the tablet, and a report over its logs.

    loa-powerlog.py run [--out FILE] [--interval 60] [--sample 5]   (on the tablet, as root)
    loa-powerlog.py report FILE...                                  (anywhere)

`run` appends one JSON line per interval. Battery and charger readings are
averaged over the samples of the interval; everything else is a counter
delta over the interval. There is no per-rail power meter on this tablet, so
the breakdown is by activity: CPU frequency and idle residency, GPU clock
residency, SoC sleep statistics, backlight, temperatures, network bytes and
the busiest processes.

Whole-device power = USB input power - power going into the battery. The
sign of the fuel gauge's current is checked against its charge counter by
`report`, not assumed.
"""
import argparse
import glob
import json
import os
import re
import sys
import time

PS = "/sys/class/power_supply"
IIO = "/sys/bus/iio/devices/iio:device0"
KGSL = "/sys/class/kgsl/kgsl-3d0"
QSTATS = "/sys/kernel/debug/qcom_stats"
CPUSS = "/sys/kernel/debug/qcom_cpuss_sleep_stats"
EM = "/sys/kernel/debug/energy_model"
SUBSYS = ("apss", "cxsd", "aosd", "ddr", "adsp", "cdsp", "wpss", "modem")
ZONES = ("battery", "quiet_therm", "display_therm", "wifi_therm", "charger_therm0", "cpu_therm", "ddr")
ZONE_GROUPS = ("cpu-", "gpuss-")


def rd(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return None


def num(path):
    s = rd(path)
    try:
        return int(s.split()[0])
    except (AttributeError, ValueError, IndexError):
        return None


def instant():
    """Readings that are averaged over the samples of an interval."""
    return {
        "bat_ua": num(f"{PS}/battery/current_now"),
        "bat_uv": num(f"{PS}/battery/voltage_now"),
        "usb_ua": num(f"{PS}/usb/current_now"),
        "usb_uv": num(f"{PS}/usb/voltage_now"),
        "iin_ua": num(f"{IIO}/in_current_pm7550ba_iin_fb_input"),
        "ichg_ua": num(f"{IIO}/in_current_pm7550ba_ichg_fb_input"),
        "vph_uv": num(f"{IIO}/in_voltage_pm7550ba_vph_pwr_input"),
    }


def cpu_times():
    out = {}
    for line in (rd("/proc/stat") or "").splitlines():
        p = line.split()
        if p and re.fullmatch(r"cpu\d+", p[0]):
            v = [int(x) for x in p[1:9]]
            out[p[0]] = (sum(v), v[3] + v[4])  # total, idle + iowait
        elif p and p[0] in ("intr", "ctxt"):
            out[p[0]] = (int(p[1]), 0)
    return out


def kv_table(path):
    """'freq value' lines -> {freq: value}."""
    out = {}
    for line in (rd(path) or "").splitlines():
        p = line.split()
        if len(p) == 2 and p[0].isdigit() and p[1].isdigit():
            out[p[0]] = int(p[1])
    return out


def counters():
    c = {"cpu": cpu_times(), "freq": {}, "idle": {}, "soc": {}, "cpuss": {}, "net": {}, "proc": {}}
    for pol in glob.glob("/sys/devices/system/cpu/cpufreq/policy*"):
        c["freq"][os.path.basename(pol)] = kv_table(f"{pol}/stats/time_in_state")  # 10 ms units
    for st in glob.glob("/sys/devices/system/cpu/cpu[0-9]*/cpuidle/state*"):
        name = rd(f"{st}/name")
        c["idle"][name] = c["idle"].get(name, 0) + (num(f"{st}/time") or 0)  # us, summed over CPUs
    for s in SUBSYS:
        t = rd(f"{QSTATS}/{s}")
        if t:
            m = dict(re.findall(r"(Count|Accumulated Duration): (\d+)", t))
            c["soc"][s] = (int(m.get("Count", 0)), int(m.get("Accumulated Duration", 0)))
    for f in glob.glob(f"{CPUSS}/*/*"):
        v = num(f)
        if v is not None:
            c["cpuss"][f"{os.path.basename(os.path.dirname(f))}.{os.path.basename(f)}"] = v
    g = (rd(f"{KGSL}/gpu_clock_stats") or "").split()
    fr = (rd(f"{KGSL}/gpu_available_frequencies") or "").split()
    c["gpu"] = dict(zip(fr, (int(x) for x in g))) if len(g) == len(fr) else {}
    for ifc in ("wlan0", "usb0"):
        rx, tx = num(f"/sys/class/net/{ifc}/statistics/rx_bytes"), num(f"/sys/class/net/{ifc}/statistics/tx_bytes")
        if rx is not None:
            c["net"][ifc] = (rx, tx)
    for st in glob.glob("/proc/[0-9]*/stat"):
        t = rd(st)
        if not t:
            continue
        comm = t[t.find("(") + 1:t.rfind(")")]
        f = t[t.rfind(")") + 2:].split()
        c["proc"][st.split("/")[2] + ":" + comm] = int(f[11]) + int(f[12])  # utime + stime, ticks
    c["suspends"] = num("/sys/power/suspend_stats/success")
    return c


def state():
    zones, groups = {}, {}
    for z in glob.glob("/sys/class/thermal/thermal_zone*"):
        typ, t = rd(f"{z}/type"), num(f"{z}/temp")
        if typ is None or t is None:
            continue
        if typ in ZONES:
            zones[typ] = t
        for g in ZONE_GROUPS:
            if typ.startswith(g) and "hw-trip" not in typ:
                groups[g + "max"] = max(groups.get(g + "max", -10**9), t)
    return {
        "capacity": num(f"{PS}/battery/capacity"),
        "charge_uah": num(f"{PS}/battery/charge_counter"),
        "status": rd(f"{PS}/battery/status"),
        "usb_online": num(f"{PS}/usb/online"),
        "usb_type": rd(f"{PS}/usb/type"),
        "backlight": num("/sys/class/backlight/panel0-backlight/brightness"),
        "governors": sorted({rd(p) for p in glob.glob("/sys/devices/system/cpu/cpufreq/policy*/scaling_governor")} - {None}),
        "temp_mc": {**zones, **groups},
    }


def delta(a, b):
    """b - a over nested dicts / tuples of counters; keeps only what changed."""
    if isinstance(b, dict):
        out = {}
        for k, v in b.items():
            if k in a:
                d = delta(a[k], v)
                if d not in (0, {}, [0, 0]):
                    out[k] = d
        return out
    if isinstance(b, (tuple, list)):
        return [y - x for x, y in zip(a, b)]
    return b - a if a is not None and b is not None else None


def energy_model():
    em = {}
    for d in glob.glob(f"{EM}/cpu*"):
        cpus = rd(f"{d}/cpus")
        em[os.path.basename(d)] = {
            "cpus": cpus,
            "uw": {rd(f"{p}/frequency"): num(f"{p}/power") for p in glob.glob(f"{d}/ps:*")},
        }
    return em


def run(a):
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    out = open(a.out, "a", buffering=1)
    out.write(json.dumps({
        "header": 1, "t": time.time(), "kernel": os.uname().release,
        "mem_kb": int((rd("/proc/meminfo") or "x 0").split()[1]), "interval": a.interval, "sample": a.sample,
        "charge_full_uah": num(f"{PS}/battery/charge_full"),
        "policies": {os.path.basename(p): rd(f"{p}/related_cpus") for p in glob.glob("/sys/devices/system/cpu/cpufreq/policy*")},
        "energy_model": energy_model(),
    }) + "\n")
    prev, pm, pb = counters(), time.monotonic(), time.clock_gettime(time.CLOCK_BOOTTIME)
    while True:
        acc, n, end = {}, 0, time.monotonic() + a.interval
        while time.monotonic() < end:
            for k, v in instant().items():
                if v is not None:
                    acc[k] = acc.get(k, 0) + v
            n += 1
            time.sleep(a.sample)
        cur, m, b = counters(), time.monotonic(), time.clock_gettime(time.CLOCK_BOOTTIME)
        d = delta(prev, cur)
        top = sorted(d.pop("proc", {}).items(), key=lambda kv: -kv[1])[:8]
        rec = {"t": round(time.time(), 1), "awake_s": round(m - pm, 2), "asleep_s": round((b - pb) - (m - pm), 2),
               "avg": {k: round(v / n) for k, v in acc.items()}, "d": d, "top": top}
        rec.update(state())
        out.write(json.dumps(rec, separators=(",", ":")) + "\n")
        prev, pm, pb = cur, m, b


def report(a):
    for path in a.files:
        hdr, recs = {}, []
        with open(path) as f:
            for line in f:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue  # a line cut short by a power-off
                if r.get("header"):
                    hdr = r
                else:
                    recs.append(r)
        if not recs:
            print(f"{path}: no records")
            continue
        # Fuel gauge sign: does a positive current go with a falling charge counter?
        s = sum((r["avg"].get("bat_ua", 0)) * (b["charge_uah"] - r["charge_uah"])
                for r, b in zip(recs, recs[1:]) if r.get("charge_uah") and b.get("charge_uah"))
        sign = -1 if s > 0 else 1  # +1: positive current = discharging
        em = hdr.get("energy_model", {})
        print(f"== {path}\nkernel {hdr.get('kernel')}  mem {round((hdr.get('mem_kb') or 0) / 1048576)} GB  "
              f"records {len(recs)}  fuel gauge: positive current = {'discharging' if sign > 0 else 'charging'}")
        print(f"{'hour':11} {'min':>4} {'slept':>5} {'batt':>7} {'sysW':>5} {'usbW':>5} {'iinW':>5} {'batW':>6} {'cpu%':>5} "
              f"{'cpuW*':>5} {'gpuMHz':>6} {'bl':>4} {'cxsd%':>5} {'cpuC':>4} {'batC':>4}  top processes (cpu s)")
        hours = {}
        for r in recs:
            hours.setdefault(time.strftime("%m-%d %H", time.localtime(r["t"])), []).append(r)
        rows = list(hours.items()) + [("total", recs)]
        for h, rs in rows:
            awake = sum(r["awake_s"] for r in rs)
            slept = sum(r["asleep_s"] for r in rs)
            wsum = lambda f: sum(f(r) * r["awake_s"] for r in rs) / awake if awake else 0
            g = lambda r, k: r["avg"].get(k) or 0
            usb_w = wsum(lambda r: g(r, "usb_ua") * g(r, "usb_uv") / 1e12 if r.get("usb_online") else 0)
            iin_w = wsum(lambda r: g(r, "iin_ua") * g(r, "usb_uv") / 1e12 if r.get("usb_online") else 0)
            bat_w = wsum(lambda r: sign * g(r, "bat_ua") * g(r, "bat_uv") / 1e12)  # > 0: battery drains
            tot = sum(v[0] for r in rs for k, v in r["d"].get("cpu", {}).items() if k.startswith("cpu"))
            idle = sum(v[1] for r in rs for k, v in r["d"].get("cpu", {}).items() if k.startswith("cpu"))
            busy = 1 - idle / tot if tot else 0
            # CPU estimate from the kernel's energy model: per policy, mean power at the
            # frequencies it ran at, times the busy CPU-seconds of its CPUs.
            cpu_j = 0.0
            for pol, cpus in (hdr.get("policies") or {}).items():
                first = "cpu" + cpus.split()[0]
                uw = (em.get(first) or {}).get("uw", {})
                tis = {}
                for r in rs:
                    for fq, t in r["d"].get("freq", {}).get(pol, {}).items():
                        tis[fq] = tis.get(fq, 0) + t
                if not tis or not uw:
                    continue
                pw = sum(t * (uw.get(fq) or 0) for fq, t in tis.items()) / sum(tis.values()) / 1e6
                for c in cpus.split():
                    ct = sum(r["d"].get("cpu", {}).get("cpu" + c, [0, 0])[0] for r in rs)
                    ci = sum(r["d"].get("cpu", {}).get("cpu" + c, [0, 0])[1] for r in rs)
                    cpu_j += pw * (ct - ci) / 100
            gp = {}
            for r in rs:
                for fq, t in r["d"].get("gpu", {}).items():
                    gp[fq] = gp.get(fq, 0) + t
            gmhz = sum(int(fq) * t for fq, t in gp.items()) / sum(gp.values()) / 1e6 if gp else 0
            cx = sum(r["d"].get("soc", {}).get("cxsd", [0, 0])[1] for r in rs)
            procs = {}
            for r in rs:
                for name, t in r["top"]:
                    n = name.split(":", 1)[1]
                    procs[n] = procs.get(n, 0) + t / 100
            top = " ".join(f"{n}={t:.0f}" for n, t in sorted(procs.items(), key=lambda kv: -kv[1])[:4])
            tz = lambda k: max((r["temp_mc"].get(k, 0) for r in rs), default=0) / 1000
            wall = awake + slept
            print(f"{h:11} {wall / 60:4.0f} {slept / 60:5.0f} {rs[0]['capacity']:3}>{rs[-1]['capacity']:<3} "
                  f"{usb_w + bat_w:5.2f} {usb_w:5.2f} {iin_w:5.2f} {bat_w:6.2f} {busy * 100:5.1f} {cpu_j / awake if awake else 0:5.2f} "
                  f"{gmhz:6.0f} {rs[-1].get('backlight') or 0:4} {100 * cx / (wall * 19200000) if wall else 0:5.1f} "
                  f"{tz('cpu-max'):4.0f} {tz('battery'):4.0f}  {top}")
        uah = recs[0]["charge_uah"] - recs[-1]["charge_uah"] if recs[0].get("charge_uah") and recs[-1].get("charge_uah") else None
        hrs = (recs[-1]["t"] - recs[0]["t"]) / 3600
        if uah is not None and hrs > 0:
            full = hdr.get("charge_full_uah") or 0
            print(f"charge counter: {uah / 1000:+.0f} mAh drained in {hrs:.1f} h"
                  + (f" = {100 * uah / full / hrs:.2f} %/h" if full else ""))
        print("sysW = usbW + batW (awake time only; batW > 0 means the battery drains). usbW is the fuel gauge's "
              "input reading, iinW the charger ADC's; they disagree, so trust batW with USB unplugged.\n"
              "cpuW* is an estimate from the kernel's energy model, not a measurement.\n")


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--out", default="/var/log/loa-powerlog/%s.jsonl" % time.strftime("%Y%m%d-%H%M%S"))
    r.add_argument("--interval", type=float, default=60)
    r.add_argument("--sample", type=float, default=5)
    q = sub.add_parser("report")
    q.add_argument("files", nargs="+")
    a = p.parse_args()
    (run if a.cmd == "run" else report)(a)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
