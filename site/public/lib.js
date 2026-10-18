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
