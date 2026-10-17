# CLAUDE.md — Wander

Context for AI assistants working in this repo.

## What this is
Tooling and infrastructure for Wander, a private multi-trip travel archive. Two parts:
- `tripmap/` — Python (3.9+, Pillow; shells out to exiftool, ffmpeg, rclone). Builds a trip folder into map data and previews, runs the local editor, publishes to R2, manages Cloudflare Access. Runs **from this repo** against a trip folder (often on an external drive); each trip folder only holds the launcher that `tripmap/launcher.py` writes. Never copy the code into trip folders.
- `worker/` — Cloudflare Worker (plain JS, no deps) bound to a private R2 bucket, on the instance's media host.

- `site/` — reference viewer: a static site (HTML/CSS/JS modules, Leaflet) that reads the data contract; deployable to Cloudflare Pages. Media host in `site/public/config.js` (example.com in git).

The live instance's own website may live elsewhere (see the instance notes); any static site that follows the data contract can be the front end.

## Instance settings (never in git)
- `~/.wander/config.json` (or `wander.config.json` in the repo root, or `$WANDER_CONFIG`): site URL, media host, rclone remote + bucket, Access name prefix and session lengths. Template: `wander.config.example.json`; loaded by `tripmap/config.py`.
- `worker/wrangler.toml` (gitignored): the Worker's route, bucket and `SITE_ORIGINS`. Template: `worker/wrangler.example.toml`.
- `~/.wander/cloudflare.env`: the Access API token.
- `~/.wander/NOTES.md`: the instance owner's notes (their domains, trips, trip drive, deploy checks). Optional; imported here when it exists, and it wins over anything generic below:

@~/.wander/NOTES.md

Committed files, docs, tests and commit messages use `example.com` and a made-up trip (`lisbon-2025`), never real domains, emails, paths, trip names or coordinates.

## Hard rules
- **Privacy:** never commit media, `_tripmap/`, `overrides.json`, `clip_locations.csv`, any `trip.json`/`trips.json`, coordinates, or instance settings. `.gitignore` enforces this — don't weaken it.
- **Access lives in Cloudflare Zero Trust**, not in code. The Worker never decides *who* may see a trip; it only serves an allow-list of file types. Each trip = one Access app covering `<media host>/<slug>` and `<media host>/auth/<slug>`.
- **Worker path handling:** keys are used exactly as sent; any `%`-encoding, `..` or `//` is refused so Access and the Worker can't disagree about paths. Keep it that way.
- **Cloudflare API token** lives in `~/.wander/cloudflare.env`, read only by `tripmap/access.py`. Never read, print or commit it; never write Access changes without the owner's yes to the `--dry-run` plan.
- **Never upload `trip.js` or `index.html`** to R2 — `trip.js` contains local folder paths. `publish.py` excludes them; the Worker refuses them anyway.
- **rclone key is bucket-scoped** → every rclone call needs `--s3-no-check-bucket` (already in `publish.py`).
- **No built-in timezone or camera offset:** `build.py --tz` is required; the camera offset defaults to `+00:00`; both are saved in `build_args.json`.
- **Live Worker:** deploy only after tests pass, then run RUNBOOK → Worker deploys checks straight away; if one fails, `npx wrangler rollback` before investigating.
- Don't add a database. Identity = Cloudflare Access cookie; data = static JSON in R2.
- **Git:** the maintainer commits straight to main; no branches or PRs unless asked. Outside contributions come as small PRs (CONTRIBUTING.md).

## Data contract
SPEC.md → "Data contract — build your own site" is the interface between `tripmap/` (producer) and any site (consumer). Changing a field means updating that section (and telling whoever runs the site).

## Adding a trip
Use `/new-trip`, which follows `RUNBOOK.md` → New trip.

## Testing
- Worker: `cd worker && npm test` (node, mocked R2 bucket).
- Editor: `node --test tripmap/tests/test_viewer.mjs` (pure helpers extracted from `viewer.html`'s `<script id="tripmap-pure">` block).
- Reference viewer: `cd site && npm test` (pure helpers in `site/public/lib.js`).
- tripmap: `python -m unittest discover tripmap/tests` (time/location rules, archive, cover, publish, serve, access, config, launchers; exiftool/ffmpeg/rclone/network and the Cloudflare API are stubbed). Tests always use `wander.config.example.json`. `test_build_rules.py` locks in current time/location behaviour: if a change there is intended, update the test with it.
- CI (`.github/workflows/test.yml`) runs all four on every push to main. After every push, check the run with `gh run list --limit 1` (or `gh run watch`). Fix a red build before doing anything else. The runner is pinned to `ubuntu-24.04` (not `ubuntu-latest`) so an image switch can't break CI unannounced; bump it on purpose later, in its own commit, and check the run.

## Project docs
- `README.md` — what it is, why it exists, architecture, quick start.
- `SETUP.md` — first-time setup, step by step.
- `SPEC.md` — what Wander must do, how the pieces fit, and the data contract.
- `RUNBOOK.md` — everyday tasks, new trip, Worker deploy checks, troubleshooting.
- `ROADMAP.md` — Done / Now / Next / Later.
- `LEARNINGS.md` — gotchas (symptom → cause → fix), accepted limitations, and Decisions D1–D10. Read it before debugging; add new lessons there.
- `CONTRIBUTING.md` — dev setup, tests, the rules every change keeps.
