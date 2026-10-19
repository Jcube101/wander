# Wander — Learnings

Hard-won lessons. Each one: **symptom → cause → fix/rule**. Add new ones here, not in CLAUDE.md. Accepted limitations are rows too; the design decisions behind it all are under [Decisions](#decisions) (D1–D12).

## Cloudflare / hosting

| Symptom | Cause | Fix / rule |
|---|---|---|
| Worker route and Access on `wander.` did nothing | `wander.job-joseph.com` is an A record to Lovable's own Cloudflare account; no O2O for A records, so this zone's Workers/Access never run | Lock the media host (`media.`) instead; keep `wander.` DNS-only (D7) |
| Risk: Access allows a path the Worker reads differently | Encoded or odd paths (`%2F`, `..`, `//`) can be normalised differently by each | Worker refuses any `%`, `..`, `//`; keys used exactly as sent (D8) |
| Publishing before the Access app existed made the trip public | Access is the only gate; without an app the Worker serves the trip to anyone | `publish.py` refuses to publish an unprotected trip (Access app first, then Publish) |
| Trip page loads but images are blank | `crossorigin` on `<img>`/`<video>` makes the browser drop the Access cookie | Never put `crossorigin` on media tags |
| Site change "didn't work" | Lovable edits only reach the live domain after publishing | Re-publish in Lovable after every change |
| Lovable preview can't load protected trips | The preview origin has no Access cookie for the media host | Accepted, won't fix: test trips on wander.job-joseph.com |
| `travelogue-map-memory.lovable.app` can't load data | Lovable's own published URL isn't in the Worker's CORS list | Intended: wander.job-joseph.com is canonical |
| Docs said the Thailand app was `Wander – Thailand 2026`; the API said `media` (since renamed) | Named in the dashboard before the naming scheme | Find Access apps by destination, not name; a name-only lookup would create a second app on the same paths |
| Access app/group "update" could silently reset settings | `PUT /access/apps/{id}` and `/groups/{id}` take the whole object (`domain`/`type`, `name`/`include` required); there's no PATCH | GET, change only managed fields, drop read-only ones (`id`, `uid`, `aud`, timestamps, deprecated `self_hosted_domains`), PUT the lot |
| Two kinds of Access policy | Reusable (`/access/policies`, attached as `policies: [{id, precedence}]`) vs legacy app-scoped (`/apps/{id}/policies`); mutually exclusive, and legacy can't be added to new apps. A reusable policy still shows up under the app endpoint, with `reusable: true` | Thailand uses a reusable policy; new trips do too |
| A rule group can't be empty | `include` is required and must hold a rule | Placeholder email `nobody@wander.invalid` (RFC 2606 `.invalid` can't exist) |
| Two session lengths | The app has `session_duration` (24 h) and so does the policy (730 h) | Mirror both; check them in `access.py list` |
| A JSON POST from the site would never reach the Worker | `Content-Type: application/json` (or any custom header) makes the browser send a CORS preflight first; Access answers an OPTIONS without a cookie with 403 (`options_preflight_bypass` is off, and stays off) | Writes are "simple requests": a `text/plain` body holding JSON, no custom headers. The Worker accepts that, and refuses any POST whose `Origin` isn't in `SITE_ORIGINS` (CSRF) |
| The site couldn't tell "signed out" from "offline" | Browsers run the CORS check before handling a redirect, so a 302 without CORS headers makes `fetch` reject with a TypeError, even with `redirect: "manual"`. In the local mock it did | Access's 302 does carry `Access-Control-Allow-Origin` + credentials for the site's origin (seen live, 2026-10-20), so `redirect: "manual"` gives a readable `opaqueredirect` = signed out. Fallback for a TypeError: `GET /me`; `email` null = signed out |
| Favourites needed the visitor's identity in the Worker | The `CF_Authorization` cookie can be sent by anyone; Access adds `Cf-Access-Jwt-Assertion` to requests it let through | Verify that header (team's RS256 keys, `iss`, `exp`, `aud` = this trip's app) and take the email only from it. Each trip's AUD lives in `ACCESS_AUD` in `wrangler.toml`, so a new trip needs a Worker deploy for its hearts |
| The favourites salt can't be read back | Worker secrets are write-only | Keep the only readable copy in `~/.wander/favs-salt`; it's needed to find one person's file. A new salt orphans every file |

## R2 / rclone

| Symptom | Cause | Fix / rule |
|---|---|---|
| `CreateBucket ... 403` on publish | Bucket-scoped key can't create buckets, and rclone checks by default | Every rclone call gets `--s3-no-check-bucket` |
| Archived files would have stayed on R2 | `rclone sync` keeps destination files that were excluded (unless `--delete-excluded`) | Never rely on excludes for removal: upload only what `trip.json` references and delete the rest explicitly |
| ETA said 23 h | rclone's early estimate is noise | Ignore it; 2.3 GB took ~10 min |

## Metadata

| Symptom | Cause | Fix / rule |
|---|---|---|
| DJI clips unplaced or at wrong times | DJI Pocket 4P writes no GPS; its clock drifts (~+07:45 vs UTC on Thailand) | Time = filename + `--camera-offset`; location = nearest phone photo or manual fix |
| WhatsApp items at odd times or other trips | WhatsApp strips EXIF; only the filename date survives | Accepted: time = file save time when it matches the date, else noon; items >1 day outside the trip are dropped; never auto-located (may be friends' photos) |
| Removing the built-in `+07:00` / `+07:45` defaults would have shifted the Thailand trip by hours on its next Apply | `build_args.json` saved only the options typed, so the trip silently relied on the defaults | Every option that changes results (`--tz`, `--camera-offset`) is saved explicitly; before changing a default, make existing trips' saved options explicit and compare old vs new builds |
| `--tz -05:00` was rejected | argparse reads `-05:00` as an option, not a value | `build.py` joins offset values to their option (`--tz=-05:00`) before parsing |
| Some Sony phone JPEGs fail with an empty error | Not confirmed. Full-size decodes failed with an empty error message, mostly during parallel builds | Reduced-size `draft` decoding, sequential retry, log `repr(e)` |

## Viewer / editor

| Symptom | Cause | Fix / rule |
|---|---|---|
| Map tiles stopped loading | CARTO raster tiles now need an API key | Esri tiles + OSM (D9) |
| Edit mode lost after picking a day | `history.replaceState` dropped `?edit` | Keep `location.search` when rewriting the URL |
| Hidden element still showed | A CSS `display` rule beat the `[hidden]` attribute | Add an explicit `[hidden]{display:none}` rule |
| Editor changes invisible after a refresh | `serve.py` served `_tripmap/index.html`, a copy of `viewer.html` made at build time | `serve.py` serves the repo's `viewer.html` fresh on every request (`no-store`, also for `trip.js`); the copy is only for `file://` |
| Day chips stretched tall | Grid rows shared spare height | `grid-template-rows: auto auto 1fr auto` |
| Editor page scrolled sideways on a phone | A grid's `auto` column grows to its widest child's min-content (the filter row), even when that child scrolls | `grid-template-columns: minmax(0,1fr)` on `#app` |

## Site / data contract

| Symptom | Cause | Fix / rule |
|---|---|---|
| Captions said "gps" | Site displayed the internal `loc` field | `loc` is a source code — never display it |
| Landing hero blurry | 640 px card used as a full-width hero | Publish a 1600 px `coverImage` too |
| A ZIP of favourites failed on shots the gallery already showed (CORS error) | The `<img>` (no `Origin`, no `crossorigin`) cached the file without CORS headers, and the browser handed that cached copy to the later CORS `fetch` of the same URL. Reproduced in Chromium, 2026-10-20 | Fetch media files with `cache: "no-store"`. Media tags stay without `crossorigin` |
| `<a download="name">` to the media host saved nothing useful | The `download` attribute is ignored for cross-origin URLs | `?download=1`: the Worker adds `Content-Disposition: attachment` with the readable name |
| Rule (iPhone, not yet seen live): the share sheet can refuse after a slow fetch | `navigator.share` needs a recent tap; fetching a big video first can use it up (`NotAllowedError`) | Keep the fetched file; the button turns into **Save** and the next tap shares at once |
| Reference viewer stuck on "Loading…", unstyled, at `/<slug>/` on Pages | Relative `app.js`/`style.css` resolved under `/<slug>/`, and Pages' SPA fallback answered them with `index.html` (text/html), which browsers refuse as a module or stylesheet | Root-absolute asset and home links (`/app.js`, `/`); a site test resolves them from `/`, `/<slug>` and `/<slug>/`. Serve the viewer from the root of its host name |

## Dev workflow

| Symptom | Cause | Fix / rule |
|---|---|---|
| `git init` ran in the home folder | Backslash path broke `cd` in Git Bash, next command ran anyway | Use forward slashes (`~/Github/wander`); chain with `&&` |
| Shell killed itself | `pkill -f <pattern>` matched its own command line | Kill by port or PID |
| Every code change had to be made twice: in the repo and in the copy inside the trip folder on D: | The code was copied into each trip folder | Run from the repo; each trip folder only holds `Open Wander Editor.bat` |
| Time spent "fixing" non-bugs | Reports were often misdiagnoses | Investigate and reproduce before fixing |
| A test passed on Windows and failed in CI (`…-favourites-Alex` vs `-alex`) | Windows and macOS file systems ignore case, Linux doesn't, so `Path(...).is_dir()` matched the wrong case locally | Tests check exact names (`[p.name for p in dir.iterdir()]`); names built from emails are lowercased |

## Decisions

**D1 — Originals stay on the external disk; only previews go online.** 140 GB of originals is too much for cheap hosting and isn't needed for viewing. Bundle is ~2.5 GB per trip (thumbs 200px, cards 640px, photos 1600px, video 720p H.264). Friends heart the shots they want; the owner exports those originals and hands them over (D12).

**D2 — Cloudflare R2 over S3.** Zero egress fees (video replays cost nothing), 10 GB free, same Cloudflare account as the domain, S3-compatible tooling (rclone).

**D3 — Lovable for the public site; local viewer kept as the editor.** Lovable gives the design and Job iterates there; the editing tools (bulk placement, day/time shifts) stay local where they can write files and run the builder. No credits spent on editor features.

**D4 — Location fixes as an overrides file, not EXIF edits.** Originals are never modified; `overrides.json` (keyed by relative path) is applied at build time. Manual fixes also act as anchors for nearest-in-time matching.

**D5 — Two subdomains total, trips as paths.** `wander.` (site) and `media.` (data). New trips are folders/routes, not subdomains.

**D6 — No database; Cloudflare Access is the source of truth for who sees what.** Per-trip rule groups + one Access app per trip. Free up to 50 users. Rejected: Clerk (would still need a Worker to protect media, plus auth code), Supabase (no free DBs left, and not needed).

**D7 — The lock is on `media.`, not `wander.`.** `wander` is a Lovable-hosted A record (185.158.133.1) on Lovable's own Cloudflare account; this zone's Workers and Access don't run for it (O2O only applies to CNAMEs). Tried proxying + Worker route: request bypassed the Worker. So: app shell is public, all trip data/media sits behind Access on `media.`. Sign-in uses a top-level `/auth/<slug>` hop; the Access cookie is same-site with wander, so `<img>`/`<video>` and credentialed fetches carry it.

**D8 — Worker serves an allow-list and refuses encoded paths.** Prevents Access/Worker path disagreements (e.g. `%2F`) and exposure of non-public files (`trip.js` has local paths).

**D9 — Esri tiles in the local viewer.** CARTO began requiring an API key.

**D10 — One public repo; each instance's settings live outside git.** Domains, bucket, rclone remote and Access naming are in `~/.wander/config.json` (Python tools) and a gitignored `worker/wrangler.toml` (the Worker's route, bucket and `SITE_ORIGINS`), each with a committed `*.example.*` template. Two files rather than one because wrangler needs its own format for routes and bindings; they only share the media host and bucket. Owner-specific notes for Claude Code live in `~/.wander/NOTES.md`, which CLAUDE.md imports when present. Docs and tests use example.com and a made-up trip. Sign-in now returns only to an exact `SITE_ORIGINS` origin (it used to accept any subdomain of the owner's domain).

**D11 — Favourites are per person, in R2, keyed by a salted hash of the email.** Synced across devices without a database: one small JSON file per person per trip (`favs/<slug>/<sha256(salt + email)>.json`), read and written only by the Worker at `/<slug>/favorites`, which the trip's Access app already guards. Identity comes from the Access token the Worker verifies, never from the page. The salt is a Worker secret, so file names can't be reversed by hashing known emails; no email is stored. v1 is private (no shared counts). Read-modify-write with last write wins is fine for one person tapping a few hearts; the site queues its taps. Rejected: browser storage (doesn't sync, and the client rules forbid storing trip data), a KV/D1 database (D6), sending the email from the page (forgeable).

**D12 — Downloads: previews from the site, originals by hand.** The site offers the files people already view (1600 px photos, 720p clips) as downloads: one shot via `?download=1` (the Worker names it `<date>_<time>_<original name>`), or on desktop the favourites in view as one ZIP built in the browser (uncompressed, at most 500 MB, so pick a day for more). Phones save one shot at a time through the share sheet, which can put it in Photos. Originals still never go online (D1): someone hearts what they want, and the owner runs `tripmap/export_favs.py`, which reads their favourites from R2 and copies the originals into a folder to hand over. Rejected: serving originals behind Access (140 GB per trip, and R2's free tier is 10 GB); a server-side ZIP (a Worker can't hold hundreds of MB, and it would need a new endpoint).
