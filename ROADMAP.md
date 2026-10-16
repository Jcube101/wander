# Wander — Roadmap

Size: **S** ≈ an evening, **M** ≈ a weekend, **L** ≈ several sessions. Known problems: [docs/known-issues.md](docs/known-issues.md).

## Done

- [x] **Local map and editor:** metadata, DJI/phone/WhatsApp time handling, CSV + nearest-shot location, previews, incremental builds; filters, multi-select placement, drag, move-to-day, shift-time, undo, autosave.
- [x] **R2 publish:** safe upload order, cache headers, `trips.json`, public covers.
- [x] **Worker on `media.job-joseph.com`:** allow-list, Range, CORS, `/auth`, `/me`.
- [x] **Per-trip Access:** rule groups, one app per trip, sign-in flow, lock badges.
- [x] **Lovable site:** landing + trip pages, gallery, map, timeline, viewer, play journey.
- [x] **Stale bucket objects removed:** early-publish `trip.js` / `index.html` deleted from R2.
- [x] **Archive in the editor:** hide shots from the published trip (removed from R2), kept locally; Restore puts them back.
- [x] **GitHub Actions:** tripmap and Worker tests on every push to main.
- [x] **R2 storage check:** `publish.py` projects the bucket size and warns above 8 GB and 10 GB (never blocks).
- [x] **Run from the repo:** one-file launcher per trip folder; one-click Apply / Scan / Publish.

## Now

| Item | Why | Size | Depends on |
|---|---|---|---|
| pytest suite for tripmap (fixture trip, stubbed exiftool/ffmpeg/rclone) | Time/location rules are subtle; no tests today | M | — |

## Next

| Item | Why | Size | Depends on |
|---|---|---|---|
| Choose the trip cover in edit mode | Auto pick (middle placed photo) isn't always the best | S | Trip-level setting in `overrides.json`; publish already handles covers |
| Script Access groups/apps via the Cloudflare API | Onboarding is manual clicking in Zero Trust; would let `/new-trip` do runbook step 5 too | M | API token kept outside the repo |
| Batch "new trip" bootstrap command | Build + launcher + publish + Access in one go | M | Access scripting |

## Later

| Item | Why | Size | Depends on |
|---|---|---|---|
| Reverse-geocoded place names | Captions and day chips say "Chiang Mai", not just a pin | M | Data-contract change + Lovable prompt; names stay in protected `trip.json` only |
| Duplicate detection (perceptual hash) | Same photo from two sources appears twice | M | pytest suite |
| Lovable preview loading protected trips | Preview origin has no Access cookie | S | Likely won't fix — test on wander.job-joseph.com |
