// Wander reference viewer: a static page that reads trips.json and <slug>/trip.json from the
// media host (SPEC.md → "Data contract — build your own site"). No build step, no storage:
// trip data lives only in memory. Map code follows the local editor (tripmap/viewer.html).
import base from "./config.js";
import * as W from "./lib.js";

// Your own values go in config.local.js (gitignored); it's optional.
const config = await W.loadConfig(base, () => import("./config.local.js"));
const MEDIA = String(config.media || "").replace(/\/+$/, "");
const TITLE = config.title || "Wander";
const $ = (s, el = document) => el.querySelector(s);
const esc = W.escapeHtml;
const view = $("#view");
document.title = TITLE;
$("#brand").textContent = TITLE;

function notice(html) {
  const n = $("#notice");
  n.innerHTML = html;
  n.hidden = false;
}

try {
  if (/(^|\.)example\.com$/.test(new URL(MEDIA).hostname)) {
    notice("This viewer still points at <code>media.example.com</code>. Put your media host in <code>config.local.js</code> (see site/README.md).");
  }
} catch {
  notice("<code>config.local.js</code> (or <code>config.js</code>) needs your media host, e.g. <code>https://media.example.com</code>.");
}

// ---------------------------------------------------------------- network
// Everything on the media host goes with the Access cookie (credentials: "include").
async function getJson(url, { publicFallback = false } = {}) {
  try {
    const r = await fetch(url, { credentials: "include" });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return await r.json();
  } catch (e) {
    // An origin missing from the Worker's SITE_ORIGINS gets "access-control-allow-origin: *",
    // which a credentialed fetch rejects. Public files still load without the cookie.
    if (!publicFallback || !(e instanceof TypeError)) throw e;
    const r = await fetch(url, { credentials: "omit" });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    notice(`This page's origin (<code>${esc(location.origin)}</code>) isn't in the Worker's <code>SITE_ORIGINS</code>, so trips can't open from here. Add it in <code>worker/wrangler.toml</code> and redeploy the Worker.`);
    return r.json();
  }
}

// 200 = this visitor may open the trip; Access answers anything else (or a redirect the
// browser won't follow cross-site) when they may not.
async function canOpen(slug) {
  try {
    const r = await fetch(W.tripDataUrl(MEDIA, slug), { method: "HEAD", credentials: "include" });
    return r.ok;
  } catch {
    return false;
  }
}

async function showWho() {
  try {
    const { email } = await getJson(W.joinUrl(MEDIA, "me"));
    if (email) {
      $("#who").innerHTML = `Signed in as ${esc(email)} · <a href="${esc(W.signOutUrl(MEDIA))}">Sign out</a>`;
    }
  } catch { /* not signed in, or the Worker is unreachable: say nothing */ }
}

// ---------------------------------------------------------------- landing
async function landing() {
  let data;
  try {
    data = await getJson(W.joinUrl(MEDIA, "trips.json"), { publicFallback: true });
  } catch (e) {
    view.innerHTML = `<p class="pad muted">Couldn't load the list of trips from ${esc(MEDIA)} (${esc(e.message)}).</p>`;
    return;
  }
  const trips = W.sortTrips(data.trips);
  view.innerHTML = `<section class="landing">
    <h1>Trips</h1>
    <p class="lede">Each trip opens only for the people who were on it. Sign in with your email to see yours.</p>
    <div class="trips">${trips.map(tripCard).join("") || '<p class="muted">No trips yet.</p>'}</div>
  </section>`;
  for (const el of view.querySelectorAll("[data-lock]")) {
    canOpen(el.dataset.lock).then((ok) => {
      el.textContent = ok ? "Open" : "🔒 Private";
      el.classList.toggle("open", ok);
    });
  }
}

function tripCard(t) {
  const img = W.cardCoverUrl(MEDIA, t);
  return `<a class="trip-card" href="${esc(W.tripHref(t.slug))}">
    <div class="img">${img ? `<img src="${esc(img)}" alt="" loading="lazy">` : ""}<span class="lock" data-lock="${esc(t.slug)}">…</span></div>
    <div class="meta"><h2>${esc(t.title)}</h2><p>${esc(W.fmtRange(t.start, t.end))}</p><p>${esc(W.tripSummary(t))}</p></div>
  </a>`;
}

// ---------------------------------------------------------------- a trip
function privatePage(slug, justSignedIn) {
  document.title = `Private trip · ${TITLE}`;
  const body = justSignedIn
    ? `<p>You're signed in, but this trip hasn't been shared with your email. Ask whoever runs this site to add you, or <a href="${esc(W.signOutUrl(MEDIA))}">sign out</a> and use another address.</p>`
    : `<p>Only the people who were on this trip can see it. Sign in with your email; you'll get a one-time code.</p>
       <p><a class="btn" href="${esc(W.signInUrl(MEDIA, slug, location.href))}">Sign in</a></p>`;
  view.innerHTML = `<section class="private"><h1>This trip is private</h1>${body}<p><a href="/">← All trips</a></p></section>`;
}

async function tripPage(slug) {
  const justSignedIn = new URLSearchParams(location.search).has("signedin");
  let trip;
  try {
    trip = await getJson(W.tripDataUrl(MEDIA, slug));
  } catch {
    return privatePage(slug, justSignedIn);
  }
  if (justSignedIn) history.replaceState(null, "", W.withoutSignedIn(location.href));
  document.title = `${trip.title} · ${TITLE}`;
  document.body.classList.add("trip-mode");
  const tz = trip.tzOffsetMin || 0;
  const url = (p) => W.itemUrl(MEDIA, slug, p);
  const items = W.itemsFor(trip.items);
  const byId = new Map(items.map((x) => [x.id, x]));

  view.innerHTML = `<section class="trip-head"><a href="/" class="muted">← All trips</a>
      <h1>${esc(trip.title)}</h1><p>${esc(W.fmtRange(trip.start, trip.end))} · ${esc(W.tripSummary(trip))}</p></section>
    <nav class="days" id="days" aria-label="Days"></nav>
    <div class="split"><div id="map" role="region" aria-label="Map"></div><section class="grid" id="grid" aria-label="Photos and videos"></section></div>`;

  // Map: the editor's tiles (Esri; CARTO needs a key, LEARNINGS D9), thumbnail pins and photo clusters.
  const map = L.map("map", { worldCopyJump: true });
  const esri = (svc, maxN) => L.tileLayer(`https://server.arcgisonline.com/ArcGIS/rest/services/${svc}/MapServer/tile/{z}/{y}/{x}`,
    { maxZoom: 20, maxNativeZoom: maxN, attribution: "Tiles &copy; Esri &mdash; Esri, HERE, Garmin, &copy; OpenStreetMap contributors" });
  const bases = {
    Streets: esri("World_Street_Map", 19),
    Satellite: esri("World_Imagery", 19),
    Dark: esri("Canvas/World_Dark_Gray_Base", 16),
  };
  (matchMedia("(prefers-color-scheme: dark)").matches ? bases.Dark : bases.Streets).addTo(map);
  L.control.layers(bases, null, { position: "topright" }).addTo(map);
  const cluster = L.markerClusterGroup({
    maxClusterRadius: 50, showCoverageOnHover: false, spiderfyOnMaxZoom: true,
    iconCreateFunction: (c) => {
      const ms = c.getAllChildMarkers().map((m) => byId.get(m.options.itemId)).sort((a, b) => a.t - b.t);
      const first = ms.find((x) => x.thumb);
      return L.divIcon({ className: "", iconSize: [54, 54],
        html: `<div class="cl">${first ? `<img src="${esc(url(first.thumb))}" alt="">` : ""}<span>${ms.length}</span></div>` });
    },
  });
  map.addLayer(cluster);
  const markers = new Map();
  for (const x of items.filter(W.isPlaced)) {
    const m = L.marker([x.lat, x.lon], {
      itemId: x.id, title: W.itemCaption(x, tz),
      icon: L.divIcon({ className: "", iconSize: [46, 46],
        html: `<div class="pin ${x.type === "video" ? "v" : ""}">${x.thumb ? `<img src="${esc(url(x.thumb))}" alt="" loading="lazy">` : ""}</div>` }),
    });
    m.on("click", () => openLb(x.id));
    markers.set(x.id, m);
  }

  // Days and the gallery
  let current = items;
  const chips = $("#days");
  const days = [{ key: "all", label: "All days", sub: `${items.length} shots` },
    ...(trip.days || []).map((d) => ({ key: d.key, label: `Day ${d.n}`, sub: `${W.fmtDay(d.key)} · ${d.count}` }))];
  chips.innerHTML = days.map((d) =>
    `<button class="chip" data-day="${esc(d.key)}" aria-pressed="false">${esc(d.label)}<small>${esc(d.sub)}</small></button>`).join("");
  chips.addEventListener("click", (e) => {
    const b = e.target.closest("[data-day]");
    if (b) setDay(b.dataset.day);
  });
  const grid = $("#grid");
  grid.addEventListener("click", (e) => {
    const b = e.target.closest("[data-id]");
    if (b) openLb(b.dataset.id);
  });

  function setDay(day) {
    current = W.itemsFor(items, day);
    for (const b of chips.querySelectorAll("[data-day]")) b.setAttribute("aria-pressed", String(b.dataset.day === day));
    grid.innerHTML = current.map((x) => {
      const src = url(x.card || x.thumb);
      return `<button class="tile" data-id="${esc(x.id)}" aria-label="${esc(W.itemCaption(x, tz))}">
        ${src ? `<img src="${esc(src)}" alt="" loading="lazy">` : ""}
        <span class="t">${esc(W.fmtTime(x.t, tz))}</span>${x.type === "video" ? `<span class="v">▶ ${esc(W.fmtDuration(x.dur))}</span>` : ""}
      </button>`;
    }).join("") || '<p class="muted">Nothing on this day.</p>';
    grid.scrollTop = 0;
    cluster.clearLayers();
    const placed = current.filter((x) => markers.has(x.id));
    cluster.addLayers(placed.map((x) => markers.get(x.id)));
    if (placed.length) map.fitBounds(L.latLngBounds(placed.map((x) => [x.lat, x.lon])).pad(0.15), { maxZoom: 15 });
    else map.setView([20, 0], 2);
  }
  setDay("all");

  // Lightbox
  const lb = $("#lb"), stage = $("#lb-stage"), onmap = $("#lb-onmap");
  let list = [], idx = -1;
  function openLb(id) {
    list = current;
    idx = list.findIndex((x) => x.id === id);
    if (idx < 0) { list = items; idx = items.findIndex((x) => x.id === id); }
    if (idx < 0) return;
    lb.hidden = false;
    document.body.style.overflow = "hidden";
    show();
    $("#lb-close").focus();
  }
  function show() {
    const x = list[idx];
    // No crossorigin attribute on media tags: it would drop the Access cookie (client rules).
    stage.innerHTML = x.type === "video"
      ? `<video src="${esc(url(x.media))}" poster="${esc(url(x.card) || "")}" controls autoplay playsinline preload="metadata"></video>`
      : `<img src="${esc(url(x.media || x.card || x.thumb))}" alt="${esc(W.itemCaption(x, tz))}">`;
    $("#lb-caption").textContent = W.itemCaption(x, tz) + (x.type === "video" && x.dur ? ` · ${W.fmtDuration(x.dur)}` : "");
    onmap.hidden = !markers.has(x.id);
    for (const t of grid.querySelectorAll(".tile.cur")) t.classList.remove("cur");
    grid.querySelector(`[data-id="${CSS.escape(x.id)}"]`)?.classList.add("cur");
  }
  function closeLb() {
    lb.hidden = true;
    stage.innerHTML = ""; // stops a playing video
    document.body.style.overflow = "";
  }
  $("#lb-close").onclick = closeLb;
  $("#lb-prev").onclick = () => { idx = W.step(idx, list.length, -1); show(); };
  $("#lb-next").onclick = () => { idx = W.step(idx, list.length, 1); show(); };
  onmap.onclick = () => {
    const m = markers.get(list[idx].id);
    closeLb();
    if (m) cluster.zoomToShowLayer(m, () => m.getElement()?.scrollIntoView({ block: "nearest" }));
  };
  lb.addEventListener("click", (e) => { if (e.target === lb || e.target === stage) closeLb(); });
  addEventListener("keydown", (e) => {
    if (lb.hidden) return;
    if (e.key === "Escape") closeLb();
    else if (e.key === "ArrowLeft") $("#lb-prev").click();
    else if (e.key === "ArrowRight") $("#lb-next").click();
  });
}

// ---------------------------------------------------------------- start
if (!window.L || !L.markerClusterGroup) {
  view.innerHTML = '<p class="pad muted">Couldn\'t load the map library. Check your connection and reload.</p>';
} else {
  showWho();
  const slug = W.slugFromLocation(location);
  if (slug) tripPage(slug);
  else landing();
}
