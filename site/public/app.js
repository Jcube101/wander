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
const HEART = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 20.5s-7.6-4.6-9.4-9.4C1.4 7.9 3.6 4.5 7 4.5c2 0 3.6 1.1 5 3 1.4-1.9 3-3 5-3 3.4 0 5.6 3.4 4.4 6.6-1.8 4.8-9.4 9.4-9.4 9.4z"/></svg>';

let noticeTimer;
function notice(html, hideAfterMs) {
  const n = $("#notice");
  clearTimeout(noticeTimer);
  n.innerHTML = html;
  n.hidden = false;
  if (hideAfterMs) noticeTimer = setTimeout(() => { n.hidden = true; }, hideAfterMs);
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
  // Favourites: this visitor's own, kept by the Worker. null = not offered (the media
  // host has none, or they aren't set up for this trip): no hearts, no filter.
  let favs = null, favsSending = 0;
  const favUrl = W.favoritesUrl(MEDIA, slug);
  const sendFav = W.serial();

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
  const chip = (d) =>
    `<button class="chip" data-day="${esc(d.key)}" aria-pressed="false">${esc(d.label)}<small>${esc(d.sub)}</small></button>`;
  chips.innerHTML = chip(days[0]) +
    `<button class="chip fav-chip" data-day="favs" aria-pressed="false" hidden>${HEART}<span id="fav-label"></span><small>Only you see these</small></button>` +
    days.slice(1).map(chip).join("");
  chips.addEventListener("click", (e) => {
    const b = e.target.closest("[data-day]");
    if (b) setDay(b.dataset.day);
  });
  const grid = $("#grid");
  grid.addEventListener("click", (e) => {
    const h = e.target.closest("[data-fav]");
    if (h) return toggleFav(h.dataset.fav);
    const b = e.target.closest("[data-id]");
    if (b) openLb(b.dataset.id);
  });

  // A tile is the picture (opens the viewer) plus a heart; buttons can't nest.
  function tile(x) {
    const src = url(x.card || x.thumb);
    return `<div class="tile" data-id="${esc(x.id)}">
      <button class="open" aria-label="${esc(W.itemCaption(x, tz))}">
        ${src ? `<img src="${esc(src)}" alt="" loading="lazy">` : ""}
        <span class="t">${esc(W.fmtTime(x.t, tz))}</span>${x.type === "video" ? `<span class="v">▶ ${esc(W.fmtDuration(x.dur))}</span>` : ""}
      </button>
      <button class="heart" data-fav="${esc(x.id)}" aria-label="Favourite" aria-pressed="${favs?.has(x.id) ? "true" : "false"}"${favs ? "" : " hidden"}>${HEART}</button>
    </div>`;
  }

  function setDay(day) {
    current = day === "favs" ? W.favoriteItems(items, favs || new Set()) : W.itemsFor(items, day);
    for (const b of chips.querySelectorAll("[data-day]")) b.setAttribute("aria-pressed", String(b.dataset.day === day));
    grid.innerHTML = current.map(tile).join("") || (day === "favs"
      ? '<p class="muted">No favourites yet. Tap the ♡ on a photo or video to add it. Only you see yours.</p>'
      : '<p class="muted">Nothing on this day.</p>');
    grid.scrollTop = 0;
    cluster.clearLayers();
    const placed = current.filter((x) => markers.has(x.id));
    cluster.addLayers(placed.map((x) => markers.get(x.id)));
    if (placed.length) map.fitBounds(L.latLngBounds(placed.map((x) => [x.lat, x.lon])).pad(0.15), { maxZoom: 15 });
    else map.setView([20, 0], 2);
  }
  setDay("all");

  // Favourites: hearts on tiles and in the viewer, and the "Favourites (n)" filter.
  // In that filter, un-hearting keeps the tile until the filter is picked again,
  // so a mis-tap is one tap to undo.
  const lbFav = $("#lb-fav");
  lbFav.innerHTML = HEART;
  lbFav.onclick = () => toggleFav(lbFav.dataset.fav);
  function renderFavs() {
    chips.querySelector('[data-day="favs"]').hidden = !favs;
    if (!favs) return;
    $("#fav-label").textContent = W.favoritesLabel(favs.size);
    for (const h of document.querySelectorAll("[data-fav]")) {
      h.hidden = false;
      h.setAttribute("aria-pressed", String(favs.has(h.dataset.fav)));
    }
  }
  // A favourites request: {outcome: "ok" | "signed-out" | "error", data}. A fetch that fails
  // outright is either offline or Access sending a signed-out visitor to its login (a
  // cross-site redirect without CORS headers, which the page can't read), so /me (public:
  // the email in the Access cookie) tells the two apart.
  async function favRequest(init = {}) {
    let r;
    try {
      r = await fetch(favUrl, { ...init, credentials: "include", redirect: "manual" });
    } catch {
      const signedIn = await getJson(W.joinUrl(MEDIA, "me")).then((me) => Boolean(me.email), () => true);
      return { outcome: signedIn ? "error" : "signed-out" };
    }
    const outcome = W.favoritesOutcome(r);
    return { outcome, data: outcome === "ok" ? await r.json() : null };
  }
  function toggleFav(id) {
    if (!favs || !id) return;
    const fav = !favs.has(id);
    favs = W.withFavorite(favs, id, fav); // show it at once; undone below if the save fails
    favsSending++;
    renderFavs();
    sendFav(async () => {
      const { outcome, data } = await favRequest({
        method: "POST", headers: { "content-type": "text/plain;charset=UTF-8" }, body: W.favoriteBody(id, fav),
      });
      if (outcome !== "ok") throw Object.assign(new Error(outcome), { outcome });
      return data;
    }).then((data) => {
      if (--favsSending === 0) favs = W.favoriteIds(data, new Set(byId.keys())); // the Worker's list wins
    }, (e) => {
      favsSending--;
      favs = W.withFavorite(favs, id, !fav);
      if (e.outcome === "signed-out") {
        notice(`Your sign-in has run out, so favourites can't be saved. <a href="${esc(W.signInUrl(MEDIA, slug, location.href))}">Sign in again</a>`);
      } else {
        notice("Couldn't save that favourite. Check your connection and try again.", 6000);
      }
    }).finally(renderFavs);
  }
  favRequest().then(({ outcome, data }) => {
    if (outcome === "error") return; // none on this media host, not set up for this trip, or offline
    // Signed out (the session ran out since the trip loaded): empty hearts; a tap says to sign in.
    favs = outcome === "ok" ? W.favoriteIds(data, new Set(byId.keys())) : new Set();
    renderFavs();
  }, () => {});

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
    lbFav.dataset.fav = x.id;
    lbFav.hidden = !favs;
    lbFav.setAttribute("aria-pressed", String(Boolean(favs?.has(x.id))));
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
