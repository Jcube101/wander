# Wander — Roadmap

Size: **S** ≈ an evening, **M** ≈ a weekend, **L** ≈ several sessions. Open known issues are rows marked **Known issue**; accepted limitations live in [LEARNINGS.md](LEARNINGS.md).

## Done

- [x] **Local map and editor:** metadata, DJI/phone/WhatsApp time handling, CSV + nearest-shot location, previews, incremental builds; filters, multi-select placement, drag, move-to-day, shift-time, undo, autosave.
- [x] **R2 publish:** safe upload order, cache headers, `trips.json`, public covers.
- [x] **Worker on the media host:** allow-list, Range, CORS, `/auth`, `/me`.
- [x] **Per-trip Access:** rule groups, one app per trip, sign-in flow, lock badges.
- [x] **Live site (built with Lovable, separate repo):** landing + trip pages, gallery, map, timeline, viewer, play journey.
- [x] **Stale bucket objects removed:** early-publish `trip.js` / `index.html` deleted from R2.
- [x] **Archive in the editor:** hide shots from the published trip (removed from R2), kept locally; Restore puts them back.
- [x] **Choose the cover in the editor:** Set as cover / Automatic cover; stored as `settings.cover` in `overrides.json`; `?v=` so a new cover shows at once.
- [x] **tripmap test suite:** unittest, 65 tests (time/location rules, archive, cover, publish, editor server), runs in CI; exiftool/ffmpeg/rclone stubbed.
- [x] **GitHub Actions:** tripmap and Worker tests on every push to main.
- [x] **R2 storage check:** `publish.py` projects the bucket size and warns above 8 GB and 10 GB (never blocks).
- [x] **Run from the repo:** one-file launcher per trip folder; one-click Apply / Scan / Publish.
- [x] **Access scripting:** `tripmap/access.py` (setup / add / remove / list) via the Cloudflare API, mirroring the first hand-made trip app; guardrails, never deletes; `/new-trip` applies step 5 after a yes.
- [x] **Editor toolbar + "where did this happen":** one toolbar row with a ⋯ menu and ? help; a selection bar with only the actions that apply; selecting shows the pin, or the nearest placed shots before/after with time gaps; Place at previous / next (`[` / `]`); Follow selection toggle. Neighbour lookup tested in node (CI).

## Now

Go public: tasks 1–6 are done. Task 7 (flipping the repo to public) is the maintainer's.

## Initiative: Go public

**Goal:** make the repo public and usable by anyone, as portfolio material. There is one repo, and the maintainer keeps using it through a local, gitignored config. The maintainer's story stays in the README (not anonymous). MIT license.

**Constraint for every task:** the maintainer's live instance must still work when the task is done: the live site, the media Worker, Access, and publishing the live trip. CI must stay green. Each task ends with a commit to main and a green CI run, and is ticked here with a one-line note. After a restart, resume from the first unticked task.

- [x] **1. Audit (read-only).** Size **S**. Depends on: —. *Done: ~25 values classified; the list is in the maintainer's `~/.wander/` (it names the real values, so it stays out of the repo).*
  List every personal or instance-specific value with file:line: domains, paths, bucket, rclone remote, Zero Trust team, site-builder project ID/IP, the live trip's slug/dates/timezones, names, family references. Classify each one as *config* (make it configurable), *example* (replace with example.com), *story* (keep, but only in README/LEARNINGS) or *remove*. Write the list where later tasks can use it. Make no other changes.
- [x] **2. Config extraction.** Size **L**. Depends on: 1. *Done: `tripmap/config.py` + `wander.config.example.json`; Worker reads `SITE_ORIGINS` from wrangler vars (`wrangler.example.toml` committed, real one untracked); redeployed and checked live; the live trip's dry-run publish, `access.py setup --dry-run` ("Nothing to change") and the editor all pass through the maintainer's config.*
  One `wander.config.json`. Commit `wander.config.example.json`; the maintainer's real file is `~/.wander/config.json`. It covers the site origins, media domain, bucket, rclone remote, Access naming prefix and defaults. build/publish/access/serve read it. The Worker reads its values from wrangler vars, with a committed `wrangler.example.toml` and the real `wrangler.toml` gitignored (`git rm --cached`, so the local copy stays and still deploys). Move the maintainer's values into the local config so nothing breaks. Tests use example.com.
- [x] **3. Neutral defaults and portability.** Size **M**. Depends on: 2. *Done: `--tz` required, camera offset defaults to 0 and is always saved; `launcher.py` writes a `.bat`/`.sh` launcher that points at the repo; the live trip's saved options made explicit first, and old vs new code build it identically.*
  No built-in timezone or camera offset: a new trip must set its timezone, and the camera offset defaults to 0. The launcher finds the repo relative to itself, with no user-specific path. Add a `.sh` launcher. The docs say "Windows-tested; mac/Linux should work".
- [x] **4. Docs for strangers (incl. CONTRIBUTING.md and LICENSE).** Size **L**. Depends on: 2, 3. *Done: new README (story, live example, diagram, quick start), SETUP.md, LICENSE, CONTRIBUTING.md; SPEC's data contract is now "build your own site"; CLAUDE.md, RUNBOOK, ROADMAP and `/new-trip` generic; instance facts moved to the maintainer's `~/.wander/NOTES.md` (imported by CLAUDE.md when present).*
  - README: what Wander is, why it was built (the maintainer's story), the live landing page as the example (trips stay locked), an architecture diagram and a quick start.
  - SETUP: step-by-step first-time setup: Cloudflare account and domain, R2 bucket, scoped rclone key, Worker deploy, Access and the API token, then the first trip.
  - The data contract presented as "build your own site".
  - LICENSE (MIT) and a short, friendly CONTRIBUTING (dev setup, tests, hard rules, issues then small PRs, spare-time maintenance).
  - CLAUDE.md and RUNBOOK made generic. Instance facts move to local config/notes, out of the repo.
  - LEARNINGS keeps the real stories.
- [x] **5. Pre-flight checks.** Size **M**. Depends on: 4. *Done: fresh clone + example config passes all suites, builds/edits a made-up trip, and `publish --dry-run` stops cleanly; gitleaks (full history) clean apart from the fake test token, now marked; no media, coordinates, trip JSON or tokens in history; `.gitignore` fixed for upper-case media names, `*.env`, GPX/KML/RAW; SECURITY.md added; description, topics and social preview prepared.*
  - A fresh clone with the example config: all tests pass, and `publish --dry-run` runs (against a mock, or fails cleanly without credentials).
  - A secret scan (e.g. gitleaks) over the full history. History keeps old personal values, so check that nothing *private* is in it (media, coordinates, tokens, trip JSON), not only the current tree.
  - Personal terms appear only in the allowed "story" places.
  - Review `.gitignore`.
  - Prepare the GitHub description, topics and a social-preview image.
- [x] **6. Reference viewer.** Size **L**. Depends on: 2 (config), 5. *Done: `site/` — static landing + trip pages (map with the editor's tiles and photo pins, day filter, gallery, photo/video viewer, sign-in flow), SRI-pinned Leaflet, deploys to Cloudflare Pages; helpers tested in CI; checked in a browser against a mock media host and read-only against the live one. Task 5's checks re-run afterwards: all clean.*
  A simple static viewer that reads `trips.json`/`trip.json` through the Worker and can be deployed on Cloudflare Pages, so people don't need Lovable. Reuse the local viewer's map code where it makes sense. Ends by re-running task 5's checks, so the viewer is covered too.
- [ ] **7. Go public (the maintainer does this).** Size **S**. Depends on: 6.
  Flip the visibility and confirm CI is green on the public repo. Check the live instance: a dry-run publish, `access.py list`, and the site in an incognito window.

## Next

| Item | Why | Size | Depends on |
|---|---|---|---|
| Go public, task 7 | See above | S | Tasks 1–6 |

## Later

| Item | Why | Size | Depends on |
|---|---|---|---|
| Reverse-geocoded place names | Captions and day chips say a town's name, not just a pin | M | Data-contract change + site update; names stay in protected `trip.json` only |
| Duplicate detection (perceptual hash) | Same photo from two sources appears twice | M | — |
