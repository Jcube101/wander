# Wander — Roadmap

Size: **S** ≈ an evening, **M** ≈ a weekend, **L** ≈ several sessions. Known problems: [docs/known-issues.md](docs/known-issues.md).

## Done

- [x] **Local map and editor:** metadata, DJI/phone/WhatsApp time handling, CSV + nearest-shot location, previews, incremental builds; filters, multi-select placement, drag, move-to-day, shift-time, undo, autosave.
- [x] **R2 publish:** safe upload order, cache headers, `trips.json`, public covers.
- [x] **Worker on `media.job-joseph.com`:** allow-list, Range, CORS, `/auth`, `/me`.
- [x] **Per-trip Access:** rule groups, one app per trip, sign-in flow, lock badges.
- [x] **Lovable site:** landing + trip pages, gallery, map, timeline, viewer, play journey.
- [x] **Run from the repo:** one-file launcher per trip folder; one-click Apply / Scan / Publish.

## Now

| Item | Why | Size | Depends on |
|---|---|---|---|
| pytest suite for tripmap (fixture trip, stubbed exiftool/ffmpeg/rclone) | Time/location rules are subtle; no tests today | M | — |
| GitHub Actions: worker tests (tripmap tests once they exist) | Catch Worker regressions before deploy | S | pytest for the tripmap half |
| R2 budget check in `publish.py` (warn near 10 GB) | Each trip is ~2.5 GB; the 4th trip could leave the free tier | S | — |
| Delete stale `thailand-2026/trip.js` + `index.html` from R2 | Old objects hold local paths; Worker blocks them but they shouldn't exist | S | — |

## Next

| Item | Why | Size | Depends on |
|---|---|---|---|
| Archive button in the editor | Hide a shot from the published trip without deleting it; stays local | M | New `overrides.json` field; build filter; data-contract note |
| Choose the trip cover in edit mode | Auto pick (middle placed photo) isn't always the best | S | Trip-level setting in `overrides.json`; publish already handles covers |
| Script Access groups/apps via the Cloudflare API | Onboarding is manual clicking in Zero Trust | M | API token kept outside the repo |
| Batch "new trip" bootstrap command | Build + launcher + publish + Access in one go | M | Access scripting |

## Later

| Item | Why | Size | Depends on |
|---|---|---|---|
| Reverse-geocoded place names | Captions and day chips say "Chiang Mai", not just a pin | M | Data-contract change + Lovable prompt; names stay in protected `trip.json` only |
| Duplicate detection (perceptual hash) | Same photo from two sources appears twice | M | pytest suite |
| Original-file request flow (time-limited links, crew only) | Friends ask for full-res files | L | Access scripting; never public |
| Lovable preview loading protected trips | Preview origin has no Access cookie | S | Likely won't fix — test on wander.job-joseph.com |
