#!/usr/bin/env python3
"""Tablet side of the power test (tools/powertest/powertest.py drives it over SSH).

    loa-powertest.py begin --run-id ID --max-seconds N [--backlight RAW] [--heartbeat-timeout S]
    loa-powertest.py hb                       heartbeat; prints the run status as JSON
    loa-powertest.py input suspend --max-seconds N | resume
    loa-powertest.py display on|off | backlight RAW
    loa-powertest.py services start|stop      dev server, test Chromium, terminal
    loa-powertest.py block start WORKLOAD --seconds S --tag TAG [--period S --step none|build|test]
    loa-powertest.py block stop --tag TAG
                                              (start also schedules its own stop: a USB link
                                              drop on the Mac's side cannot stretch a block)
    loa-powertest.py conditions | warmup | end
    loa-powertest.py hold --id N              the runner's session: EOF on stdin ends the run
    loa-powertest.py watchdog                 (started by `begin` as a transient unit)
    loa-powertest.py agent-loop ...           (started by `block start agent`)

Everything a run changes is undone by `end`. The same restore runs at once when
the runner's `hold` session reads end of file (the runner on the Mac was killed:
its pipe into ssh closed), and from the watchdog when no heartbeat came for
--heartbeat-timeout seconds (the Mac or the USB link is gone; the link drops for
half a minute now and then, #72, so this timeout is longer), when the run
overruns its time, or when the charge falls below 30 % with the charger input cut. The charger input is cut
with a vote in the charge driver under one fixed client name, so the resume
always clears our own vote.
Nothing here prints the LLM endpoint's address or key.
"""
import argparse
import glob
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import time

BASE = "/opt/loa-powertest"
SRC = f"{BASE}/src"
PROJECT = f"{BASE}/project"
HOME = f"{BASE}/home"
PI = f"{BASE}/pi/bin/pi"
RUN = "/run/loa-powertest"
WORK = f"{RUN}/work"  # written by test processes running as the desktop user
LOCK = f"{RUN}/active"
HB = f"{RUN}/heartbeat"
HOLDER = f"{RUN}/holder"
SAVED = f"{RUN}/saved.json"
SUSP = f"{RUN}/suspended"
PIDIR = f"{RUN}/pi-agent"
LOGROOT = "/var/log/loa-powertest"
LLM_ENV = "/root/.config/loa-powertest/llm.env"
CHG = "/sys/devices/platform/soc/soc:mca_charge_interface"
PS = "/sys/class/power_supply"
BL = "/sys/class/backlight/panel0-backlight/brightness"
AB_OFF = "/run/loa-autobrightness-off"
STAY = "/home/omarchy/.local/state/omarchy/indicators/stay-awake"
CLIENT = "loa-powertest"
UNITS = ("blockend", "driver", "powerlog", "chromium", "term", "vite")
REFUSE = ("/var/lib/loa-update/pending", "/loa/dev-watchdog")
USER_ENV = {
    "HOME": HOME, "USER": "omarchy", "LOGNAME": "omarchy",
    "XDG_RUNTIME_DIR": "/run/user/1000", "WAYLAND_DISPLAY": "wayland-1",
    "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus",
    "PATH": f"{BASE}/pi/bin:/usr/local/bin:/usr/bin",
    "npm_config_cache": f"{BASE}/npm-cache", "npm_config_update_notifier": "false",
    "NO_PROXY": "*", "no_proxy": "*",
}


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


def write(path, text):
    with open(path, "w") as f:
        f.write(text)


def out(obj):
    print(json.dumps(obj, separators=(",", ":")), flush=True)


def die(msg, code=1):
    out({"error": msg})
    sys.exit(code)


def hypr_env():
    hy = sorted(glob.glob("/run/user/1000/hypr/*/"), key=os.path.getmtime)
    env = dict(USER_ENV, HOME="/home/omarchy")
    env["HYPRLAND_INSTANCE_SIGNATURE"] = os.path.basename(hy[-1].rstrip("/")) if hy else ""
    return env


def as_user(*cmd, timeout=10):
    r = subprocess.run(["setpriv", "--reuid=1000", "--regid=1000", "--init-groups", *cmd],
                       env=hypr_env(), capture_output=True, text=True, timeout=timeout)
    return r.stdout


def unit(name, cmd, user=True, cwd=None, env=None):
    """Start a transient system unit; as the desktop user unless user=False."""
    argv = ["systemd-run", f"--unit=loa-powertest-{name}", "--collect", "--quiet",
            "-p", "KillMode=control-group", "-p", "TimeoutStopSec=10"]
    if cwd:
        argv += ["-p", f"WorkingDirectory={cwd}"]
    for k, v in ({**USER_ENV, **(env or {})} if user else (env or {})).items():
        argv.append(f"--setenv={k}={v}")
    if user:
        argv += ["--", "setpriv", "--reuid=1000", "--regid=1000", "--init-groups"]
    else:
        argv += ["--"]
    subprocess.run(argv + list(cmd), check=True)


def unit_active(name):
    return subprocess.run(["systemctl", "is-active", "--quiet", f"loa-powertest-{name}"]).returncode == 0


def stop_units(*names):
    # One at a time: `systemctl stop a b` stops nothing when one of them is not loaded.
    for n in names:
        subprocess.run(["systemctl", "stop", f"loa-powertest-{n}"], stderr=subprocess.DEVNULL)
        subprocess.run(["systemctl", "reset-failed", f"loa-powertest-{n}"], stderr=subprocess.DEVNULL)


# ---------------------------------------------------------------- charger input

def power():
    return {
        "suspend_status": num(f"{CHG}/suspend_status"),
        "usb_ua": num(f"{PS}/usb/current_now"),
        "bat_ua": num(f"{PS}/battery/current_now"),
        "capacity": num(f"{PS}/battery/capacity"),
        "battery_temp_dc": num(f"{PS}/battery/temp"),
    }


def input_set(on):
    write(f"{CHG}/input_suspend", f"{CLIENT} all {1 if on else 0}")


def input_resume_verified(timeout=20):
    input_set(False)
    end = time.time() + timeout
    while time.time() < end:
        p = power()
        if p["suspend_status"] == 0 and (p["usb_ua"] or 0) > 0:
            return p
        time.sleep(1)
    return None


def cmd_input(a):
    if a.what == "suspend":
        if not os.path.exists(LOCK):
            die("no run is active")
        write(SUSP, json.dumps({"deadline": time.time() + a.max_seconds, "until_capacity": a.until_capacity}))
        input_set(True)
        end = time.time() + 10
        while time.time() < end:
            p = power()
            if p["suspend_status"] == 1 and p["usb_ua"] == 0:
                out({"ok": True, **p})
                return
            time.sleep(0.5)
        input_resume_verified()
        os.unlink(SUSP)
        die("suspend not confirmed: %s" % json.dumps(power()))
    p = input_resume_verified()
    if os.path.exists(SUSP):
        os.unlink(SUSP)
    if p is None:
        die("resume not confirmed: %s (votes: %s)" % (json.dumps(power()), rd(f"{CHG}/input_suspend")))
    out({"ok": True, **p})


# ---------------------------------------------------------------- display and idle

def monitors():
    try:
        return json.loads(as_user("hyprctl", "monitors", "-j") or "[]")
    except ValueError:
        return []


def dpms(on):
    act = "enable" if on else "disable"
    as_user("hyprctl", "eval", 'hl.dispatch(hl.dsp.dpms({ action = "%s" }))' % act)
    for _ in range(20):
        m = monitors()
        if m and all(x.get("dpmsStatus") == on for x in m):
            return True
        time.sleep(0.25)
    return False


def close_screensaver():
    as_user("pkill", "-f", "org.omarchy.screensaver")


def cmd_backlight(a):
    if not os.path.exists(AB_OFF):
        die("auto-brightness is not paused")
    write(BL, str(a.raw))
    out({"ok": True, "backlight": num(BL)})


def cmd_display(a):
    s = json.loads(rd(SAVED) or "{}")
    ok = dpms(a.what == "on")
    if a.what == "on":
        time.sleep(0.5)
        close_screensaver()
        if s.get("backlight_fixed") is not None:
            write(BL, str(s["backlight_fixed"]))
    out({"ok": ok, "backlight": num(BL)})


# ---------------------------------------------------------------- conditions

def versions():
    def first_line(*cmd, user=False):
        try:
            r = (as_user(*cmd) if user else subprocess.run(cmd, capture_output=True, text=True, timeout=20).stdout)
            return r.strip().splitlines()[0] if r.strip() else None
        except (OSError, subprocess.TimeoutExpired, IndexError):
            return None
    pi = json.loads(rd(f"{BASE}/pi/lib/node_modules/@earendil-works/pi-coding-agent/package.json") or "{}").get("version")
    vite = json.loads(rd(f"{PROJECT}/node_modules/vite/package.json") or "{}").get("version")
    return {
        "chromium": first_line("pacman", "-Q", "chromium"),
        "nodejs": first_line("pacman", "-Q", "nodejs"),
        "hyprland": first_line("pacman", "-Q", "hyprland"),
        "pi": pi, "vite": vite,
    }


def wifi():
    try:
        r = subprocess.run(["nmcli", "-t", "-f", "ACTIVE,SSID,FREQ,SIGNAL", "dev", "wifi"],
                           capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    for line in r.splitlines():
        p = line.split(":")
        if p[0] == "yes" and len(p) >= 4:
            # The network's name stays out of the report: only a short hash of it.
            return {"network": hashlib.sha256(p[1].encode()).hexdigest()[:8], "mhz": p[2], "signal": p[3]}
    return {"network": None}


def meminfo():
    m = {}
    for line in (rd("/proc/meminfo") or "").splitlines():
        k, v = line.split(":", 1)
        m[k] = int(v.split()[0])
    return {"mem_used_mb": (m["MemTotal"] - m["MemAvailable"]) // 1024,
            "swap_used_mb": (m["SwapTotal"] - m["SwapFree"]) // 1024}


def conditions():
    pol = {}
    for p in sorted(glob.glob("/sys/devices/system/cpu/cpufreq/policy*")):
        g = rd(f"{p}/scaling_governor")
        tun = {}
        for t in glob.glob(f"{p}/{g}/*"):
            v = rd(t)
            if v is not None and len(v) < 40:
                tun[os.path.basename(t)] = v
        pol[os.path.basename(p)] = {"governor": g, "min": rd(f"{p}/scaling_min_freq"),
                                    "max": rd(f"{p}/scaling_max_freq"), "tunables": tun}
    bus = {d: rd(f"/sys/devices/system/cpu/bus_dcvs/{d}/boost_freq") for d in ("DDR", "LLCC", "DDRQOS")}
    return {
        "kernel": os.uname().release,
        "image": rd("/var/lib/loa-update/version"),
        "cpufreq": pol,
        "rt_clamp_min": rd("/proc/sys/kernel/sched_util_clamp_min_rt_default"),
        "bus_boost_freq": bus,
        "sleep_disabled": rd("/sys/module/qcom_lpm/parameters/sleep_disabled") or "absent",
        "backlight": num(BL),
        "autobrightness_paused": os.path.exists(AB_OFF),
        "versions": versions(),
        "wifi": wifi(),
        "llm_model": llm_env().get("LLM_MODEL"),
        "ram_mb": num("/proc/meminfo") // 1024 if num("/proc/meminfo") else None,
        **meminfo(),
    }


def cmd_conditions(a):
    out(conditions())


# ---------------------------------------------------------------- run lifetime

def cmd_begin(a):
    for f in REFUSE:
        if os.path.exists(f):
            die(f"refusing: {f} exists (another session's kernel or update trial)", 3)
    if os.path.exists(LOCK):
        die("refusing: a power test is already active (%s)" % rd(LOCK), 4)
    if not os.path.exists(PI) or not os.path.isdir(f"{PROJECT}/node_modules"):
        die("test software missing: run tools/powertest/setup.sh first", 5)
    os.makedirs(WORK, exist_ok=True)
    os.chown(WORK, 1000, 1000)
    logdir = f"{LOGROOT}/{a.run_id}"
    os.makedirs(logdir, exist_ok=True)
    write(LOCK, json.dumps({"run_id": a.run_id, "started": time.time(),
                            "deadline": time.time() + a.max_seconds, "hb_timeout": a.heartbeat_timeout}))
    write(HB, "")
    mons = monitors()
    saved = {
        "backlight": num(BL),
        "ab_off_existed": os.path.exists(AB_OFF),
        "stay_awake_existed": os.path.exists(STAY),
        "dpms_on": bool(mons) and all(m.get("dpmsStatus") for m in mons),
        "autobrightness_bias": rd("/var/lib/loa/autobrightness.json"),
        "backlight_fixed": a.backlight,
    }
    write(SAVED, json.dumps(saved))
    unit("watchdog", [sys.executable, os.path.abspath(__file__), "watchdog"], user=False)
    # Idle: hypridle honours a systemd idle inhibitor, which ends with its process.
    unit("inhibit", ["systemd-inhibit", "--what=idle", f"--who={CLIENT}", "--why=power test",
                     "sleep", "infinity"], user=False)
    if not saved["stay_awake_existed"]:
        as_user("omarchy-toggle-idle", "stay-awake")  # Omarchy's screensaver timer
    write(AB_OFF, "")
    time.sleep(0.5)  # loa-autobrightness checks the flag every 100 ms
    dpms(True)
    time.sleep(0.5)
    close_screensaver()
    write(BL, str(a.backlight))
    out({"ok": True, "logdir": logdir, "saved": {k: v for k, v in saved.items() if k != "autobrightness_bias"},
         "conditions": conditions(), "power": power()})


def restore(reason):
    """Undo everything a run changed. Safe to run more than once."""
    log = []
    p = input_resume_verified() if num(f"{CHG}/suspend_status") != 0 or os.path.exists(SUSP) else power()
    log.append("input resumed" if p else "input resume NOT confirmed")
    if os.path.exists(SUSP):
        os.unlink(SUSP)
    stop_units(*UNITS)
    # A test process that escaped its unit (should not happen) still goes.
    subprocess.run(["pkill", "-f", f"{BASE}/(chromium|project|pi)"], stderr=subprocess.DEVNULL)
    shutil.rmtree(PIDIR, ignore_errors=True)
    shutil.rmtree(WORK, ignore_errors=True)
    s = json.loads(rd(SAVED) or "{}")
    if s:
        if s.get("dpms_on") is False:
            pass  # hypridle switches it off again on its own once the inhibitor is gone
        if s.get("backlight") is not None:
            write(BL, str(s["backlight"]))
        if not s.get("stay_awake_existed"):
            as_user("omarchy-toggle-idle", "allow-idle")
        if not s.get("ab_off_existed"):
            time.sleep(0.3)
            if os.path.exists(AB_OFF):
                os.unlink(AB_OFF)
    stop_units("inhibit")
    for f in (SAVED, HB, LOCK, HOLDER):
        if os.path.exists(f):
            os.unlink(f)
    log.append(f"restored ({reason})")
    os.makedirs(LOGROOT, exist_ok=True)
    with open(f"{LOGROOT}/restore.log", "a") as f:
        f.write("%s %s: %s\n" % (time.strftime("%Y-%m-%dT%H:%M:%S"), reason, "; ".join(log)))
    return p


def cmd_end(a):
    lock = rd(LOCK)
    p = restore(a.reason)
    stop_units("watchdog")
    out({"ok": p is not None, "had_lock": lock is not None, "power": power(), "hypridle": hypridle_ok()})


def hypridle_ok():
    return subprocess.run(["pgrep", "-x", "hypridle"], capture_output=True).returncode == 0


def cmd_hb(a):
    if os.path.exists(LOCK):
        os.utime(HB) if os.path.exists(HB) else write(HB, "")
    tail = (rd(f"{LOGROOT}/restore.log") or "").splitlines()[-1:]
    out({"active": os.path.exists(LOCK), "watchdog": unit_active("watchdog"),
         "units": {u: unit_active(u) for u in UNITS}, "last_restore": tail[0] if tail else None, **power()})


def cmd_hold(a):
    """Held open by the runner over ssh; every line is a heartbeat. End of file
    means the runner is gone, unless a newer session has taken over (a session
    that died with a USB link drop is replaced by a new one)."""
    import select
    write(HOLDER, a.id)
    while True:
        r, _, _ = select.select([sys.stdin], [], [], 5)
        if not r:
            continue
        line = sys.stdin.readline()
        if line:
            if os.path.exists(LOCK):
                os.utime(HB) if os.path.exists(HB) else write(HB, "")
            continue
        # A session lost with the USB link is replaced by a new one within seconds of
        # the link's return; give a successor 20 s before calling the runner gone.
        time.sleep(20)
        if rd(HOLDER) == a.id and os.path.exists(LOCK):
            restore("runner gone: its session closed")
            stop_units("watchdog")
        return


def cmd_watchdog(a):
    while True:
        time.sleep(5)
        lk = rd(LOCK)
        if lk is None:
            return
        try:
            lock = json.loads(lk)
        except ValueError:
            lock = {}
        now = time.time()
        try:
            hb_age = now - os.path.getmtime(HB)
        except OSError:
            hb_age = 1e9
        reason = None
        if hb_age > lock.get("hb_timeout", 180):
            reason = "watchdog: no heartbeat for %.0f s" % hb_age
        elif now > lock.get("deadline", now + 1):
            reason = "watchdog: run overran its time"
        elif os.path.exists(SUSP):
            sd = json.loads(rd(SUSP) or "{}")
            cap = num(f"{PS}/battery/capacity") or 100
            if cap < 30:
                reason = "watchdog: charge below 30 %"
            elif now > sd.get("deadline", now + 1) or (sd.get("until_capacity") and cap <= sd["until_capacity"]):
                # The end of a suspend the runner asked for (a block or a drain): the
                # tablet resumes the input itself, so a USB link drop cannot extend it.
                p = input_resume_verified()
                if os.path.exists(SUSP):
                    os.unlink(SUSP)
                with open(f"{LOGROOT}/restore.log", "a") as f:
                    f.write("%s watchdog: suspend ended (%s), input %s\n" % (
                        time.strftime("%Y-%m-%dT%H:%M:%S"),
                        "charge target" if now <= sd.get("deadline", now + 1) else "deadline",
                        "resumed" if p else "resume NOT confirmed"))
        if reason:
            restore(reason)
            return


# ---------------------------------------------------------------- services and workloads

def git(*args):
    return subprocess.run(["setpriv", "--reuid=1000", "--regid=1000", "--init-groups", "git", "-C", PROJECT, *args],
                          env=USER_ENV, capture_output=True, text=True, timeout=30)


def reset_project():
    git("checkout", "-q", "--", ".")
    git("clean", "-q", "-fd", "-e", "node_modules")
    st = git("status", "--porcelain").stdout.strip()
    if st:
        die("project not clean after reset: " + st[:200])


def cdp(*args, timeout=90):
    r = subprocess.run(["setpriv", "--reuid=1000", "--regid=1000", "--init-groups",
                        "node", f"{SRC}/tablet/cdp.mjs", *args],
                       env=USER_ENV, capture_output=True, text=True, timeout=timeout)
    return r.returncode, (r.stdout + r.stderr).strip()


def cmd_services(a):
    if a.what == "stop":
        stop_units(*UNITS)
        out({"ok": True})
        return
    stop_units(*UNITS)
    reset_project()
    unit("vite", ["node", "node_modules/vite/bin/vite.js", "--host", "127.0.0.1", "--port", "5173", "--strictPort"],
         cwd=PROJECT)
    unit("term", ["foot", "--app-id=loa-powertest-term", f"--working-directory={PROJECT}"])
    time.sleep(2)
    unit("chromium", ["chromium", f"--user-data-dir={BASE}/chromium", "--remote-debugging-port=9222",
                      "--remote-debugging-address=127.0.0.1", "--no-first-run", "--no-default-browser-check",
                      "--hide-crash-restore-bubble", "--disable-background-networking",
                      "--disable-component-update", "--password-store=basic", "--new-window",
                      "http://127.0.0.1:5173/"])
    rc, msg = cdp("wait-page", "--timeout", "90", timeout=150)
    if rc != 0:
        stop_units(*UNITS)
        die("preview page not up: " + msg[-300:])
    out({"ok": True, "units": {u: unit_active(u) for u in UNITS}})


def cmd_block(a):
    logdir = f"{LOGROOT}/{json.loads(rd(LOCK) or '{}').get('run_id', 'none')}"
    res = f"{logdir}/{a.tag}.result.json"
    if a.what == "start":
        if not os.path.exists(LOCK):
            die("no run is active")
        if not all(unit_active(u) for u in ("vite", "chromium", "term")):
            die("services are not running")
        # Same start state for every repeat: replay and agent begin from the pristine project.
        reset_project()
        rc, msg = cdp("reload", timeout=40)
        if rc != 0:
            die("reload before the block failed: " + msg[-200:])
        until = time.time() + a.seconds
        start = {"workload": a.workload, "t_start": time.time(), "seconds": a.seconds, **meminfo(), **power()}
        write(f"{logdir}/{a.tag}.start.json", json.dumps(start))
        unit("powerlog", [sys.executable, f"{SRC}/loa-powerlog.py", "run", "--out", f"{logdir}/{a.tag}.jsonl",
                          "--interval", str(a.interval), "--sample", str(a.sample)], user=False)
        unit("blockend", ["sh", "-c", f"sleep {a.seconds:.0f}; exec {sys.executable} {os.path.abspath(__file__)} "
                                      f"block stop --tag {a.tag} --resume"], user=False)
        if a.workload == "replay":
            unit("driver", ["node", f"{SRC}/tablet/cdp.mjs", "replay", "--project", PROJECT,
                            "--edits", f"{SRC}/edits.json", "--period", str(a.period),
                            "--step", a.step, "--work", WORK,
                            "--until", str(until), "--out", f"{WORK}/driver.json"])
        elif a.workload == "agent":
            unit("driver", [sys.executable, os.path.abspath(__file__), "agent-loop", "--until", str(until),
                            "--out", f"{WORK}/driver.json"], user=False)
        out({"ok": True, **start})
        return
    # stop
    powerlog_running = unit_active("powerlog")  # False: it died before the block's end
    stop_units("driver")
    time.sleep(1)
    stop_units("powerlog")
    drv = json.loads(rd(f"{WORK}/driver.json") or "{}")
    if os.path.exists(f"{WORK}/driver.json"):
        os.unlink(f"{WORK}/driver.json")
    start = json.loads(rd(f"{logdir}/{a.tag}.start.json") or "{}")
    mons = monitors()
    r = {"start": start, "end": {"t_end": time.time(), **meminfo(), **power(), "backlight": num(BL),
                                 "powerlog_running": powerlog_running,
                                 "screen_on": bool(mons) and all(m.get("dpmsStatus") for m in mons),
                                 "screensaver": subprocess.run(["pgrep", "-f", "org.omarchy.screensaver"],
                                                               capture_output=True).returncode == 0},
         "driver": drv}
    write(res, json.dumps(r))
    if a.resume:
        p = input_resume_verified()
        if os.path.exists(SUSP):
            os.unlink(SUSP)
        r["resumed"] = p is not None
    out(r)


# ---------------------------------------------------------------- agent

def llm_env():
    env = {}
    for line in (rd(LLM_ENV) or "").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip().removeprefix("export ").strip()] = v.strip().strip("'\"")
    return env


def pi_config():
    """models.json for Pi in a root-made, user-readable tmpfs directory. The key stays an
    environment reference; baseUrl has no interpolation in Pi's documentation."""
    e = llm_env()
    os.makedirs(PIDIR, mode=0o700, exist_ok=True)
    cfg = {"providers": {"loa": {
        "baseUrl": e["LLM_BASE_URL"], "api": "openai-completions", "apiKey": "$LLM_API_KEY",
        "models": [{"id": e["LLM_MODEL"], "contextWindow": 32768, "maxTokens": 8192,
                    "samplingParams": {"temperature": 0}}],
    }}}
    write(f"{PIDIR}/models.json", json.dumps(cfg))
    write(f"{PIDIR}/settings.json", json.dumps({"quietStartup": True}))
    for p in (PIDIR, f"{PIDIR}/models.json", f"{PIDIR}/settings.json"):
        os.chown(p, 1000, 1000)
        os.chmod(p, 0o700 if p == PIDIR else 0o600)
    return e


def run_pi(prompt, deadline, e):
    """One Pi run in the project; returns counts only (never Pi's text)."""
    env = dict(USER_ENV, PI_CODING_AGENT_DIR=PIDIR, PI_OFFLINE="1", LLM_API_KEY=e["LLM_API_KEY"])
    argv = ["setpriv", "--reuid=1000", "--regid=1000", "--init-groups", PI, "--mode", "json", "--no-session",
            "--provider", "loa", "--model", e["LLM_MODEL"], "--no-approve", prompt]
    st = {"turns": 0, "tool_calls": 0, "tool_errors": 0, "input_tokens": 0, "output_tokens": 0,
          "retries": 0, "errors": 0, "http_503": False, "finished": False, "rc": None}
    t0 = time.time()
    errf = open(f"{RUN}/pi.stderr", "w+b")
    p = subprocess.Popen(argv, cwd=PROJECT, env=env, stdout=subprocess.PIPE, stderr=errf,
                         start_new_session=True)
    os.set_blocking(p.stdout.fileno(), False)
    buf = b""
    while True:
        if time.time() > deadline:
            os.killpg(p.pid, signal.SIGTERM)
            try:
                p.wait(5)
            except subprocess.TimeoutExpired:
                os.killpg(p.pid, signal.SIGKILL)
            st["cut_at_deadline"] = True
            break
        try:
            chunk = p.stdout.read()
        except BlockingIOError:
            chunk = None
        if chunk:
            buf += chunk
            *lines, buf = buf.split(b"\n")
            for line in lines:
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                t = ev.get("type")
                if t == "turn_end":
                    st["turns"] += 1
                elif t == "tool_execution_end":
                    st["tool_calls"] += 1
                    st["tool_errors"] += bool(ev.get("isError"))
                elif t == "auto_retry_start":
                    st["retries"] += 1
                    st["http_503"] |= "503" in str(ev.get("errorMessage", ""))
                elif t == "message_end" and (ev.get("message") or {}).get("role") == "assistant":
                    m = ev["message"]
                    u = m.get("usage") or {}
                    st["input_tokens"] += u.get("input", 0) or 0
                    st["output_tokens"] += u.get("output", 0) or 0
                    if m.get("stopReason") == "error":
                        st["errors"] += 1
                        st["http_503"] |= "503" in str(m.get("errorMessage", ""))
                elif t == "agent_settled":
                    st["finished"] = not ev.get("aborted")
        if p.poll() is not None and not chunk:
            break
        if not chunk:
            time.sleep(0.2)
    st["rc"] = p.wait()
    errf.seek(0)
    errtail = errf.read()[-4000:]
    errf.close()
    os.unlink(f"{RUN}/pi.stderr")
    st["http_503"] |= b" 503" in errtail
    st["stderr_bytes"] = len(errtail)
    st["seconds"] = round(time.time() - t0, 1)
    return st


def cmd_agent_loop(a):
    e = pi_config()
    prompt = rd(f"{SRC}/prompt.txt")
    res = {"runs": [], "failed": False}

    def save():
        write(a.out + ".tmp", json.dumps(res))
        os.replace(a.out + ".tmp", a.out)

    signal.signal(signal.SIGTERM, lambda *_: (save(), sys.exit(0)))
    while time.time() < a.until - 20:
        st = run_pi(prompt, a.until, e)
        if not st.get("cut_at_deadline"):
            rc, _ = cdp("reload", timeout=40)  # look at the result, as a person would
            st["reload_rc"] = rc
        res["runs"].append(st)
        if st["http_503"] or st["errors"] or st["retries"] or (st["rc"] not in (0, None) and not st.get("cut_at_deadline")):
            res["failed"] = True
            save()
            break  # a failed repeat: the runner discards and reruns it
        save()
        if time.time() < a.until - 20:
            reset_project()
    # Idle until the end of the block if the loop stopped early.
    save()
    while time.time() < a.until:
        time.sleep(1)


def cmd_warmup(a):
    """One small request so the endpoint is warm; prints the status and latency only."""
    e = llm_env()
    body = json.dumps({"model": e["LLM_MODEL"], "temperature": 0, "max_tokens": 8,
                       "messages": [{"role": "user", "content": "Reply with OK."}]})
    t0 = time.time()
    r = subprocess.run(["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "--noproxy", "*", "-m", "150",
                        "-H", "Content-Type: application/json", "-H", "@-",
                        "-d", body, e["LLM_BASE_URL"].rstrip("/") + "/chat/completions"],
                       input=f"Authorization: Bearer {e['LLM_API_KEY']}\n", capture_output=True, text=True)
    out({"http": r.stdout.strip(), "seconds": round(time.time() - t0, 1)})


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("begin")
    b.add_argument("--run-id", required=True)
    b.add_argument("--max-seconds", type=float, required=True)
    b.add_argument("--backlight", type=int, default=820)
    b.add_argument("--heartbeat-timeout", type=float, default=180)
    sub.add_parser("hb")
    i = sub.add_parser("input")
    i.add_argument("what", choices=("suspend", "resume"))
    i.add_argument("--max-seconds", type=float, default=900)
    i.add_argument("--until-capacity", type=int, help="resume by itself at this charge level (drain)")
    d = sub.add_parser("display")
    d.add_argument("what", choices=("on", "off"))
    l = sub.add_parser("backlight")
    l.add_argument("raw", type=int)
    s = sub.add_parser("services")
    s.add_argument("what", choices=("start", "stop"))
    k = sub.add_parser("block")
    k.add_argument("what", choices=("start", "stop"))
    k.add_argument("workload", nargs="?", choices=("idle", "replay", "agent"))
    k.add_argument("--seconds", type=float, default=600)
    k.add_argument("--tag", required=True)
    k.add_argument("--interval", type=float, default=10)
    k.add_argument("--sample", type=float, default=1)
    k.add_argument("--period", type=float, default=30)
    k.add_argument("--step", choices=("none", "build", "test"), default="none",
                   help="replay: extra work in every cycle")
    k.add_argument("--resume", action="store_true", help="stop: resume the charger input afterwards")
    sub.add_parser("conditions")
    sub.add_parser("warmup")
    e = sub.add_parser("end")
    e.add_argument("--reason", default="end of run")
    sub.add_parser("watchdog")
    h = sub.add_parser("hold")
    h.add_argument("--id", required=True)
    g = sub.add_parser("agent-loop")
    g.add_argument("--until", type=float, required=True)
    g.add_argument("--out", required=True)
    a = p.parse_args()
    {"begin": cmd_begin, "hb": cmd_hb, "input": cmd_input, "display": cmd_display, "backlight": cmd_backlight, "services": cmd_services,
     "block": cmd_block, "conditions": cmd_conditions, "warmup": cmd_warmup, "end": cmd_end,
     "watchdog": cmd_watchdog, "hold": cmd_hold, "agent-loop": cmd_agent_loop}[a.cmd](a)


if __name__ == "__main__":
    main()
