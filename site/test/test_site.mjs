// Run: node --test site/test/test_site.mjs   (plain node, no dependencies)
// The reference viewer's pure helpers (site/public/lib.js), checked against the data contract.
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { test } from "node:test";
import { crc32 as zlibCrc32 } from "node:zlib";
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
  const out = (r) => W.accessOutcome({ type: "cors", ok: r.status >= 200 && r.status < 300, ...r });
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

// ---------------------------------------------------------------- downloads
const NAMES = JSON.parse(readFileSync(new URL("../../worker/test/download-names.json", import.meta.url), "utf8")).cases;

test("download names: the same as the Worker's and export_favs.py's (shared cases)", () => {
  assert.ok(NAMES.length >= 10);
  for (const c of NAMES) assert.equal(W.fileName({ id: c.id, orig: c.orig, t: c.t }, c.tzOffsetMin, c.ext), c.name, c.why);
  const used = new Set();
  assert.deepEqual(["a.jpg", "a.jpg", "A.JPG", "a_2.jpg", "b"].map((n) => W.uniqueName(n, used)),
    ["a.jpg", "a_2.jpg", "A_3.JPG", "a_2_2.jpg", "b"]); // as export_favs.unique_name
});

test("downloads: the full preview, else the card; ?download=1 on the media host", () => {
  const t = Date.UTC(2025, 4, 2, 14, 30) / 1000;
  const video = { id: "v1", orig: "DJI_0001.MP4", t, media: "media/v1.mp4", card: "cards/v1.jpg" };
  const quick = { id: "p1", orig: "IMG_1.HEIC", t, card: "cards/p1.jpg" }; // no full preview yet
  assert.equal(W.downloadPath(video), "media/v1.mp4");
  assert.equal(W.downloadPath(quick), "cards/p1.jpg");
  assert.equal(W.downloadPath({ id: "x", thumb: "thumbs/x.jpg" }), null); // thumbnails are never the download
  assert.equal(W.downloadUrl(MEDIA, "lisbon-2025", video), MEDIA + "/lisbon-2025/media/v1.mp4?download=1");
  assert.equal(W.downloadUrl(MEDIA, "lisbon-2025", { id: "x" }), null);
  assert.equal(W.downloadName(video, 60), "2025-05-02_1530_DJI_0001.mp4");
  assert.equal(W.downloadName(quick, 60), "2025-05-02_1530_IMG_1.jpg");
});

test("ZIP estimate: files, bytes from trip.json, and how many sizes are unknown; desktop only", () => {
  const items = [{ media: "media/a.jpg", bytes: 400e3 }, { media: "media/b.mp4", bytes: 60e6 }, { card: "cards/c.jpg" }, { thumb: "thumbs/d.jpg" }];
  assert.deepEqual(W.zipEstimate(items), { files: 3, bytes: 60.4e6, unknown: 1 });
  assert.equal(W.ZIP_MAX, 500e6);
  assert.deepEqual([840e3, 1, 8.44e6, 84.4e6, 499.6e6, 1.234e9].map(W.fmtBytes), ["840 KB", "1 KB", "8.4 MB", "84 MB", "500 MB", "1.2 GB"]);
  const mm = (hits) => (q) => ({ matches: hits.includes(q) });
  assert.equal(W.isDesktop(mm(["(hover: hover) and (pointer: fine)", "(min-width: 821px)"])), true);
  assert.equal(W.isDesktop(mm(["(min-width: 821px)"])), false); // a tablet: touch, however wide
  assert.equal(W.isDesktop(mm(["(hover: hover) and (pointer: fine)"])), false); // a narrow window
});

test("CRC-32: the standard check value, and the same when fed in pieces", () => {
  const enc = new TextEncoder();
  assert.equal(W.crc32(enc.encode("123456789")), 0xcbf43926);
  assert.equal(W.crc32(new Uint8Array()), 0);
  const data = Uint8Array.from({ length: 70000 }, (_, i) => (i * 7919) % 251);
  assert.equal(W.crc32(data.subarray(30000), W.crc32(data.subarray(0, 30000))), zlibCrc32(data));
});

// A minimal ZIP reader, written from the format spec, to check what zipWriter makes.
function readZip(buf) {
  const v = new DataView(buf.buffer, buf.byteOffset, buf.byteLength);
  const end = buf.byteLength - 22;
  assert.equal(v.getUint32(end, true), 0x06054b50, "end of central directory last, no comment");
  const count = v.getUint16(end + 10, true), cdSize = v.getUint32(end + 12, true), cdAt = v.getUint32(end + 16, true);
  assert.equal(v.getUint16(end + 8, true), count);
  assert.equal(cdAt + cdSize, end);
  const files = [];
  for (let i = 0, at = cdAt; i < count; i++) {
    assert.equal(v.getUint32(at, true), 0x02014b50);
    const nameLen = v.getUint16(at + 28, true), extra = v.getUint16(at + 30, true), comment = v.getUint16(at + 32, true);
    const e = { flags: v.getUint16(at + 8, true), method: v.getUint16(at + 10, true), time: v.getUint16(at + 12, true),
      date: v.getUint16(at + 14, true), crc: v.getUint32(at + 16, true), csize: v.getUint32(at + 20, true),
      size: v.getUint32(at + 24, true), local: v.getUint32(at + 42, true),
      name: new TextDecoder().decode(buf.subarray(at + 46, at + 46 + nameLen)) };
    const l = e.local;
    assert.equal(v.getUint32(l, true), 0x04034b50);
    assert.equal(v.getUint32(l + 14, true), e.crc);
    assert.equal(v.getUint32(l + 18, true), e.csize);
    assert.equal(v.getUint32(l + 22, true), e.size);
    const lName = v.getUint16(l + 26, true), lExtra = v.getUint16(l + 28, true);
    assert.equal(new TextDecoder().decode(buf.subarray(l + 30, l + 30 + lName)), e.name);
    e.data = buf.subarray(l + 30 + lName + lExtra, l + 30 + lName + lExtra + e.csize);
    files.push(e);
    at += 46 + nameLen + extra + comment;
  }
  return files;
}

test("ZIP: stored files a standard reader can open, with names, sizes, CRCs and the trip-zone time", async () => {
  const enc = new TextEncoder();
  const t = Date.UTC(2025, 4, 2, 14, 30, 58) / 1000;
  const zip = W.zipWriter();
  const photo = Uint8Array.from({ length: 5000 }, (_, i) => i % 256);
  zip.add("2025-05-02_1530_IMG_1.jpg", [photo.subarray(0, 1000), new Blob([photo.subarray(1000)])],
    { crc: W.crc32(photo), size: photo.length, t, tzOffsetMin: 60 });
  zip.add("empty.txt", [], { crc: 0, size: 0, t, tzOffsetMin: 60 });
  const clip = enc.encode("a short clip");
  zip.add("2025-05-02_1531_DJI_0002.mp4", [clip], { crc: W.crc32(clip), size: clip.length, t: t + 60, tzOffsetMin: 60 });
  assert.equal(zip.count, 3);
  const before = zip.size;
  const buf = new Uint8Array(await new Blob(zip.finish()).arrayBuffer());
  assert.equal(before, (30 + 25 + 5000) + (30 + 9) + (30 + 28 + 12)); // headers + data, before the directory
  const files = readZip(buf);
  assert.deepEqual(files.map((f) => f.name), ["2025-05-02_1530_IMG_1.jpg", "empty.txt", "2025-05-02_1531_DJI_0002.mp4"]);
  for (const [f, data] of [[files[0], photo], [files[1], new Uint8Array()], [files[2], clip]]) {
    assert.equal(f.method, 0); // stored
    assert.equal(f.flags, 0x0800);
    assert.equal(f.size, data.length);
    assert.deepEqual(f.data, data);
    assert.equal(f.crc, zlibCrc32(data));
  }
  // 15:30:58 in the trip's zone, as MS-DOS date and time
  assert.equal(files[0].date, ((2025 - 1980) << 9) | (5 << 5) | 2);
  assert.equal(files[0].time, (15 << 11) | (30 << 5) | 29);
  assert.deepEqual(W.dosDateTime(0, 0), { date: (1 << 5) | 1, time: 0 }); // before 1980: 1 Jan 1980
});
