# CLAUDE.md — Wander

Context for AI assistants working in this repo.

## What this is
Tooling and infrastructure for Wander, a private multi-trip travel archive. Two parts:
- `tripmap/` — Python (3.9+, Pillow; shells out to exiftool, ffmpeg, rclone). Runs **from this repo** on Job's Windows machine against a trip folder on an external drive; each trip folder only holds `Open Wander Editor.bat` (template in `tripmap/`). Never copy the code into trip folders.
- `worker/` — Cloudflare Worker (plain JS, no deps) bound to the private R2 bucket `trip-media`, custom domain `media.job-joseph.com`.

The website itself is NOT in this repo: it's the Lovable project synced to `Jcube101/travelogue-map-memory`. Change it via Lovable prompts; it must be re-published in Lovable to reach wander.job-joseph.com.

## Hard rules
- **Privacy:** never commit media, `_tripmap/`, `overrides.json`, `clip_locations.csv`, any `trip.json`/`trips.json`, or coordinates. `.gitignore` enforces this — don't weaken it.
- **Access lives in Cloudflare Zero Trust**, not in code. The Worker never decides *who* may see a trip; it only serves an allow-list of file types. Each trip = one Access app covering `media.job-joseph.com/<slug>` and `/auth/<slug>`.
- **Worker path handling:** keys are used exactly as sent; any `%`-encoding, `..` or `//` is refused so Access and the Worker can't disagree about paths. Keep it that way.
- **Cloudflare API token** lives in `%USERPROFILE%\.wander\cloudflare.env`, read only by `tripmap/access.py`. Never read, print or commit it; never write Access changes without Job's yes to the `--dry-run` plan.
- **Never upload `trip.js` or `index.html`** to R2 — `trip.js` contains local folder paths. `publish.py` excludes them; the Worker refuses them anyway.
- **rclone key is bucket-scoped** → every rclone call needs `--s3-no-check-bucket` (already in `publish.py`).
- Don't add a database. Identity = Cloudflare Access cookie; data = static JSON in R2.
- **Git:** private repo, so commit straight to main. No branches or PRs unless Job asks.

## Data contract
`docs/data-contract.md` is the interface between `tripmap/` (producer) and the Lovable site (consumer). Changing a field means updating that doc and sending Lovable a prompt.

## Adding a trip
Use `/new-trip`, which follows `docs/runbook.md` → New trip.

## Testing
- Worker: `cd worker && npm test` (node, mocked R2 bucket).
- Editor: `node --test tripmap/tests/test_viewer.mjs` (pure helpers extracted from `viewer.html`'s `<script id="tripmap-pure">` block).
- tripmap: `python -m unittest discover tripmap/tests` (time/location rules, archive, cover, publish, serve, access; exiftool/ffmpeg/rclone/network and the Cloudflare API are stubbed). `test_build_rules.py` locks in current time/location behaviour: if a change there is intended, update the test with it.
- CI (`.github/workflows/test.yml`) runs all three on every push to main. After every push, check the run with `gh run list --limit 1` (or `gh run watch`). Fix a red build before doing anything else. The runner is pinned to `ubuntu-24.04` (not `ubuntu-latest`) so an image switch can't break CI unannounced; bump it on purpose later, in its own commit, and check the run.

## Project docs
- `SPEC.md` — what Wander must do (requirements, non-goals). `ROADMAP.md` — Now / Next / Later.
- `LEARNINGS.md` — gotchas learned the hard way (symptom → cause → fix). Read it before debugging; add new lessons there.
