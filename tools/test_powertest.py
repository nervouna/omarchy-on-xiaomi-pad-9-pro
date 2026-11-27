#!/usr/bin/env python3
"""Tests for tools/powertest/powertest.py: the report and the workload names.

    python3 -m unittest tools/test_powertest.py     (from the repository root)
"""
import importlib.util
import json
import os
import shutil
import tempfile
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("powertest", os.path.join(HERE, "powertest", "powertest.py"))
P = importlib.util.module_from_spec(spec)
spec.loader.exec_module(P)
tspec = importlib.util.spec_from_file_location("loa_powertest",
                                               os.path.join(HERE, "powertest", "tablet", "loa-powertest.py"))
T = importlib.util.module_from_spec(tspec)
tspec.loader.exec_module(T)


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


class ReportCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir)

    def make(self, meta):
        json.dump(meta, open(os.path.join(self.dir, "run.json"), "w"))
        text = P.report(self.dir)
        rj = open(os.path.join(self.dir, "report.json")).read()
        return text, rj

    def result_rows(self, text):
        return [x.split("|")[1].strip() for x in text.split("## Result")[1].split("## Blocks")[0].splitlines()
                if x.startswith("| ") and not x.startswith("| Workload")]


class Report(ReportCase):
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
        rows = self.result_rows(text)
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


class AgentSessionWorkload(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(P.parse_workload("agent-session", 30, "none"), ("agent-session", None, None))
        for bad in ("agent-session@10", "agent-session+build", "agent-sessions"):
            with self.assertRaises(ValueError):
                P.parse_workload(bad, 30, "none")

    def test_order(self):
        self.assertEqual(P.ordered(["idle", "agent-session", "replay", "agent"]),
                         ["agent", "agent-session", "idle", "replay"])

    def test_invalid_like_agent(self):
        for wl in ("agent", "agent-session"):
            self.assertIn("endpoint error", P.block_valid(block(wl, 1, 5.0, {"runs": [], "failed": False})))
            self.assertIn("endpoint error", P.block_valid(block(wl, 1, 5.0, {"runs": [{}], "failed": True})))
            self.assertIsNone(P.block_valid(block(wl, 1, 5.0, {"runs": [{}], "failed": False})))


def task(**kw):
    return {"finished": True, "turns": 4, "tool_calls": 5, "tool_errors": 0, "input_tokens": 1000,
            "output_tokens": 300, "retries": 0, "errors": 0, "http_503": False, **kw}


class ReportBothAgents(ReportCase):
    def test_side_by_side(self):
        agent = {"runs": [task(), task(), task(finished=False, tool_errors=1)], "failed": False}
        sess = {"runs": [task(), task()], "failed": False, "process_starts": 1}
        meta = run_json(["idle", "agent-session", "agent"],
                        [block("idle", 1, 4.6), block("agent", 1, 5.6, agent), block("agent-session", 1, 5.4, sess),
                         block("agent", 2, 5.8, agent), block("agent-session", 2, 5.5, sess)])
        text, rj = self.make(meta)
        rj = json.loads(rj)
        self.assertEqual(self.result_rows(text), ["agent", "agent-session", "idle"])
        self.assertIn("| agent-session | 2 | 5.45 |", text)
        self.assertIn("agent-session minus agent: -0.25 W", text)
        line = [x for x in text.splitlines() if x.startswith("| 3 | agent-session |")][0]
        self.assertIn("2 tasks (2 finished)", line)
        self.assertIn("1 Pi start", line)
        line = [x for x in text.splitlines() if x.startswith("| 2 | agent |")][0]
        self.assertIn("3 tasks (2 finished)", line)
        self.assertIn("3 Pi starts", line)
        self.assertIn("1 tool errors", line)
        c = rj["blocks"][2]["counts"]
        self.assertEqual(c, {"tasks": 2, "finished": 2, "turns": 8, "tool_calls": 10, "tool_errors": 0,
                             "input_tokens": 2000, "output_tokens": 600, "retries": 0, "errors": 0,
                             "http_503": False, "process_starts": 1})
        self.assertEqual(rj["blocks"][1]["counts"]["process_starts"], 3)
        self.assertNotIn("counts", rj["blocks"][0])

    def test_old_runs_without_new_counts(self):
        # A run recorded before tool errors and retries were counted still reports.
        agent = {"runs": [{"finished": True, "turns": 7, "tool_calls": 10, "input_tokens": 1000,
                           "output_tokens": 700}], "failed": False}
        self.assertIn("1 tasks (1 finished)", self.make(run_json(["agent"], [block("agent", 1, 5.6, agent)]))[0])


def cmd_run(test, ctl, workloads, **fakes):
    """P.cmd_run with its surroundings replaced (restored afterwards): run.json and ctl's calls."""
    out = tempfile.mkdtemp()
    test.addCleanup(shutil.rmtree, out)
    calls = []

    def recorded(args, timeout=180, check=True):
        calls.append(args.split()[0])
        return ctl(args)

    fake_sys = type("S", (), {"platform": "linux", "exit": staticmethod(SystemExit)})
    with mock.patch.multiple(P, ctl=recorded, preflight=lambda: {"hostname": "tablet"}, push=lambda: None,
                             report=lambda d: "report", log=lambda m: None, sys=fake_sys, **fakes):
        P.cmd_run(P.argparse.Namespace(
            window="70-90", workloads=workloads, period=4, replay_step="none", out=out, seconds=600, settle=30,
            repeats=1, max_attempts=1, backlight=820, heartbeat_timeout=300, agent_anytime=False))
    return json.load(open(os.path.join(out, "run.json"))), calls


class NightRule(unittest.TestCase):
    """The 00:00-08:00 rule holds for agent and agent-session alike."""

    def run_with(self, workloads, in_window):
        def ctl(args):
            if args.startswith("begin"):
                return {"logdir": "/x", "conditions": {}}
            if args.startswith("warmup"):
                return {"http": "200", "seconds": 1}
            return {}

        class Idle:
            def __init__(self):
                self.stop = P.threading.Event()
                self.quiet = P.threading.Event()
                self.last = {}

            def start(self):
                pass

            def is_alive(self):
                return False

        return cmd_run(self, ctl, workloads, Holder=Idle, Heartbeat=Idle, in_window=in_window,
                       wait_charge=lambda a, hb, state: 80, run_block=lambda *x: self.fail("a block ran"))

    def test_outside_window_skips_both(self):
        for wls in ("agent-session", "agent,agent-session"):
            meta, calls = self.run_with(wls, lambda start, seconds: False)
            self.assertEqual([b["skipped"] for b in meta["blocks"]],
                             ["skipped: endpoint not usable"] * len(wls.split(",")))
            self.assertNotIn("warmup", calls)
            self.assertTrue(any("outside the endpoint's window" in n for n in meta["notes"]))

    def test_block_ending_after_window_skips_both(self):
        meta, calls = self.run_with("agent,agent-session", lambda start, seconds: seconds == 0)
        self.assertEqual([b["skipped"] for b in meta["blocks"]], ["skipped: would end outside 00:00-08:00"] * 2)
        self.assertIn("warmup", calls)


class RunBeginFails(unittest.TestCase):
    def test_failed_begin_keeps_the_run_record(self):
        def ctl(args):
            if args.startswith("begin"):
                raise RuntimeError("ssh: connect failed")
            return {}

        meta, calls = cmd_run(self, ctl, "idle")
        self.assertIn("end", meta)
        self.assertTrue(any("ssh: connect failed" in n for n in meta["notes"]))
        self.assertEqual(calls, ["begin", "end"])


class Meminfo(unittest.TestCase):
    SAMPLE = ("MemTotal:        7864320 kB\nMemFree:          200000 kB\nMemAvailable:    4000000 kB\n"
              "SwapTotal:       2097152 kB\nSwapFree:        2097152 kB\n")

    def test_ram_mb_reads_memtotal(self):
        self.assertEqual(T.ram_mb(self.SAMPLE), 7680)

    def test_ram_mb_missing(self):
        self.assertIsNone(T.ram_mb(""))
        self.assertIsNone(T.ram_mb(None))

    def test_missing_software_message_names_setup(self):
        src = open(os.path.join(HERE, "powertest", "tablet", "loa-powertest.py")).read()
        self.assertIn("tools/powertest/powertest.py setup", src)
        self.assertNotIn("setup.sh first", src)


# A synthetic Pi event stream in the shape of Pi's docs/json.md (shared by JSON and RPC mode).
STREAM = [
    {"type": "agent_start"}, {"type": "turn_start"},
    {"type": "message_end", "message": {"role": "user", "content": "x"}},
    {"type": "message_end", "message": {"role": "assistant", "stopReason": "toolUse",
                                        "usage": {"input": 900, "output": 40}}},
    {"type": "tool_execution_end", "toolCallId": "c1", "toolName": "edit", "isError": False},
    {"type": "tool_execution_end", "toolCallId": "c2", "toolName": "bash", "isError": True},
    {"type": "turn_end", "message": {"role": "assistant"}, "toolResults": []},
    {"type": "auto_retry_start", "attempt": 1, "maxAttempts": 3, "errorMessage": "503 Service Unavailable"},
    {"type": "message_end", "message": {"role": "assistant", "stopReason": "stop",
                                        "usage": {"input": 1100, "output": 10}}},
    {"type": "turn_end", "message": {"role": "assistant"}, "toolResults": []},
    {"type": "agent_end", "messages": [], "willRetry": False},
    {"type": "agent_settled", "aborted": False},
]

FAKE_PI = r'''
import json, os, sys
open(os.environ["FAKE_STARTS"], "a").write("%d\n" % os.getpid())
mode = os.environ.get("FAKE_MODE", "")
if mode == "exit_idle":
    import threading
    threading.Timer(0.3, lambda: os._exit(3)).start()
msgs = 0
def send(r):
    sys.stdout.write(json.dumps(r) + "\n"); sys.stdout.flush()
for line in sys.stdin:
    c = json.loads(line)
    t, i = c["type"], c.get("id")
    if t == "prompt":
        if mode == "reject":
            send({"id": i, "type": "response", "command": "prompt", "success": False, "error": "no"})
            continue
        send({"id": i, "type": "response", "command": "prompt", "success": True, "data": {"disposition": "started"}})
        msgs += 2
        if mode == "503":
            sys.stderr.write("HTTP 503 Service Unavailable\n"); sys.stderr.flush()
        send({"type": "agent_start"})
        send({"type": "message_end", "message": {"role": "assistant", "stopReason": "toolUse",
                                                 "usage": {"input": 100, "output": 20}}})
        send({"type": "tool_execution_end", "toolCallId": "c", "toolName": "edit", "isError": False})
        send({"type": "turn_end", "message": {}, "toolResults": []})
        send({"type": "agent_settled", "aborted": False})
    elif t == "new_session":
        if mode == "mute":
            continue
        msgs = 0
        send({"id": i, "type": "response", "command": "new_session", "success": True, "data": {"cancelled": False}})
    elif t == "get_state":
        send({"id": i, "type": "response", "command": "get_state", "success": True,
              "data": {"model": {"id": "fake-model"}, "messageCount": msgs, "isStreaming": False}})
'''


class PiEvents(unittest.TestCase):
    def test_count_events(self):
        st = T.new_counts()
        for ev in STREAM:
            T.count_event(st, ev)
        self.assertEqual((st["turns"], st["tool_calls"], st["tool_errors"]), (2, 2, 1))
        self.assertEqual((st["input_tokens"], st["output_tokens"]), (2000, 50))
        self.assertEqual((st["retries"], st["http_503"], st["finished"]), (1, True, True))
        self.assertTrue(T.task_failed(st))

    def test_clean_task_is_not_failed(self):
        st = T.new_counts()
        for ev in STREAM:
            if ev["type"] != "auto_retry_start":
                T.count_event(st, ev)
        self.assertFalse(T.task_failed(st))


class PiSession(unittest.TestCase):
    """One fake Pi in RPC mode for a short block: one start, a new session after each task."""

    def loop(self, mode="", seconds=1.5, margin=0):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        fake = os.path.join(d, "fake-pi.py")
        open(fake, "w").write(FAKE_PI)
        starts = os.path.join(d, "starts")
        env = dict(os.environ, FAKE_STARTS=starts, FAKE_MODE=mode)
        resets = []
        res = {"runs": [], "failed": False}
        T.session_loop(lambda: T.PiRpc([T.sys.executable, fake], d, env, os.path.join(d, "pi.stderr")),
                       "PROMPT", time.time() + seconds, "fake-model", res, lambda: None,
                       reload=lambda: 0, reset=lambda: resets.append(1), margin=margin, ns_timeout=0.3)
        return res, open(starts).read().split(), resets

    def test_one_process_many_tasks(self):
        t0 = time.time()
        res, pids, resets = self.loop()
        self.assertGreaterEqual(time.time() - t0, 1.4)  # Pi stays up until the block's deadline
        self.assertEqual(len(pids), 1)
        self.assertEqual(res["process_starts"], 1)
        self.assertFalse(res["failed"])
        done = [r for r in res["runs"] if r["finished"]]
        self.assertGreaterEqual(len(done), 2)
        self.assertEqual(done[0]["turns"], 1)
        self.assertEqual(done[0]["input_tokens"], 100)
        # A new conversation after each reset (the last one may be cut by the block's end).
        self.assertGreaterEqual(res["new_sessions"], len(done) - 1)
        self.assertIn(len(resets) - res["new_sessions"], (0, 1))
        self.assertNotIn("new_session_failed", res)

    def test_rejected_prompt_fails_the_block(self):
        res, pids, _ = self.loop("reject", seconds=0.8)
        self.assertTrue(res["failed"])
        self.assertEqual(len(res["runs"]), 1)
        self.assertEqual(len(pids), 1)

    def test_unanswered_new_session_fails_the_block(self):
        res, _, resets = self.loop("mute", seconds=2)
        self.assertTrue(res["failed"])
        self.assertTrue(res["new_session_failed"]["no_answer"])
        self.assertEqual((len(res["runs"]), len(resets)), (1, 1))

    def test_503_on_stderr_fails_the_block(self):
        res, _, _ = self.loop("503", seconds=0.8)
        self.assertTrue(res["failed"])
        self.assertTrue(res["runs"][0]["http_503"])
        self.assertEqual(len(res["runs"]), 1)

    def test_pi_exiting_while_idle_fails_the_block(self):
        # No task fits (the margin is the whole block), so Pi only idles, and dies at 0.3 s.
        t0 = time.time()
        res, pids, _ = self.loop("exit_idle", seconds=1.5, margin=1.5)
        self.assertLess(time.time() - t0, 1.2)
        self.assertTrue(res["failed"])
        self.assertTrue(res["exited_early"])
        self.assertEqual((res["runs"], res["pi_rc"], len(pids)), ([], 3, 1))


if __name__ == "__main__":
    unittest.main()
