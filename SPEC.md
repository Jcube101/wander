# Wander — Spec

What Wander is and what it must do: how the pieces fit (Components), what each must do, and the exact JSON shapes ([Data contract — build your own site](#data-contract--build-your-own-site)). Why things are this way: [LEARNINGS.md → Decisions](LEARNINGS.md#decisions). Examples use `wander.example.com` (site), `media.example.com` (media host) and a made-up trip, `lisbon-2025`; your own values live in your config ([SETUP.md](SETUP.md)).

## Purpose

A private archive of trips. Each trip is a map, a timeline and a gallery of every photo and video. Originals stay on the owner's disk. Only small previews go online, and each trip is visible only to the people who were on it.

## Audiences

| Who | Sees | How |
|---|---|---|
| Anyone | Landing page: trip titles, dates, counts, covers | Public `trips.json` + `public/covers/` |
| A trip's crew | That trip only | Email in the trip's crew rule group |
| "All trips" group (e.g. the owner and family) | Every trip | Email in `<prefix> – All trips` |
| The owner | Everything, plus the local editor | Runs `tripmap/` on their own machine |

## Components

### How the pieces fit

```
Hard disk (originals — never uploaded)
  <trip>/                    photos, DJI clips (+ .LRF proxies), clip_locations.csv, overrides.json
  <trip>/Open Wander Editor.bat (or open-wander-editor.sh)   launcher → runs this repo's tripmap/serve.py on this folder
  <trip>/_tripmap/           built bundle: thumbs/ cards/ media/ trip.json  (+ local-only trip.js, index.html, build_args.json)
        │
        │  publish.py (rclone; key scoped to the bucket)
        ▼
R2 bucket (e.g. "trip-media")  — private, no public domain
  trips.json                       list of trips (public)
  public/covers/<slug>(-card).jpg  landing-page covers (public)
  <slug>/trip.json|thumbs|cards|media   trip content (protected)
        │
        │  R2 binding
        ▼
Worker (e.g. "wander-media") on media.example.com
  /trips.json, /public/*     public; CORS with credentials for SITE_ORIGINS, "*" without for anyone else
  /<slug>/...                behind Cloudflare Access app for that trip
  /auth/<slug>?return=URL    behind the same Access app; 302s back to a SITE_ORIGINS origin only
  /me                        email from the Access cookie (display only)
        ▲
        │  fetch(credentials:'include'); <img>/<video> send the cookie automatically (same site)
        │
wander.example.com  — any static site (the live example is built with Lovable), public
  /            landing: trips from trips.json, lock badge via HEAD trip.json
  /<slug>      trip page; "This trip is private" → Sign in → /auth/<slug> → back with ?signedin=1
```

| Component | Where it runs | Contract |
|---|---|---|
| **config** (`config.py`) | The owner's machine | `~/.wander/config.json` (or `$WANDER_CONFIG`, or `wander.config.json` in the repo): media host, rclone remote + bucket, site URL, Access prefix and sessions. Only publish and Access need it |
| **tripmap build** (`build.py`) | The owner's machine, from this repo | Trip folder → `_tripmap/` bundle + `trip.json` |
| **tripmap editor** (`serve.py` + `viewer.html`) | `127.0.0.1:8765`, started by the trip folder's launcher | Reads/writes `overrides.json`; runs build/publish |
| **launcher** (`launcher.py`) | The owner's machine | Writes the trip folder's `.bat`/`.sh` launcher with this repo's path |
| **tripmap publish** (`publish.py`) | The owner's machine | `_tripmap/` → R2 via rclone |
| **R2 bucket** | Cloudflare, private, no public domain | Layout in the diagram above |
| **Worker** (`worker/`) | The media host | Serves an allow-list of R2 keys; settings in `wrangler.toml` (`SITE_ORIGINS`) |
| **Cloudflare Access** | Zero Trust, in front of the Worker | Decides who sees which trip |
| **Site** | The site host, same registrable domain as the media host | Consumes the [data contract](#data-contract--build-your-own-site) |
| **Reference viewer** (`site/public/`) | Any static host, e.g. Cloudflare Pages | One such site: trip list with lock badges; per trip a map, day filter, gallery, viewer and sign-in. Media host set in `config.js`, overridden by a gitignored `config.local.js`; no build step, no browser storage |

## Functional requirements

### Build (`tripmap/build.py`)

**Options**

| Option | Default | Effect |
|---|---|---|
| `--name` | folder name | Trip title; slug derived from it |
| `--slug` | from name | Web path segment |
| `--out` | `<trip>/_tripmap` | Bundle folder |
| `--tz` | **required** | The trip's UTC offset: day boundaries and displayed times. `--tz -05:00` works (no `=` needed) |
| `--assume-tz` | `--tz` | Zone for photos with no offset info |
| `--camera-offset` | `+00:00` | DJI clock vs UTC (filename times). Always saved in `build_args.json`, so a re-run never shifts clips |
| `--clip-locations` | `<trip>/clip_locations.csv` | Optional precomputed clip times/locations |
| `--csv-*-col`, `--csv-time-tz` | auto-detect, `--tz` | CSV column mapping |
| `--match-window` | `120` min | Max gap for borrowing a nearby location |
| `--quick` | off | Thumbnails only |
| `--data-only` | off | Rewrite data, skip media (the editor's **Apply**) |
| `--overrides` | `<trip>/overrides.json` | Manual fixes file |
| `--photo-size` / `--video-height` / `--crf` | 1600 / 720 / 28 | Preview quality |
| `--photo-workers` / `--video-workers` | CPUs−1 / 2 | Parallelism |
| `--contact` | none | "Request original" link (local viewer only) |
| `--limit` | 0 | First N items (testing) |

One `exiftool -json` pass over the trip folder, then per item:

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

Keyed by path relative to the trip folder. Saved as `{version: 2, trip, saved, settings: {...}, overrides: {...}}` (`trip` is the title); the previous file is kept as `overrides.bak.json`.

`settings` holds trip-level choices; today only `cover` (see Cover). A save that doesn't include `settings`, or doesn't name a key, keeps what's on disk; clearing is explicit (`"cover": null`). Import of a file without settings never clears them.

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
| Cover | A chosen cover that's archived falls back to automatic until restored (see Cover) |
| Local files | Originals and `_tripmap/` previews are never deleted; Scan keeps building them |
| R2 | Publish removes the archived shot's previews; Restore + Publish uploads them again |

No `trip.json` schema change: the [data contract](#data-contract--build-your-own-site) already allows day gaps.

### Cover

One cover per trip. It drives the landing card (640 px) and the hero (1600 px).

| Rule | Behaviour |
|---|---|
| Chosen | `settings.cover` = relative path of a photo (survives rebuilds like other fixes). Used if it exists, is a photo and isn't archived |
| Fallback | Otherwise the automatic pick, with one `WARNING` line saying why: missing, a video, or archived |
| Automatic pick | Unchanged: middle placed photo (else middle shot with a card); if that's archived, the next eligible one, then the previous |
| Archive / Restore | Archiving never clears the setting, so Restore + Apply brings the chosen cover back |
| `trip.json` | No schema change: `cover` is still `cards/<id>.jpg` |
| `trips.json` | `cover`/`coverImage` end in `?v=<10 hex of the image's SHA-256>`, so a new cover shows at once despite the 1 h cache. The Worker ignores query strings |

### Editor (`serve.py` + `viewer.html?edit`)

- **Layout:** one toolbar row: filters left; save status, Apply to map, Publish, ⋯ menu (Scan for new files, Import, Backup, Automatic cover, Select all in view, Follow selection), ? right: a popover with "How do I…" (one line per everyday workflow: add files, place a shot, fix day/time, hide/restore, cover, make changes live, missing after a scan) above the hints and shortcuts. A selection bar appears over the map's bottom edge only while ≥1 shot is selected (the strip never moves) and shows only the actions that apply; the rest are hidden (and disabled, so shortcuts can't fire them). It wraps on narrow screens; the page never scrolls sideways.
- **Filters:** All (not archived) / Needs review (not `gps` or `manual`) / No location (n) / Archived (n).
- **Archive / Restore** the selection (keys **A** / **Shift+A**), shown when some selected shot is published / archived. Archived shots can still be placed, moved and re-timed.
- **Set as cover** (shown only for exactly one non-archived photo that isn't already the cover) / **Automatic cover** (⋯, shown when a cover is chosen). ★ on the cover's strip tile; the summary says `Cover: <file>` or `Cover: automatic`, plus a note if the chosen cover is archived, missing or not a photo.
- **Select:** click, Shift-click range, double-click to view, Esc clears.
- **Where it happened** (uses the editor's current, unapplied times and places):
  - Placed shot(s) selected: zoom to the pin (several: fit them) and highlight.
  - Otherwise: neighbours = nearest placed, non-archived, unselected shot before the earliest selected shot and after the latest. Shown on the map: the same-day ones if any, else both. Fit to two, centre on one; highlight with gap labels (`−12 min`, `+40 min`, `+1 h 5 min`, `−2 d 3 h`) and a faint dashed line. Status: `Between <file> (−12 min) and <file> (+40 min)`; other-day neighbours get `, Day N`.
  - Highlights ignore the mouse, so clicking the map or a pin to place, and dragging pins, behave as before.
  - **Follow selection** (⋯, default on, per browser in `localStorage`): off = selecting never moves the map. The map never moves while the user is dragging it (until its glide ends), holding a pointer on it, or within 0.6 s of a wheel zoom.
  - Lookup is `TripPure.neighbours` in viewer.html's `<script id="tripmap-pure">` block: one linear pass, tested by `tripmap/tests/test_viewer.mjs`.
- **Place:** **Place at previous** / **Place at next** (keys **[** / **]**, shown when that neighbour exists) copy its location onto the selection as manual placements (undoable); click map or pin to place the selection; drag a pin; Remove location (shown when a selected shot is placed).
- **Day/time:** Move to day (keeps clock time), Shift time (`-1:30`, `+2`).
- **Undo** (Ctrl+Z, also undoes cover changes; button in the selection bar, or in the toolbar when nothing is selected); every change autosaves to `overrides.json`.
- **Apply to map** (data-only build), **Scan for new files** (full build), **Publish**; one job at a time.
- **Backup / Import** fixes files.
- Shortcuts are ignored while typing in a field or while the viewer is open; **?** toggles help; Esc closes the menu/help first, then clears the selection.
- Server: localhost only, Range support for video. API needs the `X-TripMap: 1` header and refuses foreign Origins (CSRF-safe).

### Publish (`tripmap/publish.py`)

Order matters so the site never points at missing files:

0. **Plan** (read-only): referenced = every `thumb`/`card`/`media` (+ cover) in `trip.json`; remote = `rclone lsf` of `<slug>/thumbs|cards|media/`; delete = remote − referenced. Referenced files missing locally are listed as a warning and skipped.
1. `rclone copy --files-from` the referenced previews → `<slug>/`, `Cache-Control: public, max-age=604800`. Only new or changed files; never deletes.
2. `rclone copy` `trip.json`, `no-cache`.
3. `rclone delete --files-from` the delete list. Runs only if 1 and 2 succeeded. Prints the count (names with `--verbose`). A failure here still lets step 4 run, then exits with an error.
4. Copy covers to `public/covers/` (640 px card + 1600 px hero when the cover is a photo), merge this trip into `trips.json` (newest first, `no-cache`; cover URLs carry `?v=`).

| Switch | Effect |
|---|---|
| Mass-delete guard | If the delete list is > 20% of the remote previews, stop before step 1 (nothing changed). A trip with no remote files has 0 deletes |
| `--allow-mass-delete` | Skip that guard (terminal only) |
| `--dry-run` | Access check + plan printout (storage line, upload count, full delete list, whether the guard would stop); changes nothing |

**Storage check** (in the plan, warn only, never blocks): `rclone size` of the whole bucket + local bytes of referenced files not yet on R2 − remote bytes of the delete list. Always prints `R2 storage: X.XX GB now → Y.YY GB after publish (free tier 10 GB)`, and again after `Published.` so the editor's status line shows it.

| Projected (decimal GB) | Output |
|---|---|
| ≤ 8 | The line only |
| > 8 | WARNING: suggest smaller previews (`--crf 30`, `--video-height 540`) or archiving |
| > 10 | WARNING: over the free tier, it starts costing money |
| `rclone size` fails | WARNING: couldn't check; the publish carries on |

Thresholds are constants at the top of `publish.py`.

Before the plan, it requests `<slug>/trip.json` with no cookies and follows no redirects. Only 302/401/403 (Access) counts as protected; anything else, or a network error, stops the publish. `--allow-unprotected` skips this (terminal only; the editor never passes it).

Never uploaded: anything `trip.json` doesn't reference, including `trip.js`, `index.html`, `build_args.json`, `build_errors.txt`, `*.part.mp4` and archived shots' previews. Every rclone call has `--s3-no-check-bucket`.

### Worker (`worker/src/index.js`)

| Behaviour | Rule |
|---|---|
| Methods | GET, HEAD, OPTIONS (preflight 204); others 405 |
| Path safety | Any `%`, `..` or `//` → 404 |
| Allow-list | `trips.json`; `public/…`; `<slug>/trip.json`, `<slug>/thumbs|cards/<id>.jpg`, `<slug>/media/<id>.jpg|mp4`. Everything else 404; never lists |
| `/auth/<slug>?return=`, `/me` | See [Worker endpoints](#worker-endpoints). `/me` reads the `CF_Authorization` cookie (null if missing/expired) |
| Range | 206 with `content-range`, incl. suffix ranges |
| Conditional | `If-None-Match` etc. → 304 |
| Caching | Public: data `no-cache`, images 1 h. Protected: `private`, data `no-cache`, media 1 week |
| CORS | Credentials only for the origins in `SITE_ORIGINS` (wrangler var, comma-separated); public paths also answer `*` without credentials. Without `SITE_ORIGINS`: no credentialed CORS and `/auth` answers 500 |
| Headers | `etag`, `accept-ranges`, `x-content-type-options: nosniff` |

### Access

Rule groups per audience (`<prefix> – All trips`, `<prefix> – <Trip> crew`; `<prefix>` is `access.prefix` in the config, default `Wander`). One self-hosted app per trip with destinations `<media host>/<slug>` and `<media host>/auth/<slug>`. Allow policy = trip crew OR All trips. One-time PIN login. Managed with `tripmap/access.py` (below); the dashboard is the fallback.

### Access scripting (`tripmap/access.py`)

Manages the above through the Cloudflare API, so onboarding needs no dashboard clicks.

| Command | Effect |
|---|---|
| `setup <slug> "<Title>"` | Crew group `<prefix> – <Trip> crew`, reusable policy `<prefix> – <Trip> viewers`, app `<prefix> – <Title>`. `<Trip>` = title minus a trailing year (`--trip` overrides). Names use an en dash (U+2013) |
| `add <slug\|all> <email>` | Add to the trip's crew, or to `<prefix> – All trips` |
| `remove <slug\|all> <email>` | Remove; `--revoke` also ends that person's Access sessions (`revoke_user`) |
| `list <slug\|all>` | Members; for a slug also the app's destinations, policy and session lengths |

| Rule | Behaviour |
|---|---|
| Same for every trip | App: destinations above, `domain` = the first, One-time PIN as the only IdP, no auto-redirect, App Launcher hidden, the cookie settings in `APP_SETTINGS` at the top of `access.py`, session `access.appSession` (default 24 h). Policy: allow, include crew OR All trips, no exclude/require, session `access.policySession` (default 730 h). Running `setup … --dry-run` on an existing trip must print "Nothing to change" |
| Idempotent | Group/policy found by exact name; app by destination first, then name. Matches → "Nothing to change". Differences print as `field: live -> expected` and are written only after y/N (or `--yes`). Updates GET the live object, change only managed fields and PUT the whole object back |
| Never deletes | No app, policy or group is ever deleted; that stays a dashboard action. Two apps on one slug → error |
| Empty group | Holds the rule `nobody@wander.invalid` (can't exist); removing the last member puts it back. Hidden in `list` |
| Guardrails | Before any POST/PUT: groups may hold only email rules; policies only rule-group rules with decision `allow`; apps only reference reusable policies by id. Anything else (everyone, service tokens, IP ranges, email domains, bypass, non_identity…) is refused loudly (exit 3), and setup/add/remove also refuse when a live group already holds such a rule |
| Idempotent members | Adding an existing member or removing a missing one writes nothing and says so. Emails compared lowercase |
| Confirmation | `setup` and `remove` ask y/N unless `--yes`; with no terminal the answer is no. Every write command has `--dry-run` (GETs only) |
| After setup | Runs the publish guard's check on `<slug>/trip.json` and prints it (302/401/403 = protected) |
| Config | No config → exit 2 with how to make one. Media host, prefix and sessions come from it |
| Credentials | `CF_API_TOKEN`, `CF_ACCOUNT_ID` from the environment, else `~/.wander/cloudflare.env` (outside the repo). Missing → prints how to create the token: two Account permissions, `Access: Apps and Policies` and `Access: Organizations, Identity Providers, and Groups` (Edit), nothing broader; exit 2 |
| Token handling | Sent only in the `Authorization` header; never printed, logged or committed (API error text is scrubbed too). Claude Code never reads the file |
| Emails | May appear in terminal output; never in the repo, docs, test fixtures (use `@example.com`) or commit messages |

## Data contract — build your own site

A Wander site is any front end that reads two JSON files from the media host: `trips.json` for the landing page and `<slug>/trip.json` for each trip. That's the whole interface between `tripmap/` (producer) and the site (consumer); the live example was built with Lovable from this section alone. Changing a field means updating this section (and the site).

What a site needs to do:
1. Landing page: fetch `trips.json`; show each trip's `title`, dates, `counts` and cover. For a lock badge, `HEAD <slug>/trip.json` with credentials: 200 = this visitor can open it; anything else = locked.
2. Trip page: fetch `<slug>/trip.json` with credentials. If it fails, show "This trip is private" and a **Sign in** link to `/auth/<slug>?return=<this page's URL>` ([Worker endpoints](#worker-endpoints)).
3. Show items on a map (`lat`/`lon`), by day (`days`, `day`), in time order (`t`), with `thumb`/`card`/`media` as image and video sources.
4. Follow the [client rules](#client-rules) and host the site on the same registrable domain as the media host, with its origin in the Worker's `SITE_ORIGINS`.

Base: `https://<media host>`, e.g. `https://media.example.com`. All paths below are relative to it unless noted.

### `trips.json` (public)
```json
{
  "version": 1,
  "trips": [{
    "slug": "lisbon-2025",
    "title": "Lisbon 2025",
    "start": "2025-05-02", "end": "2025-05-08", "days": 7,
    "cover": "public/covers/lisbon-2025-card.jpg?v=3f9a1c07be",
    "coverImage": "public/covers/lisbon-2025.jpg?v=8d21e4a0c5",
    "counts": { "items": 412, "photos": 350, "videos": 62, "onMap": 398 },
    "data": "lisbon-2025/trip.json",
    "updated": "2025-05-20T19:25:06+00:00"
  }]
}
```
Sorted newest trip first. `cover` ≤640px, `coverImage` 1600px (falls back to `cover`). Both may end in `?v=<hash>` (changes when the cover image changes); use the value as-is.

### `<slug>/trip.json` (protected by Access)
```json
{
  "version": 1, "title": "...", "slug": "...", "generated": "ISO time",
  "tzOffsetMin": 60,
  "start": "YYYY-MM-DD", "end": "YYYY-MM-DD",
  "cover": "cards/<id>.jpg",
  "counts": { "items": 0, "photos": 0, "videos": 0, "onMap": 0 },
  "days": [{ "key": "YYYY-MM-DD", "n": 1, "count": 3 }],
  "items": [{
    "id": "12-hex", "type": "photo|video",
    "t": 1746180000, "day": "YYYY-MM-DD", "dayN": 1,
    "lat": 38.7, "lon": -9.1,
    "loc": "gps|csv|matched|manual|cleared",
    "conf": "high|medium|low",
    "dur": 12.0, "orig": "DJI_2025...MP4",
    "thumb": "thumbs/<id>.jpg", "card": "cards/<id>.jpg", "ar": 1.778,
    "media": "media/<id>.jpg|mp4"
  }]
}
```
- Item paths are relative to `<slug>/`.
- `lat`/`lon` may be absent (unplaced shot). `loc` is an internal *source code*, never a place name — don't display it. `cleared` = deliberately unplaced (no `lat`/`lon`).
- `t` is unix seconds; show times using `tzOffsetMin` (the trip's zone), never the viewer's.
- `day`/`dayN` are computed in the trip zone; `days[].n` counts from the first day (gaps keep their numbers).

### Worker endpoints
- `GET /me` → `{ "email": string|null }` (from the Access cookie; display only).
- `GET /auth/<slug>?return=<url>` → behind the trip's Access app; 302 to `return` if its origin is exactly one of `SITE_ORIGINS` (https), else to `<first site origin>/<slug>`. The site adds `?signedin=1` to `return` to know the visitor just signed in.
- Logout: `/cdn-cgi/access/logout` (Cloudflare).

### Client rules
- `fetch(..., { credentials: 'include' })` for everything on the media host.
- No `crossorigin` attribute on `<img>`/`<video>` (it would drop the cookie).
- Never persist trip data in browser storage.

## Non-functional requirements

| Requirement | How it's kept |
|---|---|
| Originals never leave the disk | Only previews are built and uploaded |
| Raw paths never uploaded | `publish.py` excludes `trip.js`/`index.html`; Worker refuses them |
| No database, ever | Identity = Access cookie; data = static JSON in R2 |
| Free tier only | R2 ≤ 10 GB (~2.5 GB/trip); Cloudflare free plans |
| One copy of the code | Runs from this repo; trip folders hold only a launcher |
| Client rules | See [Client rules](#client-rules) |
| Tested on every push | GitHub Actions runs the tripmap, editor and Worker suites on each push to main; no real exiftool/ffmpeg/rclone, network, config or trip drive needed. A red build is fixed first |
| Privacy in git | No media, overrides, CSVs, trip JSON, coordinates or instance settings committed; docs and tests use example.com |
| Portable | Windows-tested; mac/Linux should work (`.sh` launcher, no OS-specific paths in code) |

## Non-goals

- Public sharing of originals
- Serving originals online, even to the crew. Originals never leave the disk; anyone who wants one asks the owner.
- In-browser editing on the live site
- A user database or our own auth
- Subdomains per trip

## Onboarding a trip

Follow [RUNBOOK.md → New trip](RUNBOOK.md#new-trip).
