// Run: npm test   (plain node, no dependencies — mocks the R2 binding and Access's signing keys)
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { test } from "node:test";
import worker from "../src/index.js";

// Item ids in the made-up trips (12 hex, like the build's).
const A = "aaaaaaaaaaa1", B = "bbbbbbbbbbb2", C = "ccccccccccc3";
const ARCHIVED = "ddddddddddd4"; // was in the trip once; not in trip.json any more
const BIG = Array.from({ length: 2001 }, (_, i) => i.toString(16).padStart(12, "0"));
const tripJson = (ids) => JSON.stringify({ items: ids.map((id) => ({ id, type: "photo" })) });

const FILES = {
  "trips.json": ["application/json", '{"trips":[]}'],
  "public/covers/lisbon-2025.jpg": ["image/jpeg", "COVER"],
  "lisbon-2025/trip.json": ["application/json", tripJson([A, B, C])],
  "big-2025/trip.json": ["application/json", tripJson(BIG)],
  "lisbon-2025/cards/abc123.jpg": ["image/jpeg", "CARD"],
  "lisbon-2025/media/abc123.mp4": ["video/mp4", "0123456789ABCDEFGHIJ"],
  "lisbon-2025/trip.js": ["text/javascript", "window.TRIP={rel:'D:/private'}"],
  "lisbon-2025/index.html": ["text/html", "<html>"],
};

function object(key, opts) {
  const [type, body] = FILES[key];
  const etag = `"e-${key.length}"`;
  const base = {
    size: body.length,
    httpEtag: etag,
    writeHttpMetadata(h) { h.set("content-type", type); },
    async text() { return body; },
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

// What the Worker writes (favourites), apart from the read-only FILES above.
const STORE = new Map();
function stored(key) {
  const body = STORE.get(key);
  return { size: body.length, httpEtag: '"s"', writeHttpMetadata(h) { h.set("content-type", "application/json"); }, body, async text() { return body; } };
}

const SITE = "https://wander.example.com";
const PREVIEW = "https://preview.example.net"; // a second allowed origin, e.g. a site builder's preview
const TEAM = "https://lisbon-crew.cloudflareaccess.com";
const AUD = { "lisbon-2025": "aud-lisbon", "big-2025": "aud-big", "porto-2026": "aud-porto" }; // porto: no trip.json
const SALT = "test-salt-not-a-secret";
const env = {
  SITE_ORIGINS: `${SITE}, ${PREVIEW}/`,
  ACCESS_TEAM_DOMAIN: TEAM + "/",
  ACCESS_AUD: AUD,
  FAVS_SALT: SALT,
  BUCKET: {
    async get(k, o) { return FILES[k] ? object(k, o || {}) : STORE.has(k) ? stored(k) : null; },
    async head(k) { return FILES[k] ? object(k) : STORE.has(k) ? stored(k) : null; },
    async put(k, v) { STORE.set(k, String(v)); },
    async delete(k) { STORE.delete(k); },
  },
};

// Access's signing keys: a real RSA pair, served at the team's certs URL. An attacker's
// pair signs forged tokens.
const RSA = { name: "RSASSA-PKCS1-v1_5", modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: "SHA-256" };
const access = await crypto.subtle.generateKey(RSA, true, ["sign", "verify"]);
const attacker = await crypto.subtle.generateKey(RSA, true, ["sign", "verify"]);
const certsFetched = [];
globalThis.fetch = async (url) => {
  certsFetched.push(String(url));
  if (String(url) !== `${TEAM}/cdn-cgi/access/certs`) throw new TypeError("network down");
  const jwk = await crypto.subtle.exportKey("jwk", access.publicKey);
  return new Response(JSON.stringify({ keys: [{ ...jwk, kid: "k1", use: "sig" }] }));
};
const b64url = (x) => Buffer.from(typeof x === "string" ? x : JSON.stringify(x)).toString("base64url");
async function token(claims, { key = access.privateKey, kid = "k1", alg = "RS256" } = {}) {
  const signed = `${b64url({ alg, kid, typ: "JWT" })}.${b64url(claims)}`;
  const sig = await crypto.subtle.sign("RSASSA-PKCS1-v1_5", key, new TextEncoder().encode(signed));
  return `${signed}.${Buffer.from(sig).toString("base64url")}`;
}
const now = () => Math.floor(Date.now() / 1000);
const claims = (email, extra = {}) =>
  ({ iss: TEAM, aud: [AUD["lisbon-2025"]], email, exp: now() + 3600, iat: now(), type: "app", ...extra });
const favKey = (slug, email) => `favs/${slug}/${createHash("sha256").update(SALT + email).digest("hex")}.json`;

async function call(path, init = {}, e = env) {
  const res = await worker.fetch(new Request("https://media.example.com" + path, init), e);
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
  const { res, body } = await call("/public/covers/lisbon-2025.jpg?v=0123abcdef");
  assert.equal(res.status, 200);
  assert.equal(body, "COVER");
  assert.equal((await call("/lisbon-2025/trip.js?v=1")).res.status, 404); // still refused
});

test("protected trip data is private-cached and only CORS-readable by the site", async () => {
  let { res } = await call("/lisbon-2025/trip.json", fromSite());
  assert.equal(res.status, 200);
  assert.match(res.headers.get("cache-control"), /^private/);
  assert.equal(res.headers.get("access-control-allow-origin"), SITE);
  ({ res } = await call("/lisbon-2025/trip.json", { headers: { origin: "https://evil.example" } }));
  assert.equal(res.headers.get("access-control-allow-origin"), null);
});

test("video range requests", async () => {
  let { res, body } = await call("/lisbon-2025/media/abc123.mp4", { headers: { range: "bytes=5-9" } });
  assert.equal(res.status, 206);
  assert.equal(res.headers.get("content-range"), "bytes 5-9/20");
  assert.equal(body, "56789");
  ({ res, body } = await call("/lisbon-2025/media/abc123.mp4", { headers: { range: "bytes=-4" } }));
  assert.equal(res.headers.get("content-range"), "bytes 16-19/20");
  assert.equal(body, "GHIJ");
});

test("conditional request returns 304", async () => {
  const { res } = await call("/lisbon-2025/cards/abc123.jpg", { headers: { "if-none-match": `"e-${"lisbon-2025/cards/abc123.jpg".length}"` } });
  assert.equal(res.status, 304);
});

test("refuses non-allow-listed files, listing, encoding tricks and writes", async () => {
  for (const p of ["/lisbon-2025/trip.js", "/lisbon-2025/index.html", "/", "/lisbon-2025%2Fcards%2Fabc123.jpg",
                   "/%2e%2e/x.jpg", "/Lisbon-2025/cards/abc123.jpg"]) {
    const { res } = await call(p);
    assert.equal(res.status, 404, p);
  }
  const { res } = await call("/lisbon-2025/cards/abc123.jpg", { method: "PUT", body: "x" });
  assert.equal(res.status, 405);
});

test("auth hop only returns to a site origin", async () => {
  const back = "https://wander.example.com/lisbon-2025?signedin=1";
  let { res } = await call("/auth/lisbon-2025?return=" + encodeURIComponent(back));
  assert.equal(res.status, 302);
  assert.equal(res.headers.get("location"), back);
  ({ res } = await call("/auth/lisbon-2025?return=" + encodeURIComponent(PREVIEW + "/lisbon-2025")));
  assert.equal(res.headers.get("location"), PREVIEW + "/lisbon-2025");
  for (const evil of ["https://evil.example/", "https://wander.example.com.evil.example/", "http://wander.example.com/x",
                      "https://other.example.com/x", "https://wander.example.com:8443/x", "javascript:alert(1)"]) {
    ({ res } = await call("/auth/lisbon-2025?return=" + encodeURIComponent(evil)));
    assert.equal(res.headers.get("location"), "https://wander.example.com/lisbon-2025", evil);
  }
});

test("without SITE_ORIGINS: no credentialed CORS, /auth refuses, public files still served", async () => {
  const bare = { BUCKET: env.BUCKET };
  let { res } = await call("/trips.json", fromSite(), bare);
  assert.equal(res.status, 200);
  assert.equal(res.headers.get("access-control-allow-origin"), "*");
  assert.equal(res.headers.get("access-control-allow-credentials"), null);
  ({ res } = await call("/lisbon-2025/trip.json", fromSite(), bare));
  assert.equal(res.headers.get("access-control-allow-origin"), null);
  ({ res } = await call("/auth/lisbon-2025", {}, bare));
  assert.equal(res.status, 500);
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

// ---------------------------------------------------------------- favourites
const FAV = "/lisbon-2025/favorites";
function favGet(jwt, slug = "lisbon-2025") {
  return call(`/${slug}/favorites`, { headers: { origin: SITE, ...(jwt ? { "cf-access-jwt-assertion": jwt } : {}) } });
}
function favPost(jwt, body, { slug = "lisbon-2025", origin = SITE, type = "text/plain;charset=UTF-8" } = {}) {
  const headers = { "content-type": type };
  if (origin) headers.origin = origin;
  if (jwt) headers["cf-access-jwt-assertion"] = jwt;
  return call(`/${slug}/favorites`, { method: "POST", headers, body: typeof body === "string" ? body : JSON.stringify(body) });
}
const ids = ({ body }) => JSON.parse(body).ids;

test("favourites: the token's own list, read and written; stored under a salted hash with no email", async () => {
  STORE.clear();
  const jwt = await token(claims("Friend@Example.com"));
  let r = await favGet(jwt);
  assert.equal(r.res.status, 200);
  assert.deepEqual(JSON.parse(r.body), { ids: [] });
  assert.equal(r.res.headers.get("cache-control"), "private, no-store");
  assert.equal(r.res.headers.get("access-control-allow-origin"), SITE);
  assert.equal(r.res.headers.get("access-control-allow-credentials"), "true");

  r = await favPost(jwt, { id: A, fav: true });
  assert.equal(r.res.status, 200);
  assert.deepEqual(JSON.parse(r.body), { ids: [A] });
  assert.equal(r.res.headers.get("access-control-allow-origin"), SITE);
  assert.deepEqual(ids(await favPost(jwt, { id: C, fav: true, email: "someone-else@example.com" })), [A, C]); // email ignored
  assert.deepEqual(ids(await favPost(jwt, { id: A, fav: true })), [A, C]); // already a favourite: no change

  const key = favKey("lisbon-2025", "friend@example.com"); // lowercased email
  assert.deepEqual([...STORE.keys()], [key]);
  assert.match(key, /^favs\/lisbon-2025\/[0-9a-f]{64}\.json$/);
  assert.ok(!key.includes(createHash("sha256").update("friend@example.com").digest("hex")), "salted");
  assert.doesNotMatch(STORE.get(key), /friend|example|someone/i);
  assert.deepEqual(JSON.parse(STORE.get(key)).ids, [A, C]);
  assert.deepEqual(ids(await favGet(jwt)), [A, C]);

  await favPost(jwt, { id: A, fav: false });
  assert.deepEqual(ids(await favPost(jwt, { id: C, fav: false })), []);
  assert.equal(STORE.size, 0); // removing the last one deletes the file
});

test("favourites: another person's token can't see or change mine", async () => {
  STORE.clear();
  const me = await token(claims("me@example.com"));
  const other = await token(claims("other@example.com"));
  await favPost(me, { id: A, fav: true });
  assert.deepEqual(ids(await favGet(other)), []);
  await favPost(other, { id: B, fav: true });
  await favPost(other, { id: A, fav: false }); // not theirs to remove
  assert.deepEqual(ids(await favGet(me)), [A]);
  assert.deepEqual(ids(await favGet(other)), [B]);
  assert.equal(STORE.size, 2);
});

test("favourites: a missing, forged, expired or other-app token is 401; cookies and the page never count", async () => {
  STORE.clear();
  const good = claims("me@example.com");
  const [h, , s] = (await token(good)).split(".");
  const bad = {
    missing: null,
    garbage: "not.a.jwt",
    "two parts": "abc.def",
    forged: await token(good, { key: attacker.privateKey }),
    "unknown key": await token(good, { key: attacker.privateKey, kid: "k2" }),
    "alg none": `${b64url({ alg: "none", kid: "k1" })}.${b64url(good)}.`,
    "payload swapped": `${h}.${b64url({ ...good, email: "victim@example.com" })}.${s}`,
    expired: await token({ ...good, exp: now() - 5 }),
    "no expiry": await token({ ...good, exp: undefined }),
    "not yet valid": await token({ ...good, nbf: now() + 600 }),
    "other team": await token({ ...good, iss: "https://evil.cloudflareaccess.com" }),
    "another trip's app": await token({ ...good, aud: [AUD["big-2025"]] }),
    "no audience": await token({ ...good, aud: [] }),
    "no email (service token)": await token({ ...good, email: undefined, common_name: "svc" }),
  };
  for (const [name, jwt] of Object.entries(bad)) {
    const r = await favGet(jwt);
    assert.equal(r.res.status, 401, name);
    assert.equal(r.res.headers.get("access-control-allow-origin"), SITE, name); // the site can tell "sign in"
    assert.equal((await favPost(jwt, { id: A, fav: true })).res.status, 401, name);
  }
  const valid = await token(good);
  const cookieOnly = await call(FAV, { headers: { origin: SITE, cookie: "CF_Authorization=" + valid } });
  assert.equal(cookieOnly.res.status, 401);
  assert.equal((await favGet(valid, "big-2025")).res.status, 401); // Lisbon's token doesn't open another trip
  assert.equal(STORE.size, 0);
});

test("favourites: a POST from any other origin is refused (403), whatever the token", async () => {
  STORE.clear();
  const jwt = await token(claims("me@example.com"));
  for (const origin of ["https://evil.example", "https://wander.example.com.evil.example", "http://wander.example.com", "null", null]) {
    assert.equal((await favPost(jwt, { id: A, fav: true }, { origin })).res.status, 403, String(origin));
  }
  assert.equal(STORE.size, 0);
  assert.equal((await favPost(jwt, { id: A, fav: true }, { origin: PREVIEW })).res.status, 200); // any SITE_ORIGINS one
});

test("favourites: unknown ids, bad bodies and other methods are refused", async () => {
  STORE.clear();
  const jwt = await token(claims("me@example.com"));
  const cases = [
    [{ id: "000000000000", fav: true }, 400],
    [{ id: ARCHIVED, fav: true }, 400],
    ["{not json", 400],
    ["null", 400],
    ['["x"]', 400],
    [{ id: A }, 400],
    [{ id: A, fav: "true" }, 400],
    [{ id: 12, fav: true }, 400],
    [{ id: A, fav: true, pad: "x".repeat(2000) }, 413],
  ];
  for (const [body, status] of cases) {
    assert.equal((await favPost(jwt, body)).res.status, status, JSON.stringify(body).slice(0, 60));
  }
  assert.equal((await favPost(jwt, "id=x", { type: "application/x-www-form-urlencoded" })).res.status, 415);
  assert.equal(STORE.size, 0);
  // application/json works too (non-browser clients; a browser would need the preflight Access refuses)
  assert.equal((await favPost(jwt, { id: A, fav: true }, { type: "application/json" })).res.status, 200);
  for (const method of ["PUT", "DELETE", "HEAD"]) {
    const r = await call(FAV, { method, headers: { origin: SITE, "cf-access-jwt-assertion": jwt } });
    assert.equal(r.res.status, 405, method);
  }
  assert.equal((await call("/lisbon-2025/trip.json", { method: "POST", body: "{}" })).res.status, 405);
  const porto = await token(claims("me@example.com", { aud: [AUD["porto-2026"]] }));
  assert.equal((await favGet(porto, "porto-2026")).res.status, 404); // set up, but no trip.json
});

test("favourites: at most 2,000 per person per trip", async () => {
  STORE.clear();
  const jwt = await token(claims("me@example.com", { aud: [AUD["big-2025"]] }));
  STORE.set(favKey("big-2025", "me@example.com"), JSON.stringify({ version: 1, ids: BIG.slice(0, 2000) }));
  const opts = { slug: "big-2025" };
  let r = await favPost(jwt, { id: BIG[2000], fav: true }, opts);
  assert.equal(r.res.status, 409);
  assert.match(r.body, /2000/);
  assert.equal((await favPost(jwt, { id: BIG[0], fav: true }, opts)).res.status, 200); // already in: fine
  assert.equal(ids(await favPost(jwt, { id: BIG[0], fav: false }, opts)).length, 1999);
  r = await favPost(jwt, { id: BIG[2000], fav: true }, opts);
  assert.equal(r.res.status, 200);
  assert.equal(ids(r).length, 2000);
});

test("favourites: shots archived since are dropped (a GET filters them, the next write prunes them)", async () => {
  STORE.clear();
  const jwt = await token(claims("me@example.com"));
  const key = favKey("lisbon-2025", "me@example.com");
  STORE.set(key, JSON.stringify({ version: 1, ids: [A, ARCHIVED, B] }));
  assert.deepEqual(ids(await favGet(jwt)), [A, B]);
  assert.deepEqual(JSON.parse(STORE.get(key)).ids, [A, ARCHIVED, B]); // a GET never writes
  assert.deepEqual(ids(await favPost(jwt, { id: C, fav: true })), [A, B, C]);
  assert.deepEqual(JSON.parse(STORE.get(key)).ids, [A, B, C]);
});

test("favs/ is never served as files, signed in or not", async () => {
  STORE.clear();
  const jwt = await token(claims("me@example.com"));
  await favPost(jwt, { id: A, fav: true });
  const key = favKey("lisbon-2025", "me@example.com");
  for (const p of [`/${key}`, "/favs/trip.json", "/favs/favorites", "/favs", "/favs/", "/favs/lisbon-2025/"]) {
    for (const method of ["GET", "HEAD", "POST"]) {
      const r = await call(p, { method, headers: { origin: SITE, "cf-access-jwt-assertion": jwt } });
      assert.equal(r.res.status, 404, `${method} ${p}`);
      assert.ok(!r.body.includes(A), `${method} ${p}`);
    }
  }
});

test("favourites not set up (team, salt, or this trip's AUD missing) → 500; everything else still works", async () => {
  const jwt = await token(claims("me@example.com"));
  const get = (e) => call(FAV, { headers: { origin: SITE, "cf-access-jwt-assertion": jwt } }, e);
  for (const e of [{ ACCESS_TEAM_DOMAIN: undefined }, { ACCESS_AUD: undefined }, { FAVS_SALT: undefined },
                   { ACCESS_AUD: { "big-2025": AUD["big-2025"] } }, { ACCESS_TEAM_DOMAIN: "http://lisbon-crew.cloudflareaccess.com" }]) {
    assert.equal((await get({ ...env, ...e })).res.status, 500, JSON.stringify(e));
    assert.equal((await call("/trips.json", {}, { ...env, ...e })).res.status, 200);
  }
  // ACCESS_AUD may also arrive as a JSON string (e.g. set in the dashboard)
  assert.equal((await get({ ...env, ACCESS_AUD: JSON.stringify(AUD) })).res.status, 200);
});

test("favourites: Access's keys are fetched once and cached; unreachable keys → 503", async () => {
  const jwt = await token(claims("me@example.com"));
  await favGet(jwt);
  const before = certsFetched.length;
  await favGet(jwt);
  await favPost(jwt, { id: B, fav: true });
  assert.equal(certsFetched.length, before);
  const down = "https://down.cloudflareaccess.com";
  const t = await token(claims("me@example.com", { iss: down }));
  const r = await call(FAV, { headers: { origin: SITE, "cf-access-jwt-assertion": t } }, { ...env, ACCESS_TEAM_DOMAIN: down });
  assert.equal(r.res.status, 503);
});
