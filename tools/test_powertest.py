#!/usr/bin/env python3
"""Tests for tools/powertest/powertest.py: the report and the workload names.

    python3 -m unittest tools/test_powertest.py     (from the repository root)
"""
import importlib.util
import json
import os
import shutil
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("powertest", os.path.join(HERE, "powertest", "powertest.py"))
P = importlib.util.module_from_spec(spec)
spec.loader.exec_module(P)


def block(workload, rep, mean_w, driver=None):
    return {
        "workload": workload, "tag": f"{workload}-{rep}", "backlight": 820, "t": 1763250000 + 700 * rep,
        "power": {"mean_w": mean_w, "sd_within_w": 0.05, "records": 58, "covered_s": 580, "expected_s": 580,
                  "interval": 10, "usb_ua_max": 0, "min_bat_ua": 900000, "battery_c": [34.0, 35.0],
                  "cpu_max_c": 50.0, "slept_s": 0},
        "result": {"start": {"capacity": 88, "mem_used_mb": 3400, "swap_used_mb": 0},
                   "end": {"capacity": 86, "mem_used_mb": 3410, "swap_used_mb": 0}, "driver": driver or {}},
        "invalid": None, "usb_link_records": [58, 58],
    }


def run_json(workloads, blocks):
    return {
        "run_id": "test", "preflight": {"hostname": "tablet", "mem_mb": 7400},
        "args": {"workloads": workloads, "backlight": 820, "seconds": 600, "discard": 20, "interval": 10,
                 "sample": 1, "window": "85-90", "period": 30, "replay_step": "none"},
        "conditions": {"kernel": "k", "cpufreq": {}, "versions": {}},
        "blocks": blocks, "notes": [],
    }


class Report(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir)

    def make(self, meta):
        json.dump(meta, open(os.path.join(self.dir, "run.json"), "w"))
        text = P.report(self.dir)
        rj = open(os.path.join(self.dir, "report.json")).read()
        return text, rj

    def test_one_repeat_has_no_nan(self):
        replay = {"cycles": 19, "failed": 0, "hot_ms": [110], "reload_ms": [50]}
        agent = {"runs": [{"finished": True, "turns": 7, "tool_calls": 10, "input_tokens": 1000,
                           "output_tokens": 700}], "failed": False}
        meta = run_json(["idle", "replay", "agent"],
                        [block("idle", 1, 4.62), block("replay", 1, 4.70, replay), block("agent", 1, 5.64, agent)])
        text, rj = self.make(meta)
        self.assertNotIn("nan", text.lower())
        self.assertNotIn("nan", rj.lower())
        row = [x for x in text.splitlines() if x.startswith("| replay |")][0]
        self.assertEqual(row.split("|")[4].strip(), "-")
        json.loads(rj)  # strict JSON: NaN would not be written at all
        self.assertIsNone(json.loads(rj)["summary"]["replay"]["sd_w"])

    def test_agent_leads(self):
        agent = {"runs": [], "failed": False}
        meta = run_json(["idle", "replay", "agent"],
                        [block("idle", 1, 4.62), block("idle", 2, 4.63), block("agent", 1, 5.6, agent),
                         block("agent", 2, 5.7, agent)])
        text, _ = self.make(meta)
        rows = [x.split("|")[1].strip() for x in text.split("## Result")[1].split("## Blocks")[0].splitlines()
                if x.startswith("| ") and not x.startswith("| Workload")]
        self.assertEqual(rows[0], "agent")
        self.assertEqual(rows[1:], ["idle", "replay"])

    def test_replay_variant_rows(self):
        drv = {"cycles": 60, "failed": 0, "hot_ms": [110], "reload_ms": [50], "step": "build", "step_ms": [900],
               "step_failed": 0}
        meta = run_json(["replay+build@10"], [block("replay+build@10", 1, 5.2, drv),
                                              block("replay+build@10", 2, 5.3, drv)])
        text, _ = self.make(meta)
        self.assertIn("| replay+build@10 | 2 | 5.25 |", text)
        self.assertIn("build median 900 ms", text)


class Workloads(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(P.parse_workload("idle", 30, "none"), ("idle", None, None))
        self.assertEqual(P.parse_workload("replay", 30, "none"), ("replay", "none", 30.0))
        self.assertEqual(P.parse_workload("replay+build@10", 30, "none"), ("replay", "build", 10.0))
        self.assertEqual(P.parse_workload("replay@3", 30, "test"), ("replay", "test", 3.0))
        for bad in ("replay+make", "idle@10", "replay@x", "bogus"):
            with self.assertRaises(ValueError):
                P.parse_workload(bad, 30, "none")

    def test_invalid_step_failure(self):
        drv = {"cycles": 10, "failed": 1, "hot_ms": [], "reload_ms": [], "step": "build", "step_failed": 1}
        b = block("replay+build@10", 1, 5.0, drv)
        self.assertIn("failed", P.block_valid(b))


if __name__ == "__main__":
    unittest.main()
