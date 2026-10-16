// Run: npm test   (plain node, no dependencies — mocks the R2 binding)
import assert from "node:assert/strict";
import { test } from "node:test";
import worker from "../src/index.js";

const FILES = {
  "trips.json": ["application/json", '{"trips":[]}'],
  "public/covers/thailand-2026.jpg": ["image/jpeg", "COVER"],
  "thailand-2026/trip.json": ["application/json", '{"items":[]}'],
  "thailand-2026/cards/abc123.jpg": ["image/jpeg", "CARD"],
  "thailand-2026/media/abc123.mp4": ["video/mp4", "0123456789ABCDEFGHIJ"],
  "thailand-2026/trip.js": ["text/javascript", "window.TRIP={rel:'D:/private'}"],
  "thailand-2026/index.html": ["text/html", "<html>"],
};

function object(key, opts) {
  const [type, body] = FILES[key];
  const etag = `"e-${key.length}"`;
  const base = {
    size: body.length,
    httpEtag: etag,
    writeHttpMetadata(h) { h.set("content-type", type); },
  };
  if (!opts) return base; // head()
  if (opts.onlyIf?.get?.("if-none-match") === etag) return base; // conditional hit → no body
  const rh = opts.range?.get?.("range");
  if (rh) {
    const m = rh.match(/bytes=(\d*)-(\d*)/);
    const range = m[1] === "" ? { suffix: +m[2] } : { offset: +m[1], length: (m[2] ? +m[2] : body.length - 1) - +m[1] + 1 };
    const part = range.suffix !== undefined ? body.slice(body.length - range.suffix) : body.slice(range.offset, range.offset + range.length);
    return { ...base, body: part, range };
  }
  return { ...base, body };
}

const env = {
  BUCKET: {
    async get(k, o) { return FILES[k] ? object(k, o || {}) : null; },
    async head(k) { return FILES[k] ? object(k) : null; },
  },
};

const SITE = "https://wander.job-joseph.com";
async function call(path, init = {}) {
  const res = await worker.fetch(new Request("https://media.job-joseph.com" + path, init), env);
  return { res, body: res.body ? await res.text() : "" };
}
const fromSite = (extra = {}) => ({ headers: { origin: SITE, ...extra } });
const jwt = (payload) => "h." + Buffer.from(JSON.stringify(payload)).toString("base64url") + ".s";

test("public trip list: anyone, and the site with credentials", async () => {
  let { res } = await call("/trips.json");
  assert.equal(res.status, 200);
  assert.equal(res.headers.get("access-control-allow-origin"), "*");
  assert.equal(res.headers.get("access-control-allow-credentials"), null);
  ({ res } = await call("/trips.json", fromSite()));
  assert.equal(res.headers.get("access-control-allow-origin"), SITE);
  assert.equal(res.headers.get("access-control-allow-credentials"), "true");
});

test("query strings are ignored: cover ?v= serves the same object", async () => {
  const { res, body } = await call("/public/covers/thailand-2026.jpg?v=0123abcdef");
  assert.equal(res.status, 200);
  assert.equal(body, "COVER");
  assert.equal((await call("/thailand-2026/trip.js?v=1")).res.status, 404); // still refused
});

test("protected trip data is private-cached and only CORS-readable by the site", async () => {
  let { res } = await call("/thailand-2026/trip.json", fromSite());
  assert.equal(res.status, 200);
  assert.match(res.headers.get("cache-control"), /^private/);
  assert.equal(res.headers.get("access-control-allow-origin"), SITE);
  ({ res } = await call("/thailand-2026/trip.json", { headers: { origin: "https://evil.example" } }));
  assert.equal(res.headers.get("access-control-allow-origin"), null);
});

test("video range requests", async () => {
  let { res, body } = await call("/thailand-2026/media/abc123.mp4", { headers: { range: "bytes=5-9" } });
  assert.equal(res.status, 206);
  assert.equal(res.headers.get("content-range"), "bytes 5-9/20");
  assert.equal(body, "56789");
  ({ res, body } = await call("/thailand-2026/media/abc123.mp4", { headers: { range: "bytes=-4" } }));
  assert.equal(res.headers.get("content-range"), "bytes 16-19/20");
  assert.equal(body, "GHIJ");
});

test("conditional request returns 304", async () => {
  const { res } = await call("/thailand-2026/cards/abc123.jpg", { headers: { "if-none-match": '"e-30"' } });
  assert.equal(res.status, 304);
});

test("refuses non-allow-listed files, listing, encoding tricks and writes", async () => {
  for (const p of ["/thailand-2026/trip.js", "/thailand-2026/index.html", "/", "/thailand-2026%2Fcards%2Fabc123.jpg",
                   "/%2e%2e/x.jpg", "/Thailand-2026/cards/abc123.jpg"]) {
    const { res } = await call(p);
    assert.equal(res.status, 404, p);
  }
  const { res } = await call("/thailand-2026/cards/abc123.jpg", { method: "PUT", body: "x" });
  assert.equal(res.status, 405);
});

test("auth hop only returns to job-joseph.com", async () => {
  const back = "https://wander.job-joseph.com/thailand-2026?signedin=1";
  let { res } = await call("/auth/thailand-2026?return=" + encodeURIComponent(back));
  assert.equal(res.status, 302);
  assert.equal(res.headers.get("location"), back);
  for (const evil of ["https://evil.example/", "https://job-joseph.com.evil.example/", "http://wander.job-joseph.com/x"]) {
    ({ res } = await call("/auth/thailand-2026?return=" + encodeURIComponent(evil)));
    assert.equal(res.headers.get("location"), "https://wander.job-joseph.com/thailand-2026", evil);
  }
});

test("/me reads the Access cookie and ignores expired ones", async () => {
  let { body } = await call("/me", fromSite());
  assert.deepEqual(JSON.parse(body), { email: null });
  const live = jwt({ email: "friend@example.com", exp: Math.floor(Date.now() / 1000) + 3600 });
  ({ body } = await call("/me", fromSite({ cookie: "a=1; CF_Authorization=" + live })));
  assert.deepEqual(JSON.parse(body), { email: "friend@example.com" });
  ({ body } = await call("/me", { headers: { cookie: "CF_Authorization=" + jwt({ email: "old@x.com", exp: 1 }) } }));
  assert.deepEqual(JSON.parse(body), { email: null });
});

test("preflight", async () => {
  const { res } = await call("/trips.json", { method: "OPTIONS", headers: { origin: SITE } });
  assert.equal(res.status, 204);
  assert.equal(res.headers.get("access-control-allow-origin"), SITE);
});
