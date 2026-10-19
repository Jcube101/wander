// Run: node --test site/test/test_site.mjs   (plain node, no dependencies)
// The reference viewer's pure helpers (site/public/lib.js), checked against the data contract.
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { test } from "node:test";
import * as W from "../public/lib.js";

const MEDIA = "https://media.example.com";
const PUBLIC = new URL("../public/", import.meta.url);

test("assets and home links resolve the same from /, /<slug> and /<slug>/ (Pages serves index.html for all three)", () => {
  const src = readFileSync(new URL("index.html", PUBLIC), "utf8") + readFileSync(new URL("app.js", PUBLIC), "utf8");
  const refs = [...src.matchAll(/\b(?:src|href)="([^"$]*)"/g)].map((m) => m[1])
    .filter((r) => !/^(?:https?:|data:|#|\?)/.test(r));
  assert.ok(refs.includes("/app.js") && refs.includes("/style.css"), refs.join(" "));
  for (const ref of refs) {
    const paths = ["/", "/lisbon-2025", "/lisbon-2025/"].map((p) => new URL(ref, "https://wander.example.com" + p).pathname);
    assert.equal(new Set(paths).size, 1, `${ref} resolves to ${paths.join(", ")}`);
    if (paths[0] !== "/") assert.ok(existsSync(new URL("." + paths[0], PUBLIC)), `${ref}: no such file in public/`);
  }
});

test("URLs: one slash, covers prefer the right size, item paths are relative to the trip", () => {
  assert.equal(W.joinUrl(MEDIA + "/", "/trips.json"), "https://media.example.com/trips.json");
  const t = { cover: "public/covers/lisbon-2025-card.jpg?v=1", coverImage: "public/covers/lisbon-2025.jpg?v=2" };
  assert.equal(W.coverUrl(MEDIA, t), MEDIA + "/public/covers/lisbon-2025.jpg?v=2");
  assert.equal(W.cardCoverUrl(MEDIA, t), MEDIA + "/public/covers/lisbon-2025-card.jpg?v=1");
  assert.equal(W.coverUrl(MEDIA, { cover: "public/covers/x-card.jpg" }), MEDIA + "/public/covers/x-card.jpg");
  assert.equal(W.coverUrl(MEDIA, {}), null);
  assert.equal(W.itemUrl(MEDIA, "lisbon-2025", "cards/abc.jpg"), MEDIA + "/lisbon-2025/cards/abc.jpg");
  assert.equal(W.itemUrl(MEDIA, "lisbon-2025", null), null);
  assert.equal(W.tripDataUrl(MEDIA, "lisbon-2025"), MEDIA + "/lisbon-2025/trip.json");
});

test("which trip a page shows: ?trip= first, else a /<slug> path; bad slugs are ignored", () => {
  assert.equal(W.slugFromLocation({ search: "?trip=lisbon-2025", pathname: "/" }), "lisbon-2025");
  assert.equal(W.slugFromLocation({ search: "", pathname: "/lisbon-2025" }), "lisbon-2025");
  assert.equal(W.slugFromLocation({ search: "", pathname: "/lisbon-2025/" }), "lisbon-2025");
  assert.equal(W.slugFromLocation({ search: "", pathname: "/" }), null);
  assert.equal(W.slugFromLocation({ search: "", pathname: "/index.html" }), null);
  for (const bad of ["../x", "Lisbon", "a%2Fb", "", "x/../y"]) {
    assert.equal(W.slugFromLocation({ search: "?trip=" + encodeURIComponent(bad), pathname: "/" }), null, bad);
  }
  assert.equal(W.tripHref("lisbon-2025"), "?trip=lisbon-2025");
});

test("sign-in returns to the same page with signedin=1, keeping other parameters and the hash", () => {
  const url = W.signInUrl(MEDIA, "lisbon-2025", "https://wander.example.com/?trip=lisbon-2025&signedin=0#map");
  assert.ok(url.startsWith(MEDIA + "/auth/lisbon-2025?return="));
  const back = new URL(new URL(url).searchParams.get("return"));
  assert.equal(back.origin, "https://wander.example.com");
  assert.equal(back.searchParams.get("trip"), "lisbon-2025");
  assert.deepEqual(back.searchParams.getAll("signedin"), ["1"]);
  assert.equal(back.hash, "#map");
  assert.equal(W.withoutSignedIn(back.href), "https://wander.example.com/?trip=lisbon-2025#map");
  assert.equal(W.signOutUrl(MEDIA), MEDIA + "/cdn-cgi/access/logout");
});

test("times are shown in the trip's zone, never the viewer's", () => {
  const t = Date.UTC(2025, 4, 2, 23, 30) / 1000; // 23:30 UTC
  assert.equal(W.fmtTime(t, 60), "00:30");       // +01:00
  assert.equal(W.fmtTime(t, -300), "18:30");     // -05:00
  assert.equal(W.fmtTime(t, 0), "23:30");
  assert.equal(W.fmtDay("2025-05-02"), "Fri 2 May");
  assert.equal(W.itemCaption({ t, day: "2025-05-03", dayN: 2 }, 60), "Day 2 · Sat 3 May · 00:30");
  assert.equal(W.itemCaption({ t, day: "2025-05-02" }, 0), "Fri 2 May · 23:30");
});

test("date ranges, durations and summaries", () => {
  assert.equal(W.fmtRange("2025-05-02", "2025-05-08"), "2–8 May 2025");
  assert.equal(W.fmtRange("2025-04-28", "2025-05-03"), "28 Apr – 3 May 2025");
  assert.equal(W.fmtRange("2025-12-30", "2026-01-02"), "30 Dec 2025 – 2 Jan 2026");
  assert.equal(W.fmtRange("2025-05-02", "2025-05-02"), "2 May 2025");
  assert.equal(W.fmtRange(null, null), "");
  assert.equal(W.fmtDuration(12.4), "12s");
  assert.equal(W.fmtDuration(75), "1:15");
  assert.equal(W.fmtDuration(0), "");
  assert.equal(W.tripSummary({ days: 7, counts: { photos: 350, videos: 62 } }), "7 days · 350 photos · 62 videos");
  assert.equal(W.tripSummary({ days: [{}], counts: { photos: 1, videos: 0 } }), "1 day · 1 photo");
});

test("trips newest first; items by day in time order; unplaced items stay in the gallery", () => {
  const trips = [{ slug: "a", start: "2024-01-01" }, { slug: "b", start: "2025-05-02" }, { slug: "c" }];
  assert.deepEqual(W.sortTrips(trips).map((t) => t.slug), ["b", "a", "c"]);
  assert.deepEqual(W.sortTrips(undefined), []);
  const items = [
    { id: "3", t: 30, day: "d2", lat: 1, lon: 2 },
    { id: "1", t: 10, day: "d1" },
    { id: "2", t: 20, day: "d1", lat: 0, lon: 0 },
  ];
  assert.deepEqual(W.itemsFor(items).map((x) => x.id), ["1", "2", "3"]);
  assert.deepEqual(W.itemsFor(items, "d1").map((x) => x.id), ["1", "2"]);
  assert.deepEqual(items.filter(W.isPlaced).map((x) => x.id), ["3", "2"]); // 0,0 is a place; missing isn't
  assert.equal(W.dayLabel({ n: 3, key: "2025-05-04" }), "Day 3 · Sun 4 May");
});

test("config.local.js overrides config.js key by key; a missing one is skipped silently", async (t) => {
  const base = { media: "https://media.example.com", title: "Wander" };
  const warn = t.mock.method(console, "warn", () => {});
  const local = (cfg) => async () => ({ default: cfg });
  assert.deepEqual(await W.loadConfig(base, local({ media: "https://media.lisbon.test" })),
    { media: "https://media.lisbon.test", title: "Wander" });
  assert.deepEqual(await W.loadConfig(base, local(undefined)), base); // no default export
  const missing = async () => { throw new TypeError("Failed to fetch dynamically imported module"); };
  assert.deepEqual(await W.loadConfig(base, missing), base);
  assert.equal(warn.mock.callCount(), 0);
  const broken = async () => { throw new SyntaxError("Unexpected token '}'"); };
  assert.deepEqual(await W.loadConfig(base, broken), base);
  assert.equal(warn.mock.callCount(), 1); // there, but broken: say so
  assert.equal(base.media, "https://media.example.com");
});

test("favourites: endpoint, POST body (text/plain JSON) and what a response means", () => {
  assert.equal(W.favoritesUrl(MEDIA + "/", "lisbon-2025"), MEDIA + "/lisbon-2025/favorites");
  assert.equal(W.favoriteBody("abc123def456", true), '{"id":"abc123def456","fav":true}');
  assert.equal(W.favoriteBody("abc123def456", 0), '{"id":"abc123def456","fav":false}');
  const out = (r) => W.favoritesOutcome({ type: "cors", ok: r.status >= 200 && r.status < 300, ...r });
  assert.equal(out({ status: 200 }), "ok");
  assert.equal(out({ type: "opaqueredirect", status: 0, ok: false }), "signed-out"); // Access → its login page
  assert.equal(out({ status: 401 }), "signed-out");
  for (const status of [400, 403, 404, 409, 413, 500, 503]) assert.equal(out({ status }), "error", status);
});

test("favourites: ids from the Worker, toggling, the filter and its label", () => {
  const known = new Set(["a", "b", "c"]);
  assert.deepEqual([...W.favoriteIds({ ids: ["b", "zzz", 7, null, "a"] }, known)], ["b", "a"]);
  for (const bad of [null, {}, { ids: "a" }, []]) assert.equal(W.favoriteIds(bad, known).size, 0);
  const favs = new Set(["a"]);
  const more = W.withFavorite(favs, "c", true);
  assert.deepEqual([...more], ["a", "c"]);
  assert.deepEqual([...favs], ["a"]); // a copy: the old set is what a rollback goes back to
  assert.deepEqual([...W.withFavorite(more, "a", false)], ["c"]);
  assert.deepEqual([...W.withFavorite(more, "zzz", false)], ["a", "c"]);
  const items = [{ id: "c", t: 30 }, { id: "a", t: 10 }, { id: "b", t: 20 }];
  assert.deepEqual(W.favoriteItems(items, more).map((x) => x.id), ["a", "c"]);
  assert.deepEqual(W.favoriteItems(items, new Set()), []);
  assert.equal(W.favoritesLabel(0), "Favourites (0)");
  assert.equal(W.favoritesLabel(12), "Favourites (12)");
});

test("favourites: taps are sent one at a time, in order, and a failure doesn't block the next", async () => {
  const queue = W.serial();
  const log = [];
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  const a = queue(async () => { log.push("a start"); await wait(20); log.push("a end"); return "A"; });
  const b = queue(async () => { log.push("b start"); throw new Error("offline"); });
  const c = queue(async () => { log.push("c start"); return "C"; });
  assert.equal(await a, "A");
  await assert.rejects(b, /offline/);
  assert.equal(await c, "C");
  assert.deepEqual(log, ["a start", "a end", "b start", "c start"]);
});

test("lightbox stepping wraps; HTML escaping", () => {
  assert.equal(W.step(0, 3, -1), 2);
  assert.equal(W.step(2, 3, 1), 0);
  assert.equal(W.step(0, 0, 1), -1);
  assert.equal(W.escapeHtml(`<img src=x onerror="a('b')">&`), "&lt;img src=x onerror=&quot;a(&#39;b&#39;)&quot;&gt;&amp;");
  assert.equal(W.escapeHtml(null), "");
});
