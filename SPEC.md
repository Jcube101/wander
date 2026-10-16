# Wander — Spec

What Wander is and what it must do. For *how* the pieces fit, see [docs/architecture.md](docs/architecture.md); for exact JSON shapes, see [docs/data-contract.md](docs/data-contract.md). Why things are this way: [docs/decisions.md](docs/decisions.md).

## Purpose

A private archive of trips. Each trip is a map, a timeline and a gallery of every photo and video. Originals stay on Job's external disk. Only small previews go online, and each trip is visible only to the people who were on it.

## Audiences

| Who | Sees | How |
|---|---|---|
| Anyone | Landing page: trip titles, dates, counts, covers | Public `trips.json` + `public/covers/` |
| A trip's crew | That trip only | Email in the trip's crew rule group |
| "All trips" group (Job and parents) | Every trip | Email in `Wander – All trips` |
| Job | Everything, plus the local editor | Runs `tripmap/` on his own machine |

## Components

| Component | Where it runs | Contract |
|---|---|---|
| **tripmap build** (`build.py`) | Job's PC, from this repo | Trip folder → `_tripmap/` bundle + `trip.json` |
| **tripmap editor** (`serve.py` + `viewer.html`) | `127.0.0.1:8765`, started by the trip folder's launcher | Reads/writes `overrides.json`; runs build/publish |
| **tripmap publish** (`publish.py`) | Job's PC | `_tripmap/` → R2 via rclone |
| **R2 bucket** `trip-media` | Cloudflare, private, no public domain | Layout below |
| **Worker** `wander-media` | `media.job-joseph.com` | Serves an allow-list of R2 keys |
| **Cloudflare Access** | Zero Trust, in front of the Worker | Decides who sees which trip |
| **Lovable site** | `wander.job-joseph.com` (repo `Jcube101/travelogue-map-memory`) | Consumes the [data contract](docs/data-contract.md) |

### R2 layout

| Key | Access |
|---|---|
| `trips.json` | Public |
| `public/covers/<slug>-card.jpg`, `public/covers/<slug>.jpg` | Public |
| `<slug>/trip.json` | Protected (trip's Access app) |
| `<slug>/thumbs/`, `cards/`, `media/` | Protected |

## Functional requirements

### Build (`tripmap/build.py`)

**Options**

| Option | Default | Effect |
|---|---|---|
| `--name` | folder name | Trip title; slug derived from it |
| `--slug` | from name | Web path segment |
| `--out` | `<trip>/_tripmap` | Bundle folder |
| `--tz` | `+07:00` | Zone for day boundaries and displayed times |
| `--assume-tz` | `--tz` | Zone for photos with no offset info |
| `--camera-offset` | `+07:45` | DJI clock vs UTC (filename times) |
| `--clip-locations` | `<trip>/clip_locations.csv` | Optional precomputed clip times/locations |
| `--csv-*-col`, `--csv-time-tz` | auto-detect, `+07:00` | CSV column mapping |
| `--match-window` | `120` min | Max gap for borrowing a nearby location |
| `--quick` | off | Thumbnails only |
| `--data-only` | off | Rewrite data, skip media (the editor's **Apply**) |
| `--overrides` | `<trip>/overrides.json` | Manual fixes file |
| `--photo-size` / `--video-height` / `--crf` | 1600 / 720 / 28 | Preview quality |
| `--photo-workers` / `--video-workers` | CPUs−1 / 2 | Parallelism |
| `--contact` | none | "Request original" link (local viewer only) |
| `--limit` | 0 | First N items (testing) |

**Time** — first clue that works:
1. DJI video → filename + `--camera-offset`
2. Photo → EXIF + `OffsetTimeOriginal` → GPS time → EXIF + assumed zone
3. Other video → QuickTime `CreateDate` (UTC)
4. Full date-time in filename + assumed zone
5. Date-only filename (WhatsApp) → file time if same day, else noon

Items with no usable time are skipped and listed. Date-only items more than a day outside the trip's firm dates are dropped.

**Location** — later steps win:
1. EXIF GPS → `loc: gps`
2. `clip_locations.csv` → `loc: csv` (+ its `conf`)
3. `overrides.json` → `manual` or `cleared`
4. Still unplaced → nearest `gps`/`manual` shot (archived ones included) within the window → `loc: matched`, `conf` high ≤10 min, medium ≤30 min, else low. Never for CSV rows, `cleared` items or WhatsApp media.

**Outputs**
- 200 px thumbs, 640 px cards, 1600 px photo previews, 720p H.264 video previews (from DJI `.LRF` proxies when present).
- Incremental: existing outputs are skipped, so builds can stop and resume.
- Photos that fail in parallel are retried one at a time; failures go to `build_errors.txt`.
- `trip.js` + `index.html`: local editor only (contain paths).
- `trip.json`: public contract, no paths or camera details. Archived shots are left out (see Archive).
- `build_args.json`: remembered options so the editor can re-run the build.
- Prints the bundle size.

### `overrides.json`

Keyed by path relative to the trip folder. Saved as `{version: 2, trip, saved, overrides: {...}}`; the previous file is kept as `overrides.bak.json`.

| Value | Meaning |
|---|---|
| `{"lat": .., "lon": ..}` | Manual location (`loc: manual`); also an anchor for matching |
| `{"noloc": true}` or `null` | Deliberately unplaced (`loc: cleared`); never auto-matched |
| `{"t": <unix s>}` | Manual time; combinable with either of the above |
| `{"archived": true}` | Hidden from the published trip; combinable with all of the above. Restore removes the field |

Manual values beat every other source. Overrides that match no file are reported (renamed or moved).

### Archive

Hide a shot from the published trip without deleting anything.

| Where | Behaviour |
|---|---|
| `trip.js` (editor) | Archived shots included, `archived: true`; dimmed in the strip, hidden on the map except in the Archived filter |
| `trip.json` (public) | Archived shots left out; counts exclude them; a day with only archived shots is left out |
| Days and dates | Day numbers and `start`/`end` come from all shots, so archiving never renumbers days |
| Location matching | Archived GPS/manual shots still anchor nearby shots (local maths only) |
| Cover | Middle eligible shot of all shots; if it's archived, the next eligible one (then the previous) |
| Local files | Originals and `_tripmap/` previews are never deleted; Scan keeps building them |
| R2 | Publish removes the archived shot's previews; Restore + Publish uploads them again |

No `trip.json` schema change: the [data contract](docs/data-contract.md) already allows day gaps.

### Editor (`serve.py` + `viewer.html?edit`)

- **Filters:** All (not archived) / Needs review (not `gps` or `manual`) / No location / Archived (n).
- **Archive / Restore** the selection (keys **A** / **Shift+A**). Archived shots can still be placed, moved and re-timed.
- **Select:** click, Shift-click range, double-click to view.
- **Place:** click map or pin to place the selection; drag a pin; Remove location.
- **Day/time:** Move to day (keeps clock time), Shift time (`-1:30`, `+2`).
- **Undo** (Ctrl+Z); every change autosaves to `overrides.json`.
- **Apply to map** (data-only build), **Scan for new files** (full build), **Publish**; one job at a time.
- **Backup / Import** fixes files.
- Server: localhost only, Range support for video. API needs the `X-TripMap: 1` header and refuses foreign Origins.

### Publish (`tripmap/publish.py`)

Order matters so the site never points at missing files:

0. **Plan** (read-only): referenced = every `thumb`/`card`/`media` (+ cover) in `trip.json`; remote = `rclone lsf` of `<slug>/thumbs|cards|media/`; delete = remote − referenced. Referenced files missing locally are listed as a warning and skipped.
1. `rclone copy --files-from` the referenced previews → `<slug>/`, `Cache-Control: public, max-age=604800`. Only new or changed files; never deletes.
2. `rclone copy` `trip.json`, `no-cache`.
3. `rclone delete --files-from` the delete list. Runs only if 1 and 2 succeeded. Prints the count (names with `--verbose`). A failure here still lets step 4 run, then exits with an error.
4. Copy covers to `public/covers/` (640 px card + 1600 px hero when the cover is a photo), merge this trip into `trips.json` (newest first, `no-cache`).

| Switch | Effect |
|---|---|
| Mass-delete guard | If the delete list is > 20% of the remote previews, stop before step 1 (nothing changed). A trip with no remote files has 0 deletes |
| `--allow-mass-delete` | Skip that guard (terminal only) |
| `--dry-run` | Access check + plan printout (upload count, full delete list, whether the guard would stop); changes nothing |

Before the plan, it requests `<slug>/trip.json` with no cookies and follows no redirects. Only 302/401/403 (Access) counts as protected; anything else, or a network error, stops the publish. `--allow-unprotected` skips this (terminal only; the editor never passes it).

Never uploaded: anything `trip.json` doesn't reference, including `trip.js`, `index.html`, `build_args.json`, `build_errors.txt`, `*.part.mp4` and archived shots' previews. Every rclone call has `--s3-no-check-bucket`.

### Worker (`worker/src/index.js`)

| Behaviour | Rule |
|---|---|
| Methods | GET, HEAD, OPTIONS (preflight 204); others 405 |
| Path safety | Any `%`, `..` or `//` → 404 |
| Allow-list | `trips.json`; `public/…`; `<slug>/trip.json`, `<slug>/thumbs|cards/<id>.jpg`, `<slug>/media/<id>.jpg|mp4`. Everything else 404; never lists |
| `/auth/<slug>?return=` | 302 to `return` if https `*.job-joseph.com`, else `https://wander.job-joseph.com/<slug>` |
| `/me` | `{email}` from the `CF_Authorization` cookie (null if missing/expired); display only |
| Range | 206 with `content-range`, incl. suffix ranges |
| Conditional | `If-None-Match` etc. → 304 |
| Caching | Public: data `no-cache`, images 1 h. Protected: `private`, data `no-cache`, media 1 week |
| CORS | Credentials only for known site origins; public paths also answer `*` without credentials |
| Headers | `etag`, `accept-ranges`, `x-content-type-options: nosniff` |

### Access

One self-hosted app per trip with destinations `media.job-joseph.com/<slug>` and `media.job-joseph.com/auth/<slug>`. Allow policy = trip crew OR All trips. One-time PIN login.

## Non-functional requirements

| Requirement | How it's kept |
|---|---|
| Originals never leave the disk | Only previews are built and uploaded |
| Raw paths never uploaded | `publish.py` excludes `trip.js`/`index.html`; Worker refuses them |
| No database, ever | Identity = Access cookie; data = static JSON in R2 |
| Free tier only | R2 ≤ 10 GB (~2.5 GB/trip); Cloudflare free plans |
| One copy of the code | Runs from this repo; trip folders hold only a launcher |
| Client rules | `credentials: 'include'`; no `crossorigin` on `<img>`/`<video>`; nothing in browser storage; times shown in the trip's zone |
| Privacy in git | No media, overrides, CSVs, trip JSON or coordinates committed |

## Non-goals

- Public sharing of originals
- Serving originals online, even to the crew. Originals never leave the disk; anyone who wants one asks Job.
- In-browser editing on the live site
- A user database or our own auth
- Subdomains per trip

## Onboarding a trip

Follow [docs/runbook.md → New trip](docs/runbook.md#new-trip).
