// wander-media: serves trip media from the private R2 bucket at
// https://media.job-joseph.com/<key>
//
// Who may see what is decided by Cloudflare Access *before* this Worker runs:
// one Access application per trip covering
//   media.job-joseph.com/<slug>        (the trip's data, photos and videos)
//   media.job-joseph.com/auth/<slug>   (the sign-in hop used by the website)
// This Worker only serves an explicit allow-list of files, never lists the
// bucket, supports Range requests (video seeking), and answers the website's
// cross-site requests from wander.job-joseph.com with cookies allowed.

const SITE_ORIGINS = new Set([
  "https://wander.job-joseph.com",
  "https://id-preview--a7f27062-3286-4c42-bf0c-e191ee723d94.lovable.app", // Lovable preview
]);
const SITE_HOST_SUFFIX = ".job-joseph.com"; // where /auth may send people back to

const ALLOWED = new RegExp(
  "^(?:" +
    "trips\\.json" +
    "|public/[\\w.-]+(?:/[\\w.-]+)*" +
    "|[a-z0-9-]+/(?:trip\\.json|thumbs/[\\w-]+\\.jpg|cards/[\\w-]+\\.jpg|media/[\\w-]+\\.(?:jpg|mp4))" +
  ")$"
);
const PUBLIC = /^(?:trips\.json|public\/.+)$/;
const TYPES = { json: "application/json", jpg: "image/jpeg", mp4: "video/mp4" };

function corsHeaders(request) {
  const origin = request.headers.get("origin");
  if (!origin || !SITE_ORIGINS.has(origin)) return {};
  return {
    "access-control-allow-origin": origin,
    "access-control-allow-credentials": "true",
    "access-control-allow-methods": "GET, HEAD, OPTIONS",
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

function safeReturn(raw, fallback) {
  try {
    const u = new URL(raw);
    if (u.protocol === "https:" && (u.hostname === SITE_HOST_SUFFIX.slice(1) || u.hostname.endsWith(SITE_HOST_SUFFIX))) return u.toString();
  } catch {}
  return fallback;
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const cors = corsHeaders(request);

    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: { ...cors, "access-control-max-age": "86400" } });
    }
    if (request.method !== "GET" && request.method !== "HEAD") {
      return text("Method not allowed", 405, { allow: "GET, HEAD" });
    }

    // Use the path exactly as sent; our names never need %-encoding, so any
    // encoded character is refused (Access and this Worker can't disagree).
    const path = url.pathname.slice(1);
    if (path.includes("%") || path.includes("..") || path.includes("//")) return text("Not found", 404, cors);

    // Sign-in hop: Access guards /auth/<slug>; once signed in, send them back.
    const auth = path.match(/^auth\/([a-z0-9-]+)$/);
    if (auth) {
      const back = safeReturn(url.searchParams.get("return"), `https://wander.job-joseph.com/${auth[1]}`);
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
