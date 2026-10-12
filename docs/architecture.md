# Architecture

```
Hard disk (originals — never uploaded)
  D:\<trip>\                 photos, DJI clips (+ .LRF proxies), clip_locations.csv, overrides.json
  D:\<trip>\TripMap\         copy of tripmap/ (build.py, viewer.html, serve.py, publish.py, Open TripMap.bat)
  D:\<trip>\_tripmap\        built bundle: thumbs/ cards/ media/ trip.json  (+ local-only trip.js, index.html)
        │
        │  publish.py (rclone; key scoped to the bucket)
        ▼
R2 bucket "trip-media"  — private, no public domain
  trips.json                       list of trips (public)
  public/covers/<slug>(-card).jpg  landing-page covers (public)
  <slug>/trip.json|thumbs|cards|media   trip content (protected)
        │
        │  R2 binding
        ▼
Worker "wander-media" on media.job-joseph.com
  /trips.json, /public/*     public, CORS (credentials) for wander + Lovable preview
  /<slug>/...                behind Cloudflare Access app for that trip
  /auth/<slug>?return=URL    behind the same Access app; 302s back to *.job-joseph.com only
  /me                        email from the Access cookie (display only)
        ▲
        │  fetch(credentials:'include'); <img>/<video> send the cookie automatically (same site)
        │
wander.job-joseph.com  — Lovable-hosted app shell (repo: travelogue-map-memory), public
  /            landing: trips from trips.json, lock badge via HEAD trip.json
  /<slug>      trip page; "This trip is private" → Sign in → /auth/<slug> → back with ?signedin=1
```

## Components

### tripmap/build.py
One pass of `exiftool -json` over the trip folder, then per item: resolve time (DJI filename + camera offset, EXIF + offset, GPS time, QuickTime UTC, WhatsApp date + file time), resolve location (GPS → `clip_locations.csv` → `overrides.json` manual → nearest geotagged shot within `--match-window`). Builds 200px thumbs, 640px gallery cards, 1600px photo previews, 720p H.264 previews (from DJI `.LRF` proxies when present). Incremental: skips anything already built. Writes `trip.js` (local editor, includes paths) and `trip.json` (public contract, no paths). Saves its own args in `build_args.json` so the helper can re-run it.

### tripmap/serve.py + viewer.html
Local-only helper on `127.0.0.1:8765`. Serves the bundle with Range support and an API for the editor: save `overrides.json`, run a data-only build (Apply), a full build (Scan for new files), or `publish.py` (Publish). API requires an `X-TripMap` header and rejects foreign Origins (CSRF-safe). `viewer.html` doubles as the editor in `?edit` mode (filters, multi-select placement, drag, move-to-day, shift-time, undo).

### tripmap/publish.py
1. `rclone sync` thumbs/cards/media (cache 1 week), excluding local-only files.
2. `rclone copy` trip.json (no-cache).
3. Copy covers to `public/covers/`, merge this trip into `trips.json` (no-cache).
All calls use `--s3-no-check-bucket` (bucket-scoped key can't CreateBucket).

### worker/
Allow-list regex for servable keys; refuses `%`, `..`, `//`; never lists the bucket. Protected responses are `Cache-Control: private`. CORS with credentials only for known site origins; public paths also answer `*` without credentials.

### Access (Cloudflare Zero Trust)
Rule groups per audience (`Wander – All trips`, `Wander – <Trip> crew`); one self-hosted app per trip with two destinations (`/<slug>`, `/auth/<slug>`) and an Allow policy including the trip crew OR All trips. One-time PIN login.
