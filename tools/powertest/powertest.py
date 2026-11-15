#!/usr/bin/python3
"""Power baseline of the 8 GB tablet on battery, driven from the Mac over the USB cable.

    tools/powertest/powertest.py setup                 install the test software on the tablet
    tools/powertest/powertest.py run [options]         measure; writes report.md and report.json
    tools/powertest/powertest.py report DIR            rebuild the report from a run's directory

`run` cuts the charger input for each block (the USB data link stays up), so
system power is the battery's voltage times its current. Workloads:
  idle    screen on at a fixed backlight, terminal and preview page open, nothing running
  replay  a fixed cycle of source edits with hot reload and a page reload (the baseline)
  agent   Pi Agent on a fixed prompt against the LAN endpoint (the cross-check)
Each repeat starts between --window charge levels; the runner drains or charges
the battery to get there. A watchdog on the tablet restores everything when this
runner stops sending heartbeats. The LLM endpoint may be used only between
00:00 and 08:00 local time: outside that window the agent blocks are skipped
(--agent-anytime overrides it for a person at the keyboard).
TSSH=/path/to/tssh overrides tools/tssh (a worktree has no keys/).
The shebang is the system Python on purpose: macOS hides the network interfaces'
MAC addresses from Homebrew's Python and its children, so tools/tssh could not
find the tablet's USB interface from there.
"""
import argparse
import json
import math
import os
import signal
import statistics
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
TSSH = os.environ.get("TSSH", os.path.join(REPO, "tools", "tssh"))
CTL = "python3 /opt/loa-powertest/src/tablet/loa-powertest.py"
WINDOW_END_H = 8  # the endpoint may be used from 00:00 to 08:00 local time


def log(msg):
    print(time.strftime("%H:%M:%S ") + msg, flush=True)


def ssh(cmd, timeout=120, inp=None, tries=8):
    """Run CMD on the tablet. The USB link re-enumerates now and then (#72): when
    the interface is gone or ssh itself fails (255), wait and try again."""
    for i in range(tries):
        try:
            r = subprocess.run([TSSH, cmd], input=inp, capture_output=True, timeout=timeout)
            rc, o, e = r.returncode, r.stdout.decode(errors="replace"), r.stderr.decode(errors="replace")
        except subprocess.TimeoutExpired:
            rc, o, e = 255, "", "timeout"
        if rc != 255 and "interface not found" not in e:
            return rc, o, e
        time.sleep(5)
    return rc, o, e


def ctl(args, timeout=180, check=True):
    """Run a tablet-side command; returns its JSON line (the last one printed)."""
    rc, o, e = ssh(f"{CTL} {args}", timeout=timeout)
    lines = [x for x in o.splitlines() if x.startswith("{")]
    res = json.loads(lines[-1]) if lines else {"error": (e or o).strip()[-300:] or f"rc {rc}"}
    if check and (rc != 0 or "error" in res):
        raise RuntimeError(f"tablet: {args.split()[0]}: {res.get('error', res)}")
    return res


def push():
    """Copy tools/powertest and loa-powerlog.py to /opt/loa-powertest/src."""
    tar = subprocess.run(["tar", "-c", "--no-xattrs", "--exclude", "node_modules", "--exclude", "__pycache__",
                          "-C", HERE, "tablet", "project", "edits.json", "prompt.txt",
                          "-C", os.path.join(REPO, "tools", "powerlog"), "loa-powerlog.py"],
                         capture_output=True, check=True, env=dict(os.environ, COPYFILE_DISABLE="1")).stdout
    rc, o, e = ssh("set -e; rm -rf /opt/loa-powertest/src.new; mkdir -p /opt/loa-powertest/src.new; "
                   "tar -x -C /opt/loa-powertest/src.new 2>/dev/null; rm -rf /opt/loa-powertest/src; "
                   "mv /opt/loa-powertest/src.new /opt/loa-powertest/src", inp=tar)
    if rc != 0:
        raise RuntimeError("push failed: " + e)


def preflight():
    rc, o, e = ssh("hostname; awk '/MemTotal/{print int($2/1024)}' /proc/meminfo; "
                   "pgrep -x Hyprland >/dev/null && echo hypr; "
                   "for f in /var/lib/loa-update/pending /loa/dev-watchdog /run/loa-powertest/active; do "
                   "[ -e $f ] && echo refuse:$f; done; true", timeout=30)
    if rc != 0:
        raise RuntimeError("tablet not reachable: " + e.strip())
    lines = o.split()
    host, mem = lines[0], int(lines[1])
    if not 6000 < mem < 9000:
        raise RuntimeError(f"the tablet that answers has {mem} MB RAM; this test runs only on the 8 GB tablet")
    if "hypr" not in lines:
        raise RuntimeError("no graphical session (Hyprland) on the tablet")
    refuse = [x[7:] for x in lines if x.startswith("refuse:")]
    if refuse:
        raise RuntimeError("refusing to start: " + ", ".join(refuse) + " exists on the tablet")
    return {"hostname": host, "mem_mb": mem}


def in_window(start, seconds):
    """The agent block must start and end inside 00:00-08:00 local time."""
    t = time.localtime(start)
    end = time.localtime(start + seconds + 120)
    return t.tm_hour < WINDOW_END_H and end.tm_hour < WINDOW_END_H and end.tm_mday == t.tm_mday


class Holder(threading.Thread):
    """Keeps `loa-powertest.py hold` open on the tablet and writes a line into it
    every 5 s. If this process dies, ssh's stdin closes, the tablet reads end of
    file and restores itself within seconds. A session lost with the USB link is
    replaced by a new one."""
    def __init__(self):
        super().__init__(daemon=True)
        self.stop = threading.Event()
        self.n = 0

    def run(self):
        while not self.stop.is_set():
            self.n += 1
            p = subprocess.Popen([TSSH, f"{CTL} hold --id {os.getpid()}-{self.n}"], stdin=subprocess.PIPE,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                while p.poll() is None and not self.stop.is_set():
                    p.stdin.write(b".\n")
                    p.stdin.flush()
                    self.stop.wait(5)
            except OSError:
                pass
            if self.stop.is_set():
                break
            p.kill()
            self.stop.wait(5)
        try:
            p.stdin.close()
            p.wait(10)
        except Exception:
            p.kill()


class Heartbeat(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.stop = threading.Event()
        self.last = {}

    def run(self):
        while not self.stop.wait(10):
            try:
                self.last = ctl("hb", timeout=20, check=False)
            except Exception as exc:  # keep beating; the watchdog decides
                self.last = {"error": str(exc)}


# ---------------------------------------------------------------- analysis

def block_power(path, discard, seconds):
    """Mean system power of one block from its loa-powerlog file (input cut, so the
    battery alone supplies the system; positive battery current = discharging)."""
    recs, hdr = [], {}
    with open(path) as f:
        for line in f:
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("header"):
                hdr = r
            else:
                recs.append(r)
    if not recs:
        return None
    t0 = hdr.get("t", recs[0]["t"] - recs[0]["awake_s"])
    # Only the block itself: after the discard, and not past its end (a block whose
    # stop came late because the USB link was down keeps running on the tablet).
    use = [r for r in recs if r["t"] - r["awake_s"] >= t0 + discard and r["t"] <= t0 + seconds + 1]
    w = [r["avg"]["bat_ua"] * r["avg"]["bat_uv"] / 1e12 for r in use]
    usb = max((r["avg"].get("usb_ua") or 0) for r in use) if use else None
    temps = [r["temp_mc"].get("battery", 0) / 1000 for r in use if r.get("temp_mc")]
    cpu = [r["temp_mc"].get("cpu-max", 0) / 1000 for r in use if r.get("temp_mc")]
    return {"mean_w": statistics.fmean(w) if w else None, "sd_within_w": statistics.pstdev(w) if len(w) > 1 else 0,
            "records": len(use), "usb_ua_max": usb, "min_bat_ua": min(r["avg"]["bat_ua"] for r in use) if use else None,
            "battery_c": [round(min(temps), 1), round(max(temps), 1)] if temps else None,
            "cpu_max_c": round(max(cpu), 1) if cpu else None,
            "slept_s": round(sum(r.get("asleep_s", 0) for r in use), 1)}


def block_valid(b):
    p = b.get("power") or {}
    if not p or p.get("mean_w") is None:
        return "no power records"
    if p["usb_ua_max"] != 0:
        return f"USB current not 0 during the block ({p['usb_ua_max']} uA)"
    if p["min_bat_ua"] is not None and p["min_bat_ua"] <= 0:
        return "battery was not discharging in every record"
    if p["slept_s"] > 1:
        return "the tablet slept during the block"
    en = b.get("result", {}).get("end", {})
    if en.get("screen_on") is False or en.get("screensaver"):
        return "the screen went off or the screensaver started during the block"
    if en.get("backlight") not in (None, b.get("backlight")):
        return f"backlight changed during the block ({en.get('backlight')})"
    d = b.get("result", {}).get("driver", {})
    if b["workload"] == "replay":
        if not d.get("cycles"):
            return "replay ran no cycles"
        if d.get("failed"):
            return f"replay: {d['failed']} of {d['cycles']} cycles failed"
    if b["workload"] == "agent":
        if d.get("failed") or not d.get("runs"):
            return "agent: endpoint error (503 or other), repeat discarded"
    return None


def sd(xs):
    return statistics.stdev(xs) if len(xs) > 1 else float("nan")


def report(outdir):
    meta = json.load(open(os.path.join(outdir, "run.json")))
    blocks = meta["blocks"]
    lines = [f"# Power baseline {meta['run_id']}", ""]
    c = meta.get("conditions", {})
    v = c.get("versions", {})
    pol = c.get("cpufreq", {})
    lines += ["## Fixed conditions", "",
              f"- Tablet: {meta['preflight']['hostname']}, {meta['preflight']['mem_mb']} MB RAM; kernel `{c.get('kernel')}`; "
              f"image `{c.get('image')}`",
              "- CPU: " + "; ".join(f"{p} `{x['governor']}` ({', '.join(f'{k}={t}' for k, t in sorted(x['tunables'].items()))})"
                                     for p, x in pol.items()),
              f"- RT clamp min `{c.get('rt_clamp_min')}`; bus `boost_freq` {c.get('bus_boost_freq')}; "
              f"`sleep_disabled` {c.get('sleep_disabled')}",
              f"- Backlight fixed at {meta['args']['backlight']} (raw, max 4095), auto-brightness paused, "
              "hypridle inhibited, Omarchy's screensaver timer off",
              f"- Versions: {v.get('chromium')}, {v.get('nodejs')}, Pi Agent {v.get('pi')}, Vite {v.get('vite')}, "
              f"{v.get('hyprland')}; LLM model `{c.get('llm_model')}` (temperature 0)",
              f"- Wi-Fi: network `{(c.get('wifi') or {}).get('network')}` (hash), "
              f"{(c.get('wifi') or {}).get('mhz')}",
              f"- Each block: {meta['args']['seconds']:.0f} s with the charger input cut, first "
              f"{meta['args']['discard']:.0f} s discarded, loa-powerlog every {meta['args']['interval']:.0f} s "
              f"({meta['args']['sample']:.0f} s samples); start charge window {meta['args']['window']} %; "
              f"replay period {meta['args']['period']:.0f} s", ""]
    lines += ["## Result", "", "| Workload | Valid repeats | Mean (W) | SD across repeats (W) | Blocks (W) |",
              "|---|---|---|---|---|"]
    summary = {}
    for wl in meta["args"]["workloads"]:
        bs = [b for b in blocks if b["workload"] == wl]
        ok = [b for b in bs if not b.get("invalid") and not b.get("skipped")]
        ws = [b["power"]["mean_w"] for b in ok]
        summary[wl] = {"n": len(ws), "mean_w": statistics.fmean(ws) if ws else None, "sd_w": sd(ws) if ws else None}
        if not ws:
            why = "; ".join(sorted({b.get("skipped") or b.get("invalid") or "" for b in bs})) or "not run"
            lines.append(f"| {wl} | 0 | - | - | {why} |")
            continue
        lines.append(f"| {wl} | {len(ws)} | {statistics.fmean(ws):.2f} | {sd(ws):.3f} | "
                     + " ".join(f"{x:.2f}" for x in ws) + " |")
    lines += [""]
    r, ag = summary.get("replay", {}), summary.get("agent", {})
    if r.get("sd_w") is not None and not math.isnan(r["sd_w"]):
        lines.append(f"Replay repeatability: SD {r['sd_w']:.3f} W, "
                     + ("within" if r["sd_w"] <= 0.1 else "**outside**") + " the 0.1 W limit.")
    if r.get("mean_w") and ag.get("mean_w"):
        diff = ag["mean_w"] - r["mean_w"]
        lines.append(f"Agent minus replay: {diff:+.2f} W ({100 * diff / r['mean_w']:+.0f} %); agent SD "
                     f"{ag['sd_w']:.3f} W.")
    lines += ["", "## Blocks", "",
              "| # | Workload | Start | Charge | Mean W | SD in block | Battery C | CPU max C | Mem MB start/end | "
              "Swap MB start/end | Work | Note |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for i, b in enumerate(blocks, 1):
        p, res = b.get("power") or {}, b.get("result") or {}
        st, en, d = res.get("start", {}), res.get("end", {}), res.get("driver", {})
        if b["workload"] == "replay":
            work = f"{d.get('cycles', 0)} cycles, {d.get('failed', 0)} failed"
            if d.get("hot_ms"):
                work += f", hot update median {statistics.median(d['hot_ms'])} ms"
        elif b["workload"] == "agent":
            runs = d.get("runs", [])
            work = (f"{len(runs)} Pi runs ({sum(x.get('finished', False) for x in runs)} finished), "
                    f"{sum(x['turns'] for x in runs)} turns, {sum(x['tool_calls'] for x in runs)} tool calls, "
                    f"{sum(x['input_tokens'] for x in runs)} in / {sum(x['output_tokens'] for x in runs)} out tokens")
        else:
            work = "-"
        note = b.get("skipped") or b.get("invalid") or ""
        lines.append(f"| {i} | {b['workload']} | {time.strftime('%H:%M', time.localtime(b.get('t', 0)))} | "
                     f"{st.get('capacity', '-')}>{en.get('capacity', '-')} % | "
                     f"{p['mean_w']:.2f} | {p['sd_within_w']:.2f} | {p['battery_c']} | {p['cpu_max_c']} | "
                     if p.get("mean_w") is not None else
                     f"| {i} | {b['workload']} | {time.strftime('%H:%M', time.localtime(b.get('t', 0)))} | - | - | - | - | - | ")
        if p.get("mean_w") is not None:
            lines[-1] += (f"{st.get('mem_used_mb')}/{en.get('mem_used_mb')} | {st.get('swap_used_mb')}/{en.get('swap_used_mb')} | "
                          f"{work} | {note} |")
        else:
            lines[-1] += f"- | - | {work} | {note} |"
    lines += ["", "Mean W is the battery's voltage times its current with the charger input cut, so it is the "
              "system draw without charger losses; the live USB data link adds an unknown, constant offset.", ""]
    for n in meta.get("notes", []):
        lines.append(f"- {n}")
    text = "\n".join(lines) + "\n"
    open(os.path.join(outdir, "report.md"), "w").write(text)
    json.dump({"summary": summary, "conditions": c, "blocks": blocks}, open(os.path.join(outdir, "report.json"), "w"),
              indent=1)
    return text


# ---------------------------------------------------------------- the run

def wait_charge(a, hb, state):
    """Bring the charge into the window: drain with the input cut, or charge."""
    lo, hi = a.lo, a.hi
    target = min(hi, lo + a.charge_margin)
    while True:
        cap = ctl("hb", check=False).get("capacity")
        if cap is None:
            raise RuntimeError("cannot read the charge level")
        if lo <= cap <= hi:
            return cap
        if cap > hi:
            # The tablet resumes the input itself at the target (or the deadline).
            log(f"charge {cap} % > {hi} %: draining with the input cut")
            ctl(f"input suspend --max-seconds {a.max_drain} --until-capacity {hi}")
            t_end = time.time() + a.max_drain + 120
            while time.time() < t_end:
                time.sleep(30)
                st = ctl("hb", check=False)
                if st.get("active") is False:
                    raise RuntimeError("the tablet ended the run (watchdog): " + str(st.get("last_restore")))
                if st.get("suspend_status") == 0:
                    break
            ctl("input resume")
        else:
            log(f"charge {cap} % < {lo} %: charging to {target} %" + (" with the screen off" if a.charge_screen_off else ""))
            if a.charge_screen_off:
                ctl("display off")
            else:
                ctl(f"backlight {a.charge_backlight}")
            while (hb.last.get("capacity") or cap) < target:
                time.sleep(30)
                if not hb.last.get("active", True):
                    raise RuntimeError("the tablet ended the run (watchdog): " + str(hb.last.get("last_restore")))
            if a.charge_screen_off:
                ctl("display on")
            ctl(f"backlight {a.backlight}")


def run_block(a, wl, tag, outdir, hb, state):
    b = {"workload": wl, "tag": tag, "backlight": a.backlight}
    ctl("display on")
    ctl("services start", timeout=240)
    time.sleep(a.settle)
    # The tablet ends the block and resumes the input by itself (the block's own stop
    # unit, and the suspend deadline as a backstop), so a USB link drop on the Mac's
    # side changes nothing in the block; the runner collects the result afterwards.
    ctl(f"input suspend --max-seconds {a.seconds + 120}")
    b["t"] = time.time()
    ctl(f"block start {wl} --seconds {a.seconds} --tag {tag} --interval {a.interval} --sample {a.sample} "
        f"--period {a.period}", timeout=120)
    end = time.time() + a.seconds
    while time.time() < end:
        time.sleep(min(15, max(0.5, end - time.time())))
    res = f"{state['logdir']}/{tag}.result.json"
    t_end = time.time() + 1500
    while True:
        rc, o, e = ssh(f"cat {res} 2>/dev/null", timeout=60)
        if rc == 0 and o.strip():
            b["result"] = json.loads(o)
            break
        st = ctl("hb", check=False)
        if st.get("active") is False:
            raise RuntimeError("the tablet ended the run (watchdog): " + str(st.get("last_restore")))
        if time.time() > t_end:
            raise RuntimeError("no block result 25 minutes after the block's end")
        time.sleep(10)
    r = ctl("input resume")
    b["resumed"] = {k: r.get(k) for k in ("suspend_status", "usb_ua")}
    ctl("services stop")
    rc, o, e = ssh(f"cat {state['logdir']}/{tag}.jsonl", timeout=120)
    path = os.path.join(outdir, f"{tag}.jsonl")
    open(path, "w").write(o)
    b["power"] = block_power(path, a.discard, a.seconds)
    b["invalid"] = block_valid(b)
    return b


def recover(a, run_id, total, state):
    """After the USB link was lost long enough for the tablet to restore itself, or a
    command failed: wait for the tablet, make sure it is restored, start again."""
    log("recovering: waiting for the tablet")
    t_end = time.time() + 1800
    while time.time() < t_end:
        if ssh("true", timeout=30, tries=1)[0] == 0:
            break
        time.sleep(10)
    else:
        raise RuntimeError("the tablet was unreachable for 30 minutes")
    ctl("end --reason runner-recovery", check=False)
    preflight()
    r = ctl(f"begin --run-id {run_id} --max-seconds {total:.0f} --backlight {a.backlight} "
            f"--heartbeat-timeout {a.heartbeat_timeout}")
    state["logdir"] = r["logdir"]
    log("recovered")


def cmd_run(a):
    if sys.platform == "darwin" and not os.environ.get("POWERTEST_AWAKE"):
        # A sleeping Mac stops the heartbeats; caffeinate keeps it awake for the run.
        os.execvpe("caffeinate", ["caffeinate", "-i", sys.executable, *sys.argv],
                   dict(os.environ, POWERTEST_AWAKE="1"))
    a.lo, a.hi = (int(x) for x in a.window.split("-"))
    a.workloads = a.workloads.split(",")
    run_id = time.strftime("%Y%m%d-%H%M%S")
    outdir = a.out or os.path.join(os.environ.get("XDG_STATE_HOME", os.path.expanduser("~/.local/state")),
                                   "loa-powertest", run_id)
    os.makedirs(outdir, exist_ok=True)
    meta = {"run_id": run_id, "args": vars(a), "blocks": [], "notes": []}
    save = lambda: json.dump(meta, open(os.path.join(outdir, "run.json"), "w"), indent=1)
    log(f"run {run_id}, output in {outdir}")
    meta["preflight"] = preflight()
    push()
    state = {}
    per_block = a.seconds + a.settle + 600 + 3600 / max(1, a.repeats)  # generous: includes charging
    total = len(a.workloads) * a.repeats * (a.max_attempts * per_block) + 3 * 3600
    hb = Heartbeat()
    holder = Holder()

    def bail(signum, frame):
        log(f"signal {signum}: restoring the tablet")
        try:
            ctl("end --reason runner-signal", check=False, timeout=90)
        finally:
            os._exit(1)
    signal.signal(signal.SIGINT, bail)
    signal.signal(signal.SIGTERM, bail)
    try:
        r = ctl(f"begin --run-id {run_id} --max-seconds {total:.0f} --backlight {a.backlight} "
                f"--heartbeat-timeout {a.heartbeat_timeout}")
        state["logdir"] = r["logdir"]
        meta["conditions"] = r["conditions"]
        holder.start()
        hb.start()
        save()
        agent_ok = "agent" in a.workloads
        if agent_ok and not (a.agent_anytime or in_window(time.time(), 0)):
            agent_ok = False
            meta["notes"].append("agent: skipped, outside the endpoint's window (00:00-08:00 local time)")
        if agent_ok:
            w = ctl("warmup", timeout=200, check=False)
            if w.get("http") != "200":
                time.sleep(30)
                w = ctl("warmup", timeout=200, check=False)
            meta["notes"].append(f"endpoint warm-up: HTTP {w.get('http')} in {w.get('seconds')} s")
            if w.get("http") != "200":
                agent_ok = False
                meta["notes"].append("agent: skipped, the endpoint did not answer the warm-up")
        for rep in range(1, a.repeats + 1):
            for wl in a.workloads:
                for attempt in range(1, a.max_attempts + 1):
                    tag = f"{wl}-{rep}" + (f"-try{attempt}" if attempt > 1 else "")
                    if wl == "agent" and not agent_ok:
                        meta["blocks"].append({"workload": wl, "tag": tag, "t": time.time(),
                                               "skipped": "skipped: endpoint not usable"})
                        break
                    try:
                        cap = wait_charge(a, hb, state)
                        if wl == "agent" and not (a.agent_anytime or in_window(time.time(), a.seconds + a.settle + 120)):
                            meta["blocks"].append({"workload": wl, "tag": tag, "t": time.time(),
                                                   "skipped": "skipped: would end outside 00:00-08:00"})
                            break
                        log(f"{tag}: start at {cap} %")
                        b = run_block(a, wl, tag, outdir, hb, state)
                    except RuntimeError as exc:
                        log(f"{tag}: interrupted: {exc}")
                        meta["blocks"].append({"workload": wl, "tag": tag, "t": time.time(),
                                               "invalid": f"interrupted: {exc}"})
                        meta["notes"].append(f"{tag}: interrupted ({exc}); the run recovered and went on")
                        save()
                        recover(a, run_id, total, state)
                        continue
                    meta["blocks"].append(b)
                    save()
                    p = b.get("power") or {}
                    log(f"{tag}: {p.get('mean_w', 0):.3f} W" + (f" INVALID: {b['invalid']}" if b["invalid"] else ""))
                    if not b["invalid"]:
                        break
        meta["notes"].append(f"input after the run: {ctl('hb', check=False).get('suspend_status')} (suspend_status)")
    except Exception as exc:
        meta["notes"].append(f"run aborted: {exc}")
        log(f"ERROR: {exc}")
    finally:
        hb.stop.set()
        e = ctl("end", check=False, timeout=120)
        holder.stop.set()  # after `end`: the lock is gone, so its end of file changes nothing
        holder.join(20)
        meta["end"] = e
        save()
    print(report(outdir))
    log(f"report: {os.path.join(outdir, 'report.md')}")


def cmd_setup(a):
    preflight()
    push()
    rc, o, e = ssh("sh /opt/loa-powertest/src/tablet/setup-tablet.sh 2>&1", timeout=1800)
    print(o[-3000:])
    sys.exit(rc)


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("setup")
    r = sub.add_parser("run")
    r.add_argument("--workloads", default="agent,replay,idle")
    r.add_argument("--repeats", type=int, default=3)
    r.add_argument("--seconds", type=float, default=600)
    r.add_argument("--window", default="85-90", help="charge range in %% each block starts in")
    r.add_argument("--charge-margin", type=int, default=3, help="charge to window low + this")
    r.add_argument("--backlight", type=int, default=820)
    r.add_argument("--period", type=float, default=30, help="replay: seconds per edit cycle")
    r.add_argument("--interval", type=float, default=10)
    r.add_argument("--sample", type=float, default=1)
    r.add_argument("--discard", type=float, default=20)
    r.add_argument("--settle", type=float, default=30)
    r.add_argument("--max-attempts", type=int, default=3)
    r.add_argument("--max-drain", type=float, default=7200)
    # Long, because the USB link drops for minutes at a time (#72); the runner's death is
    # seen at once through its held session, and every suspend ends on the tablet anyway.
    r.add_argument("--heartbeat-timeout", type=float, default=900)
    # Off by default: with the screen off the Mac loses the tablet's USB link for
    # minutes at a time (#72). Charging happens with the screen on at a low backlight.
    r.add_argument("--charge-screen-off", action=argparse.BooleanOptionalAction, default=False)
    r.add_argument("--charge-backlight", type=int, default=40)
    r.add_argument("--agent-anytime", action="store_true",
                   help="use the endpoint outside 00:00-08:00 (only for a person at the keyboard)")
    r.add_argument("--out")
    q = sub.add_parser("report")
    q.add_argument("dir")
    a = p.parse_args()
    if a.cmd == "setup":
        cmd_setup(a)
    elif a.cmd == "run":
        cmd_run(a)
    else:
        print(report(a.dir))


if __name__ == "__main__":
    main()
