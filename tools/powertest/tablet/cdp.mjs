#!/usr/bin/env node
// Drives the preview page in the test Chromium over its remote-debugging port.
//   cdp.mjs wait-page [--timeout 60]        wait until the preview page has loaded
//   cdp.mjs reload                          reload it and wait for the load event
//   cdp.mjs replay --project DIR --edits FILE --period S --until EPOCH_S --out FILE
// replay: every S seconds apply the next edit of a fixed list (forward through
// the list, then back), wait until the page shows it (hot update or reload by
// the dev server), reload the page, check again, then stay idle until the next
// slot. The summary (cycles, failures, timings) goes to --out as JSON.
import { readFileSync, writeFileSync, renameSync } from "node:fs";
import { join } from "node:path";

const PORT = 9222;
const PAGE = "http://127.0.0.1:5173/";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function args() {
  const a = { _: process.argv[2] };
  for (let i = 3; i < process.argv.length; i += 2) a[process.argv[i].replace(/^--/, "")] = process.argv[i + 1];
  return a;
}

async function pageTarget(timeoutMs) {
  const end = Date.now() + timeoutMs;
  for (;;) {
    try {
      const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
      const t = list.find((x) => x.type === "page" && x.url.startsWith(PAGE));
      if (t) return t.webSocketDebuggerUrl;
    } catch {}
    if (Date.now() > end) throw new Error("no preview page in the test Chromium");
    await sleep(500);
  }
}

class Cdp {
  constructor(url) {
    this.ws = new WebSocket(url);
    this.id = 0;
    this.wait = new Map();
    this.listeners = [];
    this.ws.onmessage = (e) => {
      const m = JSON.parse(e.data);
      if (m.id && this.wait.has(m.id)) {
        const { ok, ko } = this.wait.get(m.id);
        this.wait.delete(m.id);
        m.error ? ko(new Error(m.error.message)) : ok(m.result);
      } else if (m.method) {
        for (const l of this.listeners) l(m);
      }
    };
  }
  open() {
    return new Promise((ok, ko) => {
      this.ws.onopen = ok;
      this.ws.onerror = () => ko(new Error("CDP connection failed"));
    });
  }
  send(method, params = {}) {
    const id = ++this.id;
    this.ws.send(JSON.stringify({ id, method, params }));
    return new Promise((ok, ko) => this.wait.set(id, { ok, ko }));
  }
  once(method, timeoutMs) {
    return new Promise((ok, ko) => {
      const t = setTimeout(() => ko(new Error(`timeout waiting for ${method}`)), timeoutMs);
      const l = (m) => {
        if (m.method === method) {
          clearTimeout(t);
          this.listeners = this.listeners.filter((x) => x !== l);
          ok(m.params);
        }
      };
      this.listeners.push(l);
    });
  }
  close() {
    this.ws.close();
  }
}

async function connect(timeoutMs = 60000) {
  const c = new Cdp(await pageTarget(timeoutMs));
  await c.open();
  await c.send("Page.enable");
  await c.send("Runtime.enable");
  return c;
}

async function html(c) {
  try {
    const r = await c.send("Runtime.evaluate", {
      expression: "document.readyState === 'complete' ? document.documentElement.outerHTML.toLowerCase() : ''",
      returnByValue: true,
    });
    return r.result.value || "";
  } catch {
    return ""; // the page is navigating
  }
}

async function waitMark(c, mark, timeoutMs) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeoutMs) {
    if ((await html(c)).includes(mark)) return Date.now() - t0;
    await sleep(100);
  }
  return null;
}

async function reload(c, timeoutMs = 20000) {
  const t0 = Date.now();
  const loaded = c.once("Page.loadEventFired", timeoutMs);
  await c.send("Page.reload", { ignoreCache: false });
  await loaded;
  return Date.now() - t0;
}

async function replay(a) {
  const edits = JSON.parse(readFileSync(a.edits, "utf8"));
  const steps = [
    ...edits.map((e) => ({ file: e.file, from: e.old, to: e.new, mark: e.new_mark })),
    ...edits.slice().reverse().map((e) => ({ file: e.file, from: e.new, to: e.old, mark: e.old_mark })),
  ];
  const period = Number(a.period) * 1000;
  const until = Number(a.until) * 1000;
  const out = { cycles: 0, failed: 0, failures: [], hot_ms: [], reload_ms: [], started: Date.now() / 1000 };
  const save = () => {
    out.ended = Date.now() / 1000;
    writeFileSync(a.out + ".tmp", JSON.stringify(out));
    renameSync(a.out + ".tmp", a.out);
  };
  process.on("SIGTERM", () => {
    save();
    process.exit(0);
  });
  let c = await connect();
  const t0 = Date.now();
  for (let k = 0; ; k++) {
    const slot = t0 + k * period;
    if (slot + period > until) break; // only whole cycles
    if (Date.now() < slot) await sleep(slot - Date.now());
    const s = steps[k % steps.length];
    const path = join(a.project, s.file);
    const src = readFileSync(path, "utf8");
    let fail = null;
    if (!src.includes(s.from)) {
      fail = `edit ${k % steps.length}: text not found in ${s.file}`;
    } else {
      writeFileSync(path, src.replace(s.from, s.to));
      const hot = await waitMark(c, s.mark, 15000);
      if (hot === null) fail = `edit ${k % steps.length}: not shown after the change`;
      else {
        out.hot_ms.push(hot);
        try {
          out.reload_ms.push(await reload(c));
          if ((await waitMark(c, s.mark, 5000)) === null) fail = `edit ${k % steps.length}: not shown after reload`;
        } catch (e) {
          fail = `edit ${k % steps.length}: reload: ${e.message}`;
        }
      }
    }
    out.cycles++;
    if (fail) {
      out.failed++;
      out.failures.push(fail);
      try {
        c.close();
      } catch {}
      c = await connect(10000).catch(() => c);
    }
    save();
  }
  save();
  c.close();
}

const a = args();
if (a._ === "wait-page") {
  const c = await connect(Number(a.timeout || 60) * 1000);
  const ok = (await waitMark(c, "240 parts, stock value", 30000)) !== null;
  c.close();
  if (!ok) {
    console.error("the preview page did not render");
    process.exit(1);
  }
} else if (a._ === "reload") {
  const c = await connect(10000);
  console.log(JSON.stringify({ reload_ms: await reload(c) }));
  c.close();
} else if (a._ === "replay") {
  await replay(a);
} else {
  console.error("usage: cdp.mjs wait-page|reload|replay ...");
  process.exit(2);
}
process.exit(0);
