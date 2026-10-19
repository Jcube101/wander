// wander-media: serves trip media from the private R2 bucket at
// https://<media host>/<key>
//
// Who may see what is decided by Cloudflare Access *before* this Worker runs:
// one Access application per trip covering
//   <media host>/<slug>        (the trip's data, photos and videos)
//   <media host>/auth/<slug>   (the sign-in hop used by the website)
// This Worker only serves an explicit allow-list of files, never lists the
// bucket, supports Range requests (video seeking), and answers the website's
// cross-site requests with cookies allowed. The one thing it writes is each
// visitor's own favourites (/<slug>/favorites, kept under favs/, never served).
// ?download=1 on a trip's card or full preview makes it a download with a readable name.
//
// Settings (wrangler.toml [vars]):
//   SITE_ORIGINS  comma-separated site origins, e.g. "https://wander.example.com".
//                 They get CORS with credentials, and /auth only sends people back
//                 to them. The first one is where /auth goes when no return is given.
//   ACCESS_TEAM_DOMAIN  e.g. "https://your-team.cloudflareaccess.com": issues the
//                 Access tokens and publishes the keys that sign them. Favourites only.
//   ACCESS_AUD    { "<slug>" = "<that trip's Access app AUD tag>" }. Favourites only:
//                 a trip missing here answers 500 on /<slug>/favorites.
// Secret (npx wrangler secret put FAVS_SALT): salts the hashed email in favourites'
// file names, so they can't be matched to known emails. Favourites only.

// Parsed once per SITE_ORIGINS value.
let parsed = { raw: null, list: [], set: new Set() };
function siteOrigins(env) {
  const raw = (env && env.SITE_ORIGINS) || "";
  if (raw !== parsed.raw) {
    const list = raw.split(",").map((s) => s.trim().replace(/\/+$/, "")).filter(Boolean);
    parsed = { raw, list, set: new Set(list) };
  }
  return parsed;
}

const ALLOWED = new RegExp(
  "^(?:" +
    "trips\\.json" +
    "|public/[\\w.-]+(?:/[\\w.-]+)*" +
    "|[a-z0-9-]+/(?:trip\\.json|thumbs/[\\w-]+\\.jpg|cards/[\\w-]+\\.jpg|media/[\\w-]+\\.(?:jpg|mp4))" +
  ")$"
);
const PUBLIC = /^(?:trips\.json|public\/.+)$/;
const TYPES = { json: "application/json", jpg: "image/jpeg", mp4: "video/mp4" };

function corsHeaders(request, sites) {
  const origin = request.headers.get("origin");
  if (!origin || !sites.set.has(origin)) return {};
  return {
    "access-control-allow-origin": origin,
    "access-control-allow-credentials": "true",
    "access-control-allow-methods": "GET, HEAD, POST, OPTIONS",
    "access-control-allow-headers": "range",
    "access-control-expose-headers": "content-length, content-range, accept-ranges, etag",
    vary: "Origin",
  };
}

function text(body, status, extra = {}) {
  return new Response(body, { status, headers: { "content-type": "text/plain; charset=utf-8", "cache-control": "no-store", ...extra } });
}

function cacheControl(key, isPublic) {
  const isData = key.endsWith(".json");
  if (isPublic) return isData ? "no-cache" : "public, max-age=3600";
  return isData ? "private, no-cache" : "private, max-age=604800"; // never in shared caches
}

// Email of the signed-in visitor, read from the Access cookie. Used only to show
// "Signed in as …" on the site — Access itself enforces who can see what.
function signedInEmail(request) {
  const m = (request.headers.get("cookie") || "").match(/(?:^|;\s*)CF_Authorization=([^;]+)/);
  if (!m) return null;
  try {
    const part = m[1].split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
    const payload = JSON.parse(atob(part + "=".repeat((4 - (part.length % 4)) % 4)));
    if (payload.exp && payload.exp * 1000 < Date.now()) return null;
    return payload.email || null;
  } catch {
    return null;
  }
}

// Only back to one of the site origins (exact scheme + host + port), else the fallback.
function safeReturn(raw, sites, fallback) {
  try {
    const u = new URL(raw);
    if (u.protocol === "https:" && sites.set.has(u.origin)) return u.toString();
  } catch {}
  return fallback;
}

// ---------------------------------------------------------------- favourites
// GET  /<slug>/favorites                          → {"ids": [...]}
// POST /<slug>/favorites  {"id": "...", "fav": b}  → the updated {"ids": [...]}
// Each signed-in visitor's own list, in favs/<slug>/<sha256(FAVS_SALT + email)>.json.
// The trip's Access app guards /<slug> already; on top of that the token Access
// forwards must verify, and the email comes only from it. POST must be a "simple"
// request (text/plain body): Access refuses the CORS preflight a JSON one would need.
const FAVORITES = /^([a-z0-9-]+)\/favorites$/;
const MAX_FAVS = 2000;
const MAX_BODY = 1024; // bytes; {"id":"<12 hex>","fav":false} is ~30
const TRIP_TTL = 60 * 1000; // a trip's item ids, per isolate
const CERTS_TTL = 60 * 60 * 1000;

class CertsUnavailable extends Error {}

function favoritesConfig(env, slug) {
  const team = String(env.ACCESS_TEAM_DOMAIN || "").trim().replace(/\/+$/, "");
  let auds = env.ACCESS_AUD;
  if (typeof auds === "string") {
    try { auds = JSON.parse(auds); } catch { auds = null; }
  }
  const aud = auds && typeof auds === "object" && Object.hasOwn(auds, slug) ? auds[slug] : null;
  const salt = String(env.FAVS_SALT || "").trim();
  if (!/^https:\/\/[a-z0-9.-]+$/.test(team) || typeof aud !== "string" || !aud || !salt) return null;
  return { team, aud, salt };
}

function base64url(s) {
  const bin = atob(s.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - (s.length % 4)) % 4));
  return Uint8Array.from(bin, (c) => c.charCodeAt(0));
}

// Access's signing keys, by key id. Refetched hourly, or (at most once a minute)
// when a token names a key we don't have, since Cloudflare rotates them.
let certs = { url: null, at: 0, keys: new Map() };
async function signingKey(team, kid) {
  const url = `${team}/cdn-cgi/access/certs`;
  const age = certs.url === url ? Date.now() - certs.at : Infinity;
  if (age > CERTS_TTL || (!certs.keys.has(kid) && age > 60 * 1000)) {
    let jwks;
    try {
      const r = await fetch(url);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      jwks = (await r.json()).keys || [];
    } catch (e) {
      throw new CertsUnavailable(String(e));
    }
    const keys = new Map();
    for (const jwk of jwks) {
      if (jwk.kty !== "RSA" || typeof jwk.kid !== "string") continue;
      try {
        keys.set(jwk.kid, await crypto.subtle.importKey("jwk", jwk, { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" }, false, ["verify"]));
      } catch { /* not a usable signing key */ }
    }
    certs = { url, at: Date.now(), keys };
  }
  return certs.keys.get(kid) || null;
}

// The visitor's email, lowercased, from the Access token on this request: signed by
// the team's keys, issued by the team, not expired, and for this trip's app. Else null.
// Only the Cf-Access-Jwt-Assertion header counts (Access sets it); never the page.
async function accessEmail(request, cfg) {
  const parts = (request.headers.get("cf-access-jwt-assertion") || "").split(".");
  if (parts.length !== 3) return null;
  let header, claims, signature;
  try {
    const decode = (p) => JSON.parse(new TextDecoder().decode(base64url(p)));
    header = decode(parts[0]);
    claims = decode(parts[1]);
    signature = base64url(parts[2]);
  } catch {
    return null;
  }
  if (!header || header.alg !== "RS256" || typeof header.kid !== "string" || !claims || typeof claims !== "object") return null;
  const key = await signingKey(cfg.team, header.kid);
  if (!key) return null;
  const signed = new TextEncoder().encode(`${parts[0]}.${parts[1]}`);
  if (!(await crypto.subtle.verify("RSASSA-PKCS1-v1_5", key, signature, signed))) return null;
  const now = Date.now() / 1000;
  const aud = Array.isArray(claims.aud) ? claims.aud : [claims.aud];
  if (claims.iss !== cfg.team || !aud.includes(cfg.aud)) return null;
  if (typeof claims.exp !== "number" || claims.exp <= now) return null;
  if (typeof claims.nbf === "number" && claims.nbf > now + 60) return null;
  if (typeof claims.email !== "string" || !claims.email.includes("@")) return null;
  return claims.email.toLowerCase();
}

// The items a trip publishes (archived shots aren't in trip.json), as id → {t, orig},
// and its zone: {items, tz}, or null if there's no trip.json. For favourites and downloads.
const trips = new Map();
async function tripIndex(env, slug) {
  const hit = trips.get(slug);
  if (hit && Date.now() - hit.at < TRIP_TTL) return hit;
  const obj = await env.BUCKET.get(`${slug}/trip.json`);
  if (!obj) {
    trips.delete(slug);
    return null;
  }
  const data = JSON.parse(await obj.text());
  const items = new Map();
  for (const x of data.items || []) {
    if (x && typeof x.id === "string") items.set(x.id, { t: x.t, orig: x.orig });
  }
  const trip = { at: Date.now(), items, tz: Number(data.tzOffsetMin) || 0 };
  trips.set(slug, trip);
  return trip;
}

async function favoritesKey(slug, salt, email) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(salt + email));
  const hex = [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
  return `favs/${slug}/${hex}.json`;
}

async function storedIds(env, key) {
  const obj = await env.BUCKET.get(key);
  if (!obj) return [];
  try {
    const ids = JSON.parse(await obj.text()).ids;
    return Array.isArray(ids) ? ids.filter((id) => typeof id === "string") : [];
  } catch {
    return [];
  }
}

// The body as text, or null if it's over `max` bytes.
async function readBody(request, max) {
  if (Number(request.headers.get("content-length")) > max) return null;
  if (!request.body) return "";
  const reader = request.body.getReader();
  const chunks = [];
  let size = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    size += value.byteLength;
    if (size > max) {
      await reader.cancel();
      return null;
    }
    chunks.push(value);
  }
  const all = new Uint8Array(size);
  let at = 0;
  for (const c of chunks) {
    all.set(c, at);
    at += c.byteLength;
  }
  return new TextDecoder().decode(all);
}

async function favorites(request, env, slug, sites, cors) {
  const fail = (msg, status, extra = {}) => text(msg, status, { ...cors, ...extra });
  const json = (ids) => new Response(JSON.stringify({ ids }), {
    status: 200,
    headers: { ...cors, "content-type": "application/json", "cache-control": "private, no-store", "x-content-type-options": "nosniff" },
  });
  if (request.method !== "GET" && request.method !== "POST") return fail("Method not allowed", 405, { allow: "GET, POST" });
  // CSRF: the cookie rides along on any site's form or fetch, so writes must come from ours.
  if (request.method === "POST" && !sites.set.has(request.headers.get("origin"))) return fail("Forbidden", 403);
  const cfg = favoritesConfig(env, slug);
  if (!cfg) return fail("Not configured: favourites need ACCESS_TEAM_DOMAIN, this trip in ACCESS_AUD, and FAVS_SALT", 500);
  let email;
  try {
    email = await accessEmail(request, cfg);
  } catch (e) {
    if (e instanceof CertsUnavailable) return fail("Couldn't check the sign-in; try again", 503);
    throw e;
  }
  if (!email) return fail("Sign in first", 401);
  const trip = await tripIndex(env, slug);
  if (!trip) return fail("Not found", 404);
  const ids = trip.items;
  const key = await favoritesKey(slug, cfg.salt, email);
  const current = (await storedIds(env, key)).filter((id) => ids.has(id)); // drops archived shots
  if (request.method === "GET") return json(current);

  const type = (request.headers.get("content-type") || "").split(";")[0].trim().toLowerCase();
  if (type !== "text/plain" && type !== "application/json") return fail("Send the JSON body as text/plain", 415);
  const raw = await readBody(request, MAX_BODY);
  if (raw === null) return fail("Too large", 413);
  let body;
  try {
    body = JSON.parse(raw);
  } catch {
    return fail("The body must be JSON", 400);
  }
  if (!body || typeof body !== "object" || typeof body.id !== "string" || typeof body.fav !== "boolean") {
    return fail('Expected {"id": "<item id>", "fav": true|false}', 400);
  }
  if (!ids.has(body.id)) return fail("No such item in this trip", 400);
  if (body.fav === current.includes(body.id)) return json(current);
  if (body.fav && current.length >= MAX_FAVS) return fail(`Too many favourites (at most ${MAX_FAVS} per trip)`, 409);
  const next = body.fav ? [...current, body.id] : current.filter((id) => id !== body.id);
  // Read-modify-write; last write wins (one person, a few taps a minute).
  if (next.length) {
    await env.BUCKET.put(key, JSON.stringify({ version: 1, ids: next, updated: new Date().toISOString() }),
      { httpMetadata: { contentType: "application/json" } });
  } else {
    await env.BUCKET.delete(key);
  }
  return json(next);
}

// ---------------------------------------------------------------- downloads
// GET /<slug>/cards|media/<id>.<ext>?download=1 → the same file, plus
// Content-Disposition: attachment; filename="<YYYY-MM-DD_HHMM>_<original name>.<ext>"
// (the shot's time in the trip's zone; SPEC.md → Downloads). Only download=1 counts, and
// no other parameter changes anything. tripmap/export_favs.py and the reference viewer
// name files the same way (shared cases: test/download-names.json).
const DOWNLOADABLE = /^([a-z0-9-]+)\/(?:cards|media)\/([\w-]+)\.(jpg|mp4)$/;
const NAME_MAX = 80;

// The original's name without its extension, reduced to A-Z a-z 0-9 . _ - (accents
// dropped, anything else → "_"), so it's safe in a header and on any file system.
function safeBase(orig, id) {
  const s = typeof orig === "string" ? orig : "";
  const dot = s.lastIndexOf(".");
  const base = (dot > 0 ? s.slice(0, dot) : s).normalize("NFKD").replace(/[̀-ͯ]/g, "")
    .replace(/[^A-Za-z0-9._-]+/g, "_").replace(/^[._-]+|[._-]+$/g, "");
  return base.slice(0, NAME_MAX).replace(/[._-]+$/, "") || id;
}

function downloadName(item, tz, id, ext) {
  const base = safeBase(item && item.orig, id);
  const t = item && item.t;
  if (typeof t !== "number" || !Number.isFinite(t)) return `${base}.${ext}`;
  const d = new Date((t + tz * 60) * 1000); // its UTC fields read as the trip's local time
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getUTCFullYear()}-${p(d.getUTCMonth() + 1)}-${p(d.getUTCDate())}_${p(d.getUTCHours())}${p(d.getUTCMinutes())}_${base}.${ext}`;
}

async function downloadFilename(env, slug, id, ext) {
  let trip = null;
  try {
    trip = await tripIndex(env, slug);
  } catch { /* unreadable trip.json: the plain name below */ }
  return downloadName(trip && trip.items.get(id), trip ? trip.tz : 0, id, ext);
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const sites = siteOrigins(env);
    const cors = corsHeaders(request, sites);

    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: { ...cors, "access-control-max-age": "86400" } });
    }

    // Use the path exactly as sent; our names never need %-encoding, so any
    // encoded character is refused (Access and this Worker can't disagree).
    const path = url.pathname.slice(1);
    if (path.includes("%") || path.includes("..") || path.includes("//")) return text("Not found", 404, cors);
    // People's favourites: only ever through /<slug>/favorites, never as files.
    if (path === "favs" || path.startsWith("favs/")) return text("Not found", 404, cors);

    const fav = path.match(FAVORITES);
    if (fav) return favorites(request, env, fav[1], sites, cors);

    if (request.method !== "GET" && request.method !== "HEAD") {
      return text("Method not allowed", 405, { allow: "GET, HEAD" });
    }

    // Sign-in hop: Access guards /auth/<slug>; once signed in, send them back.
    const auth = path.match(/^auth\/([a-z0-9-]+)$/);
    if (auth) {
      if (!sites.list.length) return text("Not configured: set SITE_ORIGINS in wrangler.toml", 500);
      const back = safeReturn(url.searchParams.get("return"), sites, `${sites.list[0]}/${auth[1]}`);
      return new Response(null, { status: 302, headers: { location: back, "cache-control": "no-store" } });
    }

    // Who's signed in (for the site's "Signed in as …").
    if (path === "me") {
      return new Response(JSON.stringify({ email: signedInEmail(request) }), {
        status: 200, headers: { ...cors, "content-type": "application/json", "cache-control": "private, no-store" },
      });
    }

    const key = path;
    if (!key || !ALLOWED.test(key)) return text("Not found", 404, cors);
    const isPublic = PUBLIC.test(key);
    const extra = isPublic ? { ...cors, "access-control-allow-origin": cors["access-control-allow-origin"] || "*" } : cors;
    if (isPublic && !cors["access-control-allow-origin"]) delete extra["access-control-allow-credentials"];

    const obj = request.method === "HEAD"
      ? await env.BUCKET.head(key)
      : await env.BUCKET.get(key, { range: request.headers, onlyIf: request.headers });
    if (!obj) return text("Not found", 404, cors);

    const headers = new Headers(extra);
    obj.writeHttpMetadata(headers);
    if (!headers.get("content-type")) headers.set("content-type", TYPES[key.split(".").pop()] || "application/octet-stream");
    headers.set("etag", obj.httpEtag);
    headers.set("accept-ranges", "bytes");
    headers.set("cache-control", cacheControl(key, isPublic));
    headers.set("x-content-type-options", "nosniff");
    const dl = !isPublic && url.searchParams.get("download") === "1" ? key.match(DOWNLOADABLE) : null;
    if (dl) headers.set("content-disposition", `attachment; filename="${await downloadFilename(env, dl[1], dl[2], dl[3])}"`);

    if (request.method === "HEAD") {
      headers.set("content-length", String(obj.size));
      return new Response(null, { status: 200, headers });
    }
    if (!("body" in obj) || obj.body === null) return new Response(null, { status: 304, headers });

    const r = request.headers.has("range") ? obj.range : undefined;
    if (r) {
      let offset, length;
      if ("suffix" in r && r.suffix !== undefined) { length = Math.min(r.suffix, obj.size); offset = obj.size - length; }
      else { offset = r.offset ?? 0; length = r.length ?? obj.size - offset; }
      headers.set("content-range", `bytes ${offset}-${offset + length - 1}/${obj.size}`);
      headers.set("content-length", String(length));
      return new Response(obj.body, { status: 206, headers });
    }
    headers.set("content-length", String(obj.size));
    return new Response(obj.body, { status: 200, headers });
  },
};
