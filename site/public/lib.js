// Pure helpers for the reference viewer: no DOM, no network. Tested by site/test/test_site.mjs.
// Everything here follows SPEC.md → "Data contract — build your own site".

export const SLUG = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const WD = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

export function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

/** base + path with exactly one slash between them. */
export function joinUrl(base, path) {
  return `${String(base).replace(/\/+$/, "")}/${String(path).replace(/^\/+/, "")}`;
}

/** config.js overridden key by key by config.local.js (gitignored, for your own values).
 *  `importLocal` loads that file. One that can't be fetched (TypeError: missing, or a host's
 *  HTML fallback) is skipped silently; one that's there but fails to run gets a warning. */
export async function loadConfig(base, importLocal) {
  try {
    const local = (await importLocal()).default;
    return { ...base, ...(local && typeof local === "object" ? local : {}) };
  } catch (e) {
    if (!(e instanceof TypeError)) console.warn("config.local.js failed to load; using config.js.", e);
    return { ...base };
  }
}

/** Landing-page cover: the 1600 px coverImage when there is one, else the 640 px cover. */
export function coverUrl(media, trip) {
  const p = trip.coverImage || trip.cover;
  return p ? joinUrl(media, p) : null;
}

/** Card-sized cover for the trip grid: the 640 px cover first. */
export function cardCoverUrl(media, trip) {
  const p = trip.cover || trip.coverImage;
  return p ? joinUrl(media, p) : null;
}

/** An item's file (thumb/card/media paths are relative to <slug>/). */
export function itemUrl(media, slug, path) {
  return path ? joinUrl(media, `${slug}/${path}`) : null;
}

export function tripDataUrl(media, slug) {
  return joinUrl(media, `${slug}/trip.json`);
}

/** The trip a page is about: ?trip=<slug>, else a /<slug> path (e.g. Pages' SPA fallback). */
export function slugFromLocation({ search = "", pathname = "/" }) {
  const q = new URLSearchParams(search).get("trip");
  if (q !== null) return SLUG.test(q) ? q : null;
  const last = pathname.replace(/\/+$/, "").split("/").pop() || "";
  return SLUG.test(last) && last !== "index" ? last : null;
}

export function tripHref(slug) {
  return `?trip=${encodeURIComponent(slug)}`;
}

/** Sign-in hop: the trip's Access app guards /auth/<slug>; the Worker sends people back to
 *  `return` (if it's one of its SITE_ORIGINS) with ?signedin=1 so the page knows. */
export function signInUrl(media, slug, pageHref) {
  const back = new URL(pageHref);
  back.searchParams.set("signedin", "1");
  return `${joinUrl(media, `auth/${encodeURIComponent(slug)}`)}?return=${encodeURIComponent(back.href)}`;
}

export function signOutUrl(media) {
  return joinUrl(media, "cdn-cgi/access/logout");
}

/** pageHref without ?signedin (for history.replaceState once the trip has loaded). */
export function withoutSignedIn(pageHref) {
  const u = new URL(pageHref);
  u.searchParams.delete("signedin");
  return u.href;
}

/** A Date whose UTC fields read as the trip's local time. */
export function tripClock(t, tzOffsetMin = 0) {
  return new Date((t + tzOffsetMin * 60) * 1000);
}

export function fmtTime(t, tzOffsetMin) {
  const d = tripClock(t, tzOffsetMin);
  return `${String(d.getUTCHours()).padStart(2, "0")}:${String(d.getUTCMinutes()).padStart(2, "0")}`;
}

/** "YYYY-MM-DD" → "Fri 2 May" */
export function fmtDay(key) {
  const d = new Date(`${key}T00:00:00Z`);
  return `${WD[d.getUTCDay()]} ${d.getUTCDate()} ${MON[d.getUTCMonth()]}`;
}

/** "2–8 May 2025", "28 Apr – 3 May 2025", "30 Dec 2025 – 2 Jan 2026" */
export function fmtRange(start, end) {
  if (!start) return "";
  const a = new Date(`${start}T00:00:00Z`), b = new Date(`${(end || start)}T00:00:00Z`);
  const [da, ma, ya] = [a.getUTCDate(), MON[a.getUTCMonth()], a.getUTCFullYear()];
  const [db, mb, yb] = [b.getUTCDate(), MON[b.getUTCMonth()], b.getUTCFullYear()];
  if (start === (end || start)) return `${da} ${ma} ${ya}`;
  if (ya !== yb) return `${da} ${ma} ${ya} – ${db} ${mb} ${yb}`;
  if (ma !== mb) return `${da} ${ma} – ${db} ${mb} ${yb}`;
  return `${da}–${db} ${mb} ${yb}`;
}

export function fmtDuration(s) {
  if (!s) return "";
  const r = Math.round(s);
  return r >= 60 ? `${Math.floor(r / 60)}:${String(r % 60).padStart(2, "0")}` : `${r}s`;
}

function plural(n, word) {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}

/** "7 days · 350 photos · 62 videos" from a trips.json entry or a trip.json */
export function tripSummary(trip) {
  const c = trip.counts || {};
  const days = typeof trip.days === "number" ? trip.days : (trip.days || []).length;
  const parts = [];
  if (days) parts.push(plural(days, "day"));
  if (c.photos) parts.push(plural(c.photos, "photo"));
  if (c.videos) parts.push(plural(c.videos, "video"));
  return parts.join(" · ");
}

/** Newest trip first (trips.json is already sorted; this keeps the page right if it isn't). */
export function sortTrips(trips) {
  return [...(trips || [])].sort((a, b) => String(b.start || "").localeCompare(String(a.start || "")));
}

/** Items in time order, optionally only one day ("all" = every day). */
export function itemsFor(items, day = "all") {
  return [...(items || [])].filter((x) => day === "all" || x.day === day).sort((a, b) => a.t - b.t);
}

export function isPlaced(x) {
  return typeof x.lat === "number" && typeof x.lon === "number";
}

/** Day chip label: "Day 3 · Fri 2 May" */
export function dayLabel(d) {
  return `Day ${d.n} · ${fmtDay(d.key)}`;
}

/** Caption for one item: "Day 3 · Fri 2 May · 14:05" */
export function itemCaption(x, tzOffsetMin) {
  const day = x.dayN ? `Day ${x.dayN} · ` : "";
  return `${day}${fmtDay(x.day)} · ${fmtTime(x.t, tzOffsetMin)}`;
}

/** Next/previous index in a list, wrapping around. */
export function step(i, n, delta) {
  return n ? (((i + delta) % n) + n) % n : -1;
}

// ---------------------------------------------------------------- favourites
// The visitor's own favourites in a trip, kept by the Worker (SPEC.md → Favourites).

export function favoritesUrl(media, slug) {
  return joinUrl(media, `${slug}/favorites`);
}

/** The POST body. Sent as text/plain, so the browser makes a "simple" request with
 *  no CORS preflight (Access would refuse the preflight a JSON content type needs). */
export function favoriteBody(id, fav) {
  return JSON.stringify({ id: String(id), fav: Boolean(fav) });
}

/** What a response from the media host means (fetch with redirect: "manual"): "ok";
 *  "signed-out" (the Worker said 401, or a readable redirect to Access's login); else "error".
 *  When Access's redirect has no CORS headers, fetch rejects instead: ask /me. */
export function accessOutcome(res) {
  if (res.type === "opaqueredirect" || res.status === 401) return "signed-out";
  return res.ok ? "ok" : "error";
}

/** The ids in a favourites response that this page knows, as a Set. */
export function favoriteIds(data, known) {
  const ids = data && Array.isArray(data.ids) ? data.ids : [];
  return new Set(ids.filter((id) => typeof id === "string" && known.has(id)));
}

/** A copy of `favs` with `id` added (fav) or removed. */
export function withFavorite(favs, id, fav) {
  const next = new Set(favs);
  if (fav) next.add(id);
  else next.delete(id);
  return next;
}

/** The favourites among `items`, in time order. */
export function favoriteItems(items, favs) {
  return itemsFor(items).filter((x) => favs.has(x.id));
}

export function favoritesLabel(n) {
  return `Favourites (${n})`;
}

/** Runs async tasks one at a time, in order; a failed task doesn't stop the next.
 *  Favourite taps go through one of these, so two quick taps can't overwrite each other. */
export function serial() {
  let tail = Promise.resolve();
  return (task) => {
    const run = tail.then(task);
    tail = run.catch(() => {});
    return run;
  };
}

// ---------------------------------------------------------------- downloads
// One file per item: the full preview, else the card (SPEC.md → Downloads).

export const ZIP_MAX = 500e6; // bytes in one favourites ZIP: built in memory, so kept modest
const NAME_MAX = 80;

export function downloadPath(x) {
  return x.media || x.card || null;
}

/** The item's file with ?download=1: the Worker answers with Content-Disposition: attachment. */
export function downloadUrl(media, slug, x) {
  const p = downloadPath(x);
  return p ? `${itemUrl(media, slug, p)}?download=1` : null;
}

/** "<YYYY-MM-DD_HHMM>_<original name>.<ext>", the time in the trip's zone: the Worker's
 *  ?download=1 name and tripmap/export_favs.py's (shared cases: worker/test/download-names.json).
 *  The name keeps A-Z a-z 0-9 . _ - only (accents dropped, anything else → "_"). */
export function fileName({ id, orig, t }, tzOffsetMin, ext) {
  const s = typeof orig === "string" ? orig : "";
  const dot = s.lastIndexOf(".");
  const base = (dot > 0 ? s.slice(0, dot) : s).normalize("NFKD").replace(/[̀-ͯ]/g, "")
    .replace(/[^A-Za-z0-9._-]+/g, "_").replace(/^[._-]+|[._-]+$/g, "").slice(0, NAME_MAX).replace(/[._-]+$/, "") || id;
  if (typeof t !== "number" || !Number.isFinite(t)) return `${base}.${ext}`;
  const d = tripClock(t, tzOffsetMin || 0);
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getUTCFullYear()}-${p(d.getUTCMonth() + 1)}-${p(d.getUTCDate())}_${p(d.getUTCHours())}${p(d.getUTCMinutes())}_${base}.${ext}`;
}

export function downloadName(x, tzOffsetMin) {
  return fileName(x, tzOffsetMin, (downloadPath(x) || "").split(".").pop() || "jpg");
}

/** name, or name_2, name_3 … before the extension, not in `used` (case-insensitive, as on
 *  Windows and macOS). Adds it to `used`. */
export function uniqueName(name, used) {
  const dot = name.lastIndexOf(".");
  const [stem, ext] = dot > 0 ? [name.slice(0, dot), name.slice(dot)] : [name, ""];
  let candidate = name;
  for (let n = 2; used.has(candidate.toLowerCase()); n++) candidate = `${stem}_${n}${ext}`;
  used.add(candidate.toLowerCase());
  return candidate;
}

/** Decimal units, like the R2 dashboard: "840 KB", "8.4 MB", "84 MB", "1.2 GB". */
export function fmtBytes(n) {
  if (n < 1e6) return `${Math.max(1, Math.round(n / 1e3))} KB`;
  if (n < 1e7) return `${(n / 1e6).toFixed(1)} MB`;
  if (n < 1e9) return `${Math.round(n / 1e6)} MB`;
  return `${(n / 1e9).toFixed(1)} GB`;
}

/** What a ZIP of these items would hold: files, bytes (from trip.json's "bytes") and how
 *  many have no size there (trips built before it existed). */
export function zipEstimate(items) {
  const files = items.filter((x) => downloadPath(x));
  const known = files.filter((x) => Number.isFinite(x.bytes));
  return { files: files.length, bytes: known.reduce((n, x) => n + x.bytes, 0), unknown: files.length - known.length };
}

/** Desktop only: a mouse, and room. Phones and tablets save one shot at a time instead. */
export function isDesktop(matchMedia) {
  return matchMedia("(hover: hover) and (pointer: fine)").matches && matchMedia("(min-width: 821px)").matches;
}

const CRC_TABLE = Uint32Array.from({ length: 256 }, (_, n) => {
  let c = n;
  for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
  return c >>> 0;
});

/** CRC-32 (as in ZIP), continued from `crc` so a file can be checked as it streams in. */
export function crc32(bytes, crc = 0) {
  let c = (crc ^ 0xffffffff) >>> 0;
  for (let i = 0; i < bytes.length; i++) c = CRC_TABLE[(c ^ bytes[i]) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

/** MS-DOS date and time (ZIP's) of a moment in the trip's zone. */
export function dosDateTime(t, tzOffsetMin) {
  const d = tripClock(Number.isFinite(t) ? t : 0, tzOffsetMin || 0);
  const y = d.getUTCFullYear();
  if (y < 1980) return { date: (1 << 5) | 1, time: 0 };
  return {
    date: ((Math.min(y, 2107) - 1980) << 9) | ((d.getUTCMonth() + 1) << 5) | d.getUTCDate(),
    time: (d.getUTCHours() << 11) | (d.getUTCMinutes() << 5) | (d.getUTCSeconds() >> 1),
  };
}

/** A ZIP of stored (uncompressed) files: photos and videos don't compress. add() takes each
 *  file once it has fully arrived, with its CRC-32 and size, so a file that fails halfway
 *  leaves nothing behind; finish() returns the whole ZIP as Blob parts, in order. No ZIP64:
 *  under 4 GB and 65,535 files (ZIP_MAX keeps it far below). */
export function zipWriter() {
  const enc = new TextEncoder();
  const parts = [], central = [];
  let offset = 0;
  return {
    get size() { return offset; },
    get count() { return central.length; },
    add(name, data, { crc, size, t, tzOffsetMin }) {
      const n = enc.encode(name);
      if (offset + 30 + n.length + size > 0xffffffff || central.length >= 0xffff) throw new RangeError("ZIP too large");
      const { date, time } = dosDateTime(t, tzOffsetMin);
      const local = new Uint8Array(30 + n.length);
      const l = new DataView(local.buffer);
      l.setUint32(0, 0x04034b50, true); // local file header
      l.setUint16(4, 20, true); // version needed
      l.setUint16(6, 0x0800, true); // names are UTF-8
      l.setUint16(8, 0, true); // stored
      l.setUint16(10, time, true);
      l.setUint16(12, date, true);
      l.setUint32(14, crc >>> 0, true);
      l.setUint32(18, size, true);
      l.setUint32(22, size, true);
      l.setUint16(26, n.length, true);
      local.set(n, 30);
      const cd = new Uint8Array(46 + n.length);
      const c = new DataView(cd.buffer);
      c.setUint32(0, 0x02014b50, true); // central directory header
      c.setUint16(4, 20, true); // made by
      c.setUint16(6, 20, true); // version needed
      c.setUint16(8, 0x0800, true);
      c.setUint16(10, 0, true);
      c.setUint16(12, time, true);
      c.setUint16(14, date, true);
      c.setUint32(16, crc >>> 0, true);
      c.setUint32(20, size, true);
      c.setUint32(24, size, true);
      c.setUint16(28, n.length, true);
      c.setUint32(42, offset, true); // where its local header is
      cd.set(n, 46);
      parts.push(local, ...data);
      central.push(cd);
      offset += local.length + size;
    },
    finish() {
      const cdSize = central.reduce((n, c) => n + c.length, 0);
      const end = new Uint8Array(22);
      const e = new DataView(end.buffer);
      e.setUint32(0, 0x06054b50, true); // end of central directory
      e.setUint16(8, central.length, true);
      e.setUint16(10, central.length, true);
      e.setUint32(12, cdSize, true);
      e.setUint32(16, offset, true);
      return [...parts, ...central, end];
    },
  };
}
