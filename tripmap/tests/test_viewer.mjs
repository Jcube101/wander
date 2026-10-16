// Run: node --test tripmap/tests/test_viewer.mjs   (plain node, no dependencies)
// Tests the editor's pure helpers, extracted from the <script id="tripmap-pure"> block
// in viewer.html so the page stays a single file.
import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const html = readFileSync(new URL("../viewer.html", import.meta.url), "utf8");
const block = html.match(/<script id="tripmap-pure">([\s\S]*?)<\/script>/);
assert.ok(block, "viewer.html has no <script id=\"tripmap-pure\"> block");
const ctx = {};
vm.runInNewContext(block[1], ctx);
const { neighbours, fmtGap } = ctx.TripPure;

const MIN = 60, H = 3600;
const T0 = Date.UTC(2026, 2, 10, 10, 0) / 1000; // a 10:00 on day 2026-03-10 (UTC zone in these fixtures)
const day = t => new Date(t * 1000).toISOString().slice(0, 10);
// [id, minutes from T0, placed?, archived?]
const mk = rows => rows.map(([id, m, placed = true, archived = false]) => {
  const t = T0 + m * MIN;
  return { id, t, day: day(t), orig: `${id}.jpg`, ...(placed ? { lat: 1, lon: 2 } : {}), ...(archived ? { archived: true } : {}) };
});
const ids = r => ({ prev: r.prev?.x.id ?? null, next: r.next?.x.id ?? null, show: Array.from(r.show, n => n.x.id) }); // Array.from: vm arrays are from another realm

test("unplaced shot between two placed ones on the same day", () => {
  const items = mk([["a", -12], ["u", 0, false], ["b", 40]]);
  const r = neighbours(items, new Set(["u"]));
  assert.deepEqual(ids(r), { prev: "a", next: "b", show: ["a", "b"] });
  assert.equal(r.prev.gap, -12 * MIN);
  assert.equal(r.next.gap, 40 * MIN);
  assert.equal(r.prev.sameDay, true);
});

test("skips unplaced and archived shots, takes the nearest placed one", () => {
  const items = mk([["far", -90], ["arch", -20, true, true], ["u2", -10, false], ["u", 0, false], ["near", 5], ["far2", 50]]);
  assert.deepEqual(ids(neighbours(items, new Set(["u"]))), { prev: "far", next: "near", show: ["far", "near"] });
});

test("only one neighbour", () => {
  assert.deepEqual(ids(neighbours(mk([["u", 0, false], ["b", 30]]), new Set(["u"]))), { prev: null, next: "b", show: ["b"] });
  assert.deepEqual(ids(neighbours(mk([["a", -30], ["u", 0, false]]), new Set(["u"]))), { prev: "a", next: null, show: ["a"] });
});

test("no neighbours at all", () => {
  const items = mk([["u", 0, false], ["v", 10, false], ["arch", 20, true, true]]);
  assert.deepEqual(ids(neighbours(items, new Set(["u"]))), { prev: null, next: null, show: [] });
});

test("prefers the same day: an other-day neighbour is returned but not shown", () => {
  // u is at 01:00; the previous placed shot is the evening before
  const items = mk([["eve", -14 * 60], ["u", -9 * 60, false], ["b", -8 * 60]]);
  const r = neighbours(items, new Set(["u"]));
  assert.deepEqual(ids(r), { prev: "eve", next: "b", show: ["b"] });
  assert.equal(r.prev.sameDay, false);
  assert.equal(r.next.sameDay, true);
});

test("both neighbours on other days are both shown", () => {
  const items = mk([["a", -24 * 60], ["u", 0, false], ["b", 24 * 60]]);
  const r = neighbours(items, new Set(["u"]));
  assert.deepEqual(ids(r), { prev: "a", next: "b", show: ["a", "b"] });
  assert.equal(r.prev.sameDay || r.next.sameDay, false);
});

test("multi-select: earliest selected -> previous, latest selected -> next; placed shots in between are ignored", () => {
  const items = mk([["a", -5], ["u1", 0, false], ["mid", 10], ["u2", 20, false], ["b", 33]]);
  const r = neighbours(items, new Set(["u1", "u2"]));
  assert.deepEqual(ids(r), { prev: "a", next: "b", show: ["a", "b"] });
  assert.equal(r.prev.gap, -5 * MIN);   // from u1
  assert.equal(r.next.gap, 13 * MIN);   // from u2
});

test("selected placed shots are never their own neighbours", () => {
  const items = mk([["a", -5], ["p", 0], ["b", 7]]);
  assert.deepEqual(ids(neighbours(items, new Set(["p"]))), { prev: "a", next: "b", show: ["a", "b"] });
});

test("same time as the selected shot counts, with a zero gap", () => {
  const items = mk([["a", 0], ["u", 0, false]]);
  const r = neighbours(items, new Set(["u"]));
  assert.equal(r.prev.x.id, "a");
  assert.equal(r.prev.gap, 0);
});

test("empty or unknown selection", () => {
  assert.deepEqual(ids(neighbours(mk([["a", 0]]), new Set())), { prev: null, next: null, show: [] });
  assert.deepEqual(ids(neighbours(mk([["a", 0]]), new Set(["zzz"]))), { prev: null, next: null, show: [] });
});

test("stays fast with a large trip", () => {
  const rows = [];
  for (let i = 0; i < 5000; i++) rows.push([`s${i}`, i, i % 7 === 0]);
  const items = mk(rows), sel = new Set(["s2501"]);
  const t = performance.now();
  for (let i = 0; i < 200; i++) neighbours(items, sel);
  assert.ok(performance.now() - t < 500, "200 lookups over 5,000 shots took over 0.5 s");
  assert.deepEqual(ids(neighbours(items, sel)).show, ["s2499", "s2506"]);
});

test("fmtGap", () => {
  assert.equal(fmtGap(-12 * MIN), "−12 min");
  assert.equal(fmtGap(40 * MIN), "+40 min");
  assert.equal(fmtGap(0), "+0 min");
  assert.equal(fmtGap(29), "+0 min");
  assert.equal(fmtGap(59 * MIN + 40), "+1 h");
  assert.equal(fmtGap(65 * MIN), "+1 h 5 min");
  assert.equal(fmtGap(-(2 * H + 30 * MIN)), "−2 h 30 min");
  assert.equal(fmtGap(24 * H), "+1 d");
  assert.equal(fmtGap(-(51 * H)), "−2 d 3 h");
});
