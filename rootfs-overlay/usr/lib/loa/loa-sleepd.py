#!/usr/bin/env python3
"""LoA suspend daemon: deep suspend (mem/deep) whenever the screen is off.

Android-style policy instead of a one-shot `systemctl suspend`:
  - screen off (power key / cover / idle) for GRACE s, on battery, no audio
    playing, no /run/loa-nosleep  ->  suspend;
  - a wake-up that does not turn the screen back on (stray Wi-Fi, RTC...)
    -> back to sleep after RESLEEP s;
  - the power key and the cover's hall sensor wake it; loa-power-key turns the
    screen on as usual.

Device quirks handled around each suspend (NOTES.md, 2026-09-27):
  - Bluetooth: the stock HAL's UART blocks suspend and the HAL wedges if BlueZ
    talks to it across suspend -> the BT stack is stopped before the first
    suspend of a screen-off period and started again once the screen is on.
  - Suspend mode s2idle (not the kernel default "deep"): deep resume fails to
    restore PMIC registers (temp-alarm init failed, GPIO restore failed), the
    display often stayed dark, and three thermistor channels came back ~+26 C
    (a false connector "anti-burn" then cuts USB power and charging). s2idle
    still reaches CX collapse + DDR self-refresh (qcom_stats cxsd/ddr).
  - Safety net: if the two connector thermistors disagree by > 15 C after a
    resume, rebind qcom-spmi-adc5-gen3 (reprograms the ADC channels).
  - Wi-Fi: radio off (nmcli) before the first suspend, on again with the
    screen. With wake-on-WLAN the firmware woke us every 3-5 s (the router
    unicasts IPv6 neighbor solicitations; Android filters them with APF);
    gEnableWoW=1 in the WCNSS ini crashes the WPSS firmware; and letting
    cfg80211 disconnect inside the suspend path raced the driver -> kernel oops.
We write /sys/power/state directly (systemd's AllowSuspend stays "no"): the
logind path would make NetworkManager tear Wi-Fi down on every sleep.
"""
import os, subprocess, time

GRACE, RESLEEP, BUSY_RETRY = 10, 15, 30
DPMS = "/sys/class/drm/card0-DSI-1/dpms"
USB_ONLINE = "/sys/class/power_supply/usb/online"
NOSLEEP = "/run/loa-nosleep"
ADC = "c426000.spmi:qcom,pmk8550@0:vadc@9000"
ADC_DRV = "/sys/bus/platform/drivers/qcom-spmi-adc5-gen3"
BT_UNITS = ["bluetooth", "loa-bluetooth", "loa-bthal"]

def rd(path, default=""):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return default

def wr(path, value):
    with open(path, "w") as f:
        f.write(value)

def log(*a):
    print(*a, flush=True)

def screen_on():
    return rd(DPMS, "On") == "On"

def audio_playing():
    if subprocess.run(["pidof", "agmplay"], capture_output=True).returncode == 0:
        return True                                  # speakers (loa-audio-relay)
    env = {"XDG_RUNTIME_DIR": "/run/user/1000", "PATH": "/usr/bin"}
    r = subprocess.run(["setpriv", "--reuid=1000", "--regid=1000", "--init-groups",
                        "pactl", "list", "short", "sinks"], env=env,
                       capture_output=True, text=True, timeout=5)
    return "RUNNING" in r.stdout                     # e.g. Bluetooth headphones

def blocker():
    if screen_on():
        return "screen on"
    if rd(USB_ONLINE, "0") == "1":
        return "USB power"                           # dwc3 refuses while attached
    if os.path.exists(NOSLEEP):
        return NOSLEEP
    try:
        if audio_playing():
            return "audio playing"
    except Exception as e:
        log("audio check failed:", e)
    return None

def run(*cmd):
    return subprocess.run(cmd, capture_output=True, text=True)

# "radios off" lives in /run so a restarted daemon still turns them back on.
RADIOS_OFF = "/run/loa-sleepd-radios-off"

def stop_radios():
    """Before the first suspend of a screen-off period: Wi-Fi off, BT stack off."""
    if not os.path.exists(RADIOS_OFF):
        open(RADIOS_OFF, "w").close()
        run("nmcli", "radio", "wifi", "off")
        run("systemctl", "stop", *BT_UNITS)
        time.sleep(3)                                # let Wi-Fi/BT UART go idle

def start_radios(force=False):
    if force or os.path.exists(RADIOS_OFF):
        run("nmcli", "radio", "wifi", "on")          # NM persists "off" across reboots
        run("systemctl", "--no-block", "start", *reversed(BT_UNITS))
        try:
            os.unlink(RADIOS_OFF)
        except FileNotFoundError:
            pass

IIO = "/sys/bus/iio/devices/iio:device0/"

def adc_offset_bad():
    try:
        a = int(rd(IIO + "in_temp_pm7550ba_conn_therm_input"))
        b = int(rd(IIO + "in_temp_pm8550_conn_therm2_input"))
        return abs(a - b) > 15000, a, b
    except ValueError:
        return False, None, None

def rebind_adc():
    try:
        wr(ADC_DRV + "/unbind", ADC)
        time.sleep(0.5)
        wr(ADC_DRV + "/bind", ADC)
    except OSError as e:
        log("ADC rebind failed:", e)

WS = "/sys/kernel/debug/wakeup_sources"

def ws_counts():
    out = {}
    # Tab-separated; names can contain spaces ("lock wake remoteproc").
    for line in rd(WS).splitlines()[1:]:
        f = [x for x in line.split("\t") if x != ""]
        if len(f) > 3:
            try:
                out[f[0].strip() + "#" + str(len(out))] = int(f[2])   # name#idx -> event_count
            except ValueError:
                pass
    return out

def ws_fired(before, after):
    fired = []
    for k, v in after.items():
        if k in before and v > before[k]:
            fired.append("%s+%d" % (k.split("#")[0], v - before[k]))
    return ", ".join(fired[:8]) or "-"

def suspend_once():
    """-> True if the system actually slept."""
    stop_radios()
    os.sync()
    before = int(rd("/sys/power/suspend_stats/success", "0"))
    ws0 = ws_counts()
    t0 = time.monotonic()
    try:
        wr("/sys/power/state", "mem")
    except OSError as e:
        log("suspend refused (%s): failed dev %s at %s" % (
            e.strerror, rd("/sys/power/suspend_stats/last_failed_dev"),
            rd("/sys/power/suspend_stats/last_failed_step")))
    slept = int(rd("/sys/power/suspend_stats/success", "0")) > before
    if slept:
        bad, a, b = adc_offset_bad()
        if bad:
            log("connector thermistors %s/%s m°C disagree -> rebinding ADC" % (a, b))
            rebind_adc()
        log("resumed: wake irq %s, fired: %s" % (
            rd("/sys/power/pm_wakeup_irq", "?"), ws_fired(ws0, ws_counts())))
    return slept

def main():
    try:
        wr("/sys/power/mem_sleep", "s2idle")
    except OSError as e:
        log("mem_sleep:", e)
    log("mem_sleep: %s" % rd("/sys/power/mem_sleep"))
    try:
        wr("/sys/power/pm_debug_messages", "1")   # logs the waking IRQ in s2idle
    except OSError:
        pass
    start_radios(force=True)                         # never leave radios off after a crash
    log("loa-sleepd: grace %ds, re-sleep %ds" % (GRACE, RESLEEP))
    off_since = None
    wait = GRACE
    while True:
        time.sleep(1)
        if screen_on():
            off_since = None
            wait = GRACE
            start_radios()
            continue
        now = time.monotonic()
        if off_since is None:
            off_since = now
        if now - off_since < wait:
            continue
        why = blocker()
        if why:
            off_since, wait = now, GRACE            # re-check later
            if why != "screen on":
                start_radios()                           # stay usable while awake
            continue
        slept = suspend_once()
        off_since = time.monotonic()
        wait = RESLEEP if slept else BUSY_RETRY

if __name__ == "__main__":
    main()
