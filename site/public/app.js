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

// A request to the media host that can tell "signed out" from "failed":
// {outcome: "ok" | "signed-out" | "error", res}. When the fetch fails outright, it's either
// offline or Access redirecting a signed-out visitor without CORS headers (which the page
// can't read), so /me (public: the email in the Access cookie) tells the two apart.
// cache: "no-store" by default: an <img>/<video> may have cached the same file without CORS
// headers, and a CORS fetch handed that copy fails.
async function mediaFetch(url, init = {}) {
  let res;
  try {
    res = await fetch(url, { cache: "no-store", ...init, credentials: "include", redirect: "manual" });
  } catch (e) {
    if (e.name === "AbortError") throw e;
    const signedIn = await getJson(W.joinUrl(MEDIA, "me")).then((me) => Boolean(me.email), () => true);
    return { outcome: signedIn ? "error" : "signed-out" };
  }
  return { outcome: W.accessOutcome(res), res };
}

// Saves a Blob as a file (a same-origin blob: URL, so the download attribute works).
function saveBlob(blob, name) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 60_000);
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

  // Days and the gallery. "Favourites" is a toggle on top of the day: all of them, or one day's.
  let current = items, day = "all", onlyFavs = false;
  const chips = $("#days");
  const days = [{ key: "all", label: "All days", sub: `${items.length} shots` },
    ...(trip.days || []).map((d) => ({ key: d.key, label: `Day ${d.n}`, sub: `${W.fmtDay(d.key)} · ${d.count}` }))];
  const chip = (d) =>
    `<button class="chip" data-day="${esc(d.key)}" aria-pressed="false">${esc(d.label)}<small>${esc(d.sub)}</small></button>`;
  chips.innerHTML = chip(days[0]) +
    `<button class="chip fav-chip" data-favs aria-pressed="false" hidden>${HEART}<span id="fav-label"></span><small>Only you see these</small></button>` +
    days.slice(1).map(chip).join("");
  const favChip = chips.querySelector("[data-favs]");
  chips.addEventListener("click", (e) => {
    const b = e.target.closest("[data-day], [data-favs]");
    if (!b) return;
    if (b.hasAttribute("data-favs")) onlyFavs = !onlyFavs;
    else day = b.dataset.day;
    setView();
  });
  const grid = $("#grid");
  grid.addEventListener("click", (e) => {
    if (e.target.closest("#zip-btn")) return zipStart();
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

  function setView() {
    const inDay = W.itemsFor(items, day);
    current = onlyFavs ? W.favoriteItems(inDay, favs || new Set()) : inDay;
    for (const b of chips.querySelectorAll("[data-day]")) b.setAttribute("aria-pressed", String(b.dataset.day === day));
    favChip.setAttribute("aria-pressed", String(onlyFavs));
    const empty = !onlyFavs ? "Nothing on this day."
      : day === "all" ? "No favourites yet. Tap the ♡ on a photo or video to add it. Only you see yours."
      : "No favourites on this day.";
    grid.innerHTML = current.length
      ? (onlyFavs ? '<div class="fav-tools zip-only"><span id="zip-sum"></span><button class="btn ghost" id="zip-btn">Download favourites (ZIP)</button></div>' : "")
        + current.map(tile).join("")
      : `<p class="muted">${esc(empty)}</p>`;
    zipSummary();
    grid.scrollTop = 0;
    cluster.clearLayers();
    const placed = current.filter((x) => markers.has(x.id));
    cluster.addLayers(placed.map((x) => markers.get(x.id)));
    if (placed.length) map.fitBounds(L.latLngBounds(placed.map((x) => [x.lat, x.lon])).pad(0.15), { maxZoom: 15 });
    else map.setView([20, 0], 2);
  }
  setView();

  // Favourites: hearts on tiles and in the viewer, and the "Favourites (n)" filter.
  // In that filter, un-hearting keeps the tile until the filter is picked again,
  // so a mis-tap is one tap to undo.
  const lbFav = $("#lb-fav");
  lbFav.innerHTML = HEART;
  lbFav.onclick = () => toggleFav(lbFav.dataset.fav);
  function renderFavs() {
    favChip.hidden = !favs;
    if (!favs) return;
    $("#fav-label").textContent = W.favoritesLabel(favs.size);
    for (const h of document.querySelectorAll("[data-fav]")) {
      h.hidden = false;
      h.setAttribute("aria-pressed", String(favs.has(h.dataset.fav)));
    }
    zipSummary();
  }
  // A favourites request: {outcome: "ok" | "signed-out" | "error", data}.
  async function favRequest(init = {}) {
    const { outcome, res } = await mediaFetch(favUrl, init);
    return { outcome, data: outcome === "ok" ? await res.json() : null };
  }
  const signInAgain = (what) =>
    notice(`Your sign-in has run out, so ${what}. <a href="${esc(W.signInUrl(MEDIA, slug, location.href))}">Sign in again</a>`);
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
        signInAgain("favourites can't be saved");
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
    const dl = W.downloadUrl(MEDIA, slug, x);
    lbDl.hidden = !dl;
    lbDl.href = dl || "#";
    shared = null;
    dlState("");
    for (const t of grid.querySelectorAll(".tile.cur")) t.classList.remove("cur");
    grid.querySelector(`[data-id="${CSS.escape(x.id)}"]`)?.classList.add("cur");
  }
  function closeLb() {
    lb.hidden = true;
    stage.innerHTML = ""; // stops a playing video
    document.body.style.overflow = "";
    shared = null;
  }

  // Download one shot. Desktop: the link itself (?download=1 → the Worker says "attachment").
  // Phones: the share sheet, so it can go straight into Photos. The file has to be fetched
  // first; if the browser then says the tap is too old for a share (iOS does, for a big
  // video), the button turns into "Save" and the next tap shares it at once.
  const lbDl = $("#lb-dl");
  let shared = null; // {id, file} fetched for the share sheet
  const prefersShare = () => matchMedia("(pointer: coarse)").matches && typeof navigator.canShare === "function";
  function dlState(state) {
    lbDl.dataset.state = state;
    lbDl.querySelector("span").textContent = state === "busy" ? "Preparing…" : state === "ready" ? "Save" : "Download";
  }
  lbDl.onclick = (e) => {
    if (!prefersShare()) return; // the link downloads it
    e.preventDefault();
    if (lbDl.dataset.state !== "busy") shareShot(list[idx]);
  };
  async function shareShot(x) {
    if (shared?.id === x.id) return share(shared.file);
    dlState("busy");
    let file;
    try {
      const { outcome, res } = await mediaFetch(url(W.downloadPath(x)));
      if (outcome === "signed-out") {
        signInAgain("the file can't be downloaded");
        return dlState("");
      }
      if (outcome !== "ok") throw new Error(`HTTP ${res?.status}`);
      const blob = await res.blob();
      const name = W.downloadName(x, tz);
      file = new File([blob], name, { type: blob.type || (name.endsWith(".mp4") ? "video/mp4" : "image/jpeg") });
    } catch {
      notice("Couldn't download that file. Check your connection and try again.", 6000);
      return dlState("");
    }
    if (lb.hidden || list[idx] !== x) return; // they've moved on
    if (!navigator.canShare({ files: [file] })) {
      saveBlob(file, file.name); // no share sheet for this file: an ordinary download
      return dlState("");
    }
    shared = { id: x.id, file };
    return share(file);
  }
  async function share(file) {
    try {
      await navigator.share({ files: [file] });
      dlState("");
    } catch (e) {
      if (e.name === "NotAllowedError") return dlState("ready"); // needs a fresh tap
      dlState(""); // AbortError: they closed the sheet; a tap opens it again
      if (e.name !== "AbortError") notice("Couldn't open the share sheet. Try again.", 6000);
    }
  }

  // "Download favourites (ZIP)": desktop only (CSS hides it on touch and narrow screens). The
  // favourites in view (all, or one day's), one file at a time, each streamed in and checked
  // (CRC-32) as it arrives, then stored uncompressed in a ZIP built here. A file that fails is
  // skipped and listed at the end. At most W.ZIP_MAX bytes: more → pick a day.
  const zipDlg = $("#zip"), zipBody = $("#zip-body"), zipActions = $("#zip-actions");
  let zipRun = null, zipPicked = [], zipEst = null; // zipRun = {ctrl} while downloading
  function zipItems() {
    return current.filter((x) => favs?.has(x.id) && W.downloadPath(x));
  }
  function scopeText() {
    const d = (trip.days || []).find((d) => d.key === day);
    return d ? ` from Day ${d.n}` : "";
  }
  function zipSummary() {
    const sum = $("#zip-sum");
    if (!sum) return;
    const est = W.zipEstimate(zipItems());
    sum.textContent = `${est.files} favourite${est.files === 1 ? "" : "s"}${est.bytes ? ` · about ${W.fmtBytes(est.bytes)}` : ""}`;
  }
  function zipShow(html, actions) {
    zipBody.innerHTML = html;
    zipActions.innerHTML = actions.map(([id, label, primary]) =>
      `<button class="btn${primary ? "" : " ghost"}" data-zip="${id}">${esc(label)}</button>`).join("");
    if (!zipDlg.open) zipDlg.showModal();
    zipActions.querySelector(".btn:not(.ghost)")?.focus();
  }
  function zipStart() {
    if (!W.isDesktop(matchMedia) || zipRun) return;
    const picked = zipItems();
    const est = W.zipEstimate(picked);
    if (!est.files) return;
    const size = est.bytes ? `about ${W.fmtBytes(est.bytes)}` : "size unknown";
    const unknown = est.unknown && est.bytes ? ` (not counting ${est.unknown} whose size isn't known)` : "";
    if (est.bytes > W.ZIP_MAX) {
      return zipShow(`<p>Your ${est.files} favourites${esc(scopeText())} come to ${esc(W.fmtBytes(est.bytes))}, more than one ZIP can hold (${esc(W.fmtBytes(W.ZIP_MAX))}).</p>
        <p>Pick a day above, then download that day's favourites. Do it again for the other days.</p>`, [["close", "OK", true]]);
    }
    zipShow(`<p>Download ${est.files} favourite${est.files === 1 ? "" : "s"}${esc(scopeText())} as one ZIP file: ${esc(size)}${esc(unknown)}.</p>
      <p class="muted">The photos and videos as shown here (not the camera originals). Keep this page open until it's done.</p>`,
      [["cancel", "Cancel"], ["go", "Download", true]]);
    zipPicked = picked;
    zipEst = est;
  }
  zipActions.addEventListener("click", (e) => {
    const b = e.target.closest("[data-zip]");
    if (!b) return;
    if (b.dataset.zip === "go") zipBuild(zipPicked, zipEst);
    else if (b.dataset.zip === "stop") zipRun?.ctrl.abort();
    else zipDlg.close();
  });
  zipDlg.addEventListener("cancel", (e) => { // Escape
    if (zipRun) {
      e.preventDefault();
      zipRun.ctrl.abort();
    }
  });
  zipDlg.addEventListener("close", () => {
    zipBody.innerHTML = "";
    if (zipDlg.dataset.href) URL.revokeObjectURL(zipDlg.dataset.href);
    delete zipDlg.dataset.href;
  });
  const leaveWarning = (e) => e.preventDefault();

  async function zipBuild(picked, est) {
    const ctrl = new AbortController();
    zipRun = { ctrl };
    addEventListener("beforeunload", leaveWarning);
    const zip = W.zipWriter(), used = new Set(), failed = [];
    let got = 0, n = 0, stop = null;
    zipShow(`<p id="zip-status"></p><progress id="zip-bar" max="1" value="0"></progress>`, [["stop", "Cancel"]]);
    const status = $("#zip-status"), bar = $("#zip-bar");
    const progress = () => {
      status.textContent = `Downloading ${n} of ${picked.length} · ${W.fmtBytes(got)}${est.bytes ? ` of about ${W.fmtBytes(est.bytes)}` : ""}`;
      if (est.bytes && !est.unknown) bar.value = Math.min(1, got / est.bytes);
      else bar.value = (n - 1) / picked.length;
    };
    try {
      for (const x of picked) {
        n++;
        progress();
        const name = W.uniqueName(W.downloadName(x, tz), used);
        try {
          const { outcome, res } = await mediaFetch(url(W.downloadPath(x)), { signal: ctrl.signal });
          if (outcome === "signed-out") { stop = "signed-out"; break; }
          if (outcome !== "ok") throw new Error(res ? `HTTP ${res.status}` : "no connection");
          const reader = res.body.getReader(), chunks = [];
          let crc = 0, size = 0;
          for (;;) {
            const { done, value } = await reader.read();
            if (done) break;
            crc = W.crc32(value, crc);
            size += value.byteLength;
            got += value.byteLength;
            chunks.push(value);
            if (zip.size + size > W.ZIP_MAX) { stop = "too-big"; await reader.cancel(); break; }
            progress();
          }
          if (stop) break;
          // As a Blob, the browser can keep it off the page's memory (on disk if need be).
          zip.add(name, [new Blob(chunks)], { crc, size, t: x.t, tzOffsetMin: tz });
        } catch (e) {
          if (ctrl.signal.aborted) throw e;
          failed.push(`${name} (${e.message || "failed"})`);
        }
      }
    } catch {
      zipRun = null;
      removeEventListener("beforeunload", leaveWarning);
      return zipShow("<p>Cancelled. Nothing was saved.</p>", [["close", "Close", true]]);
    }
    zipRun = null;
    removeEventListener("beforeunload", leaveWarning);
    if (stop === "signed-out") {
      zipDlg.close();
      return signInAgain("the ZIP couldn't be finished");
    }
    if (stop === "too-big") {
      return zipShow(`<p>These favourites came to more than ${esc(W.fmtBytes(W.ZIP_MAX))}, more than one ZIP can hold. Nothing was saved.</p>
        <p>Pick a day above, then download that day's favourites.</p>`, [["close", "OK", true]]);
    }
    const list = failed.length
      ? `<p>Couldn't download ${failed.length} file${failed.length === 1 ? "" : "s"}; ${zip.count ? "the ZIP has the rest" : "nothing to save"}:</p><ul class="zip-failed">${failed.map((f) => `<li>${esc(f)}</li>`).join("")}</ul>`
      : "";
    if (!zip.count) return zipShow(list || "<p>Nothing to save.</p>", [["close", "Close", true]]);
    const name = `${slug}-favourites.zip`;
    const href = URL.createObjectURL(new Blob(zip.finish(), { type: "application/zip" }));
    zipDlg.dataset.href = href;
    zipShow(`<p>Done: ${zip.count} file${zip.count === 1 ? "" : "s"}, ${esc(W.fmtBytes(zip.size))}, saved as <b>${esc(name)}</b>.</p>${list}
      <p><a class="btn" id="zip-save" href="${esc(href)}" download="${esc(name)}">Save ZIP</a></p>`, [["close", "Close", true]]);
    $("#zip-save").click(); // the browser's own download; the button is there if it was blocked
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
