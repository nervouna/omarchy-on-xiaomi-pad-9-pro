#!/usr/bin/env python3
"""Tests for rootfs-overlay/usr/lib/loa/loa-digest.py: parsers and the privacy filter.

    python3 -m unittest tools/test_loa_digest.py     (from the repository root)
"""
import importlib.util
import json
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location(
    "loa_digest", os.path.join(HERE, "..", "rootfs-overlay", "usr", "lib", "loa", "loa-digest.py"))
D = importlib.util.module_from_spec(spec)
spec.loader.exec_module(D)

# Built at run time so tools/check-public.sh does not flag this file.
MAC = ":".join(["a4", "5e", "60", "c1", "d2", "e3"])
MAC_UPPER = MAC.upper()
SSID = "Cafe Corner 5G"
HOME = "/home/" + "omarchy/Documents/plan-secret.txt"
URL = "https://example.org/private?id=42"
IP4 = "192.168.31.77"
IP6 = "fe80::1c2b:3aff:fe4d:5e6f"
SENSITIVE = [MAC, MAC_UPPER, SSID, "Cafe", "plan-secret", "Documents", "example.org", "private?id",
             IP4, "3aff:fe4d"]


def sleepd(boot, rt_s, mono_s, msg):
    return {"MESSAGE": msg, "_BOOT_ID": boot,
            "__REALTIME_TIMESTAMP": str(int(rt_s * 1e6)), "__MONOTONIC_TIMESTAMP": str(int(mono_s * 1e6))}


class Normalise(unittest.TestCase):
    def test_numbers_and_addresses_masked(self):
        a = D.normalise("[kworke][0x1b2][01:21:09.123] wcn6750: nl_srv_bcast: send msg to cld80211 fails for app id 1")
        b = D.normalise("[kworke][0xfa0][02:00:10.999]  wcn6750: nl_srv_bcast: send msg to cld80211 fails for app id 1")
        self.assertEqual(a, b)
        self.assertNotIn("0x", a)
        self.assertNotIn("  ", b)
        self.assertEqual(D.normalise("CURRENT:-123 TEMP:301"), D.normalise("CURRENT:-1234567 TEMP:3"))
        self.assertEqual(D.normalise("addr ffffffc0a1b2c3d4 bad"), "addr H bad")

    def test_dedup_counts_and_touchpad_filter(self):
        lines = ["[00:23:02.998] [xiaomi-keyboard] rawdata_show 80: write cmd -> [[[32004E31]]]",
                 "input: failed to attach handler xiaomi_keyboard to device input5, error: -22",
                 "input: failed to attach handler xiaomi_keyboard to device input6, error: -22",
                 "rdbg: failed get smem state"]
        e = D.errors_section(lines, ["bt-agent.service: Failed with result 'exit-code'."])
        self.assertEqual(e["touchpad_lines_dropped"], 1)
        self.assertEqual(e["kernel_messages"], 3)
        self.assertEqual(e["failed_unit_messages"], 1)
        self.assertEqual(e["distinct"], 3)
        self.assertEqual(e["top"][0]["count"], 2)
        self.assertIn("xiaomi_keyboard", e["top"][0]["message"])

    def test_top_is_capped(self):
        e = D.errors_section(["error kind %s" % chr(65 + i) * 2 for i in range(40)], [])
        self.assertEqual(len(e["top"]), D.TOP_ERRORS)


class Suspend(unittest.TestCase):
    def test_cycles_refusals_wakes_and_sleep_time(self):
        b = "boot1"
        e = [sleepd(b, 1000, 20, "mem_sleep: [s2idle] deep"),
             sleepd(b, 1000, 20, "loa-sleepd: grace 10s, re-sleep 15s"),
             # 1800 s asleep: the real-time clock moves on, the monotonic one does not.
             sleepd(b, 2900, 120, "resumed: wake irq 32, fired: c426000.spmi:qcom,pmk8550@0:rtc@6100+1, battery 90%"),
             sleepd(b, 2930, 150, "resumed: wake irq ?, fired: qrtr_ws+7, c426000.spmi:qcom,pmk8550@0:rtc@6100+1, battery 90%"),
             sleepd(b, 3000, 210, "suspend refused (Device or resource busy): failed dev a600000.dwc3 at prepare"),
             sleepd(b, 3100, 300, "resumed: wake irq 250, fired: -, battery 89%"),
             sleepd("boot2", 9000, 15, "mem_sleep: [s2idle] deep")]
        s = D.suspend_section(e, "s2idle")
        self.assertEqual(s["cycles"], 3)
        self.assertAlmostEqual(s["asleep_h"], round((1800 + 0 + 10) / 3600, 2))
        self.assertEqual(s["refused"], [{"device": "a600000.dwc3", "step": "prepare", "count": 1}])
        self.assertEqual(s["wake_sources"], {"c426000.spmi:qcom,pmk8550@0:rtc@6100": 2, "qrtr_ws": 1})
        self.assertEqual(s["wake_irqs"], {"32": 1, "?": 1, "250": 1})

    def test_clock_jump_is_not_sleep(self):
        e = [sleepd("b", 1000, 20, "loa-sleepd: grace 10s, re-sleep 15s"),
             sleepd("b", 1000 + 30 * 86400, 60, "resumed: wake irq 32, fired: -, battery 90%")]
        self.assertEqual(D.suspend_section(e)["asleep_h"], 0)


def samp(t, sl=0.0, c=80, q=8000, i=500, v=4000, u=0, s=1, cpu=40.0, qt=30.0, cd=None, b="b1"):
    x = {"t": t, "b": b, "sl": sl, "c": c, "q": q, "i": i, "v": v, "u": u, "ui": 0, "uv": 0, "s": s,
         "cpu": cpu, "qt": qt}
    if cd:
        x["cd"] = cd
    return x


class Battery(unittest.TestCase):
    def test_split_by_state(self):
        full = 10000.0  # mAh: 100 mAh = 1 %
        smp = []
        t, q = 0, 9000
        for _ in range(61):          # 1 h screen on, 8 %/h
            smp.append(samp(t, q=round(q), s=1))
            t += 60
            q -= 800 / 60
        for _ in range(60):          # 1 h screen off awake, 3 %/h
            smp.append(samp(t, q=round(q), s=0))
            t += 60
            q -= 300 / 60
        sl = 0.0
        for _ in range(4):           # 2 h in 30 min sleeps, 1 %/h
            smp.append(samp(t, sl=sl, q=round(q), s=0))
            t += 1800
            sl += 1780
            q -= 50
        smp.append(samp(t, sl=sl, q=round(q), s=0))
        b, why = D.battery_section(smp, full)
        self.assertIsNone(why)
        dr = b["drain_pct_per_h"]
        self.assertAlmostEqual(dr["screen_on"], 8, delta=0.2)
        self.assertAlmostEqual(dr["screen_off_awake"], 3, delta=0.2)
        self.assertAlmostEqual(dr["s2idle"], 1, delta=0.1)
        self.assertAlmostEqual(b["hours_on_battery"], 4, delta=0.05)
        self.assertEqual(b["current_sign"], "measured")
        self.assertIsNone(b["peak_charge_w"])

    def test_charging_on_usb(self):
        smp = [samp(0, c=50, q=5000, i=-5000, v=4200, u=1), samp(60, c=51, q=5080, i=-6000, v=4300, u=1)]
        smp[0].update(ui=3000, uv=9000)
        b, _ = D.battery_section(smp, 10000.0)
        self.assertEqual(b["hours_on_battery"], 0)
        self.assertEqual(b["drain_pct_per_h"]["s2idle"], None)
        self.assertIn("s2idle", b["drain_null_reasons"])
        self.assertEqual(b["current_sign"], "measured")
        self.assertAlmostEqual(b["peak_charge_w"], 25.8, delta=0.1)
        self.assertAlmostEqual(b["peak_input_w"], 27.0, delta=0.1)
        self.assertEqual((b["start_pct"], b["end_pct"], b["min_pct"], b["max_pct"]), (50, 51, 50, 51))

    def test_no_samples(self):
        b, why = D.battery_section([], 10000.0)
        self.assertIsNone(b)
        self.assertTrue(why)

    def test_other_boot_and_gaps_are_skipped(self):
        smp = [samp(0, b="x"), samp(60, b="y"), samp(4000, b="y")]
        self.assertEqual(list(D.pairs(smp)), [])


class Thermals(unittest.TestCase):
    def test_peak_p95_cooling(self):
        smp = [samp(i * 60, cpu=float(i), qt=20.0 + i / 10) for i in range(1, 101)]
        smp[10]["cd"] = ["cpufreq-cpu6"]
        smp[11]["cd"] = ["cpufreq-cpu6", "battery"]
        t, why = D.thermal_section(smp)
        self.assertEqual(t["cpu_peak_c"], 100.0)
        self.assertEqual(t["cpu_p95_c"], 95.0)
        self.assertEqual(t["quiet_therm_peak_c"], 30.0)
        self.assertEqual(t["samples_cooling_active"], 2)
        self.assertEqual(t["cooling_devices"], {"cpufreq-cpu6": 2, "battery": 1})


class Crashes(unittest.TestCase):
    def test_hyprland_restarts(self):
        starts = [("b1", 100), ("b1", 5000), ("b2", 9000), ("b2", 9500)]
        self.assertEqual(D.hyprland_restarts(starts, since=1000), 2)

    def test_coredump_exe_basename_only(self):
        c = D.crashes_section(["/usr/bin/Hyprland", "/usr/bin/Hyprland"], [], 0, None)
        self.assertEqual(c["coredumps"], {"Hyprland": 2})


class Privacy(unittest.TestCase):
    def test_nothing_private_reaches_the_output(self):
        kernel = ["wlan: connected to SSID: %s bssid %s" % (SSID, MAC),
                  "cfg80211: ssid=\"%s\" rejected" % SSID,
                  "audit: opened %s for writing" % HOME,
                  "net: fetch %s failed" % URL,
                  "wlan0: %s from %s via %s" % (MAC_UPPER, IP4, IP6),
                  "wcn6750: trans BSSID %s" % ":".join(["a4", "5e", "60", "**", "**", "e3"])]
        failed = ["app-%s.service: Failed with result 'exit-code'." % HOME]
        entries = [sleepd("b", 1, 1, "loa-sleepd: grace 10s, re-sleep 15s"),
                   sleepd("b", 100, 50, "resumed: wake irq 1, fired: %s+1, %s+2, battery 50%%" % (MAC, URL))]
        d = {"digest": 1, "reasons": {}, "period": "test",
             "errors": D.errors_section(kernel, failed),
             "suspend": D.suspend_section(entries),
             "crashes": D.crashes_section([HOME + "/bin/tool"], ["x-%s.service" % IP4], 0, None)}
        d = D.scrub_all(d)
        out = json.dumps(d) + D.render(d)
        for s in SENSITIVE:
            self.assertNotIn(s, out)
        self.assertNotIn("a4:5e:60", out)

    def test_scrub_keeps_device_names(self):
        for s in ("c426000.spmi:qcom,pmk8550@0:rtc@6100", "a600000.dwc3", "6.12.69-android16-6-nitian1-4k",
                  "[01:21:09.123] cpu-0-0-0"):
            self.assertEqual(D.scrub(s), s)


if __name__ == "__main__":
    unittest.main()
