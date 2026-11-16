// Unit tests of the test project, run by the replay's `test` step in every cycle:
//   LOA_PROJECT=/opt/loa-powertest/project node --test project.test.mjs
// They hold for every state the replay's edits put the project in (edits.json
// changes the row count, the price format and a part name), so a failure means
// the project is broken, not that an edit was applied.
import { test } from "node:test";
import assert from "node:assert/strict";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

const root = process.env.LOA_PROJECT || "/opt/loa-powertest/project";
const load = (f) => import(pathToFileURL(join(root, "src", f)).href + `?t=${Date.now()}`);

test("parts are generated the same way every time", async () => {
  const { parts } = await load("data.js");
  const a = parts();
  assert.ok(a.length >= 200);
  assert.deepEqual(parts(), a);
});

test("every part has a name, a bin, a count and a price in range", async () => {
  const { parts } = await load("data.js");
  for (const p of parts()) {
    assert.match(p.name, /^[a-z ]+ M[2-6]$/);
    assert.match(p.bin, /^B\d\d$/);
    assert.ok(Number.isInteger(p.count) && p.count >= 0 && p.count < 500);
    assert.ok(p.price >= 0 && p.price < 20);
  }
});

test("prices format with two decimals", async () => {
  const { formatPrice } = await load("format.js");
  for (const v of [0, 1, 2.5, 19.99, 1234.5]) {
    assert.match(formatPrice(v), new RegExp(v.toFixed(2).replace(".", "\\.")));
  }
});

test("the stock value is the sum over all parts", async () => {
  const { parts } = await load("data.js");
  const rows = parts();
  const total = rows.reduce((s, p) => s + p.count * p.price, 0);
  const again = rows.map((p) => p.count * p.price).sort((x, y) => x - y).reduce((s, x) => s + x, 0);
  assert.ok(Math.abs(total - again) < 1e-6 * Math.max(1, total));
  assert.ok(rows.filter((p) => p.count < 20).length > 0);
});
