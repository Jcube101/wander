# Wander — Roadmap

Size: **S** ≈ an evening, **M** ≈ a weekend, **L** ≈ several sessions. Open known issues are rows marked **Known issue**; accepted limitations live in [LEARNINGS.md](LEARNINGS.md).

## Done

- [x] **Local map and editor:** metadata, DJI/phone/WhatsApp time handling, CSV + nearest-shot location, previews, incremental builds; filters, multi-select placement, drag, move-to-day, shift-time, undo, autosave.
- [x] **R2 publish:** safe upload order, cache headers, `trips.json`, public covers.
- [x] **Worker on `media.job-joseph.com`:** allow-list, Range, CORS, `/auth`, `/me`.
- [x] **Per-trip Access:** rule groups, one app per trip, sign-in flow, lock badges.
- [x] **Lovable site:** landing + trip pages, gallery, map, timeline, viewer, play journey.
- [x] **Stale bucket objects removed:** early-publish `trip.js` / `index.html` deleted from R2.
- [x] **Archive in the editor:** hide shots from the published trip (removed from R2), kept locally; Restore puts them back.
- [x] **Choose the cover in the editor:** Set as cover / Automatic cover; stored as `settings.cover` in `overrides.json`; `?v=` so a new cover shows at once.
- [x] **tripmap test suite:** unittest, 65 tests (time/location rules, archive, cover, publish, editor server), runs in CI; exiftool/ffmpeg/rclone stubbed.
- [x] **GitHub Actions:** tripmap and Worker tests on every push to main.
- [x] **R2 storage check:** `publish.py` projects the bucket size and warns above 8 GB and 10 GB (never blocks).
- [x] **Run from the repo:** one-file launcher per trip folder; one-click Apply / Scan / Publish.
- [x] **Access scripting:** `tripmap/access.py` (setup / add / remove / list) via the Cloudflare API, mirroring the Thailand app; guardrails, never deletes; `/new-trip` applies step 5 after a yes.
- [x] **Editor toolbar + "where did this happen":** one toolbar row with a ⋯ menu and ? help; a selection bar with only the actions that apply; selecting shows the pin, or the nearest placed shots before/after with time gaps; Place at previous / next (`[` / `]`); Follow selection toggle. Neighbour lookup tested in node (CI).

## Now

Go public, tasks 1–6 (one session, in order). Task 7 is Job's.

## Initiative: Go public

**Goal:** make the repo public and usable by anyone, as portfolio material. There is one repo, and Job keeps using it through a local, gitignored config. His story stays in (not anonymous). MIT license.

**Constraint for every task:** Job's live setup must still work when the task is done: wander.job-joseph.com, the media Worker, Access, and publishing the Thailand trip. CI must stay green. Each task ends with a commit to main and a green CI run, and is ticked here with a one-line note. After a restart, resume from the first unticked task.

- [x] **1. Audit (read-only).** Size **S**. Depends on: —. *Done: ~25 values classified; the list is in Job's `%USERPROFILE%\.wander\go-public-audit.md` (it names the real values, so it stays out of the repo).*
  List every personal or instance-specific value with file:line: domains, paths, bucket, rclone remote, Zero Trust team, Lovable project ID/IP, Thailand slug/dates/timezones, names, "parents". Classify each one as *config* (make it configurable), *example* (replace with example.com), *story* (keep, but only in README/LEARNINGS) or *remove*. Write the list where later tasks can use it. Make no other changes.
- [x] **2. Config extraction.** Size **L**. Depends on: 1. *Done: `tripmap/config.py` + `wander.config.example.json`; Worker reads `SITE_ORIGINS` from wrangler vars (`wrangler.example.toml` committed, real one untracked); redeployed and checked live; Thailand dry-run publish, `access.py setup --dry-run` ("Nothing to change") and the editor all pass through Job's config.*
  One `wander.config.json`. Commit `wander.config.example.json`; Job's real file is `%USERPROFILE%\.wander\config.json`. It covers the site origins, media domain, bucket, rclone remote, Access naming prefix and defaults. build/publish/access/serve read it. The Worker reads its values from wrangler vars, with a committed `wrangler.example.toml` and Job's real `wrangler.toml` gitignored (`git rm --cached`, so his copy stays and still deploys). Move Job's values into his local config so nothing breaks. Tests use example.com.
- [ ] **3. Neutral defaults and portability.** Size **M**. Depends on: 2.
  No built-in timezone or camera offset: a new trip must set its timezone, and the camera offset defaults to 0. The launcher finds the repo relative to itself, with no `C:\Users\jobjo`. Add a `.sh` launcher. The docs say "Windows-tested; mac/Linux should work".
- [ ] **4. Docs for strangers (incl. CONTRIBUTING.md and LICENSE).** Size **L**. Depends on: 2, 3.
  - README: what Wander is, why Job built it (his story), the live landing page as the example (trips stay locked), an architecture diagram and a quick start.
  - SETUP: step-by-step first-time setup: Cloudflare account and domain, R2 bucket, scoped rclone key, Worker deploy, Access and the API token, then the first trip.
  - The data contract presented as "build your own site".
  - LICENSE (MIT, Job Joseph) and a short, friendly CONTRIBUTING (dev setup, tests, hard rules, issues then small PRs, spare-time maintenance).
  - CLAUDE.md and RUNBOOK made generic. Job's instance facts move to his local config/notes, out of the repo.
  - LEARNINGS keeps the real stories.
- [ ] **5. Pre-flight checks.** Size **M**. Depends on: 4.
  - A fresh clone with the example config: all tests pass, and `publish --dry-run` runs (against a mock, or fails cleanly without credentials).
  - A secret scan (e.g. gitleaks) over the full history. History keeps old personal values, so check that nothing *private* is in it (media, coordinates, tokens, trip JSON), not only the current tree.
  - Personal terms appear only in the allowed "story" places.
  - Review `.gitignore`.
  - Prepare the GitHub description, topics and a social-preview image.
- [ ] **6. Reference viewer.** Size **L**. Depends on: 2 (config), 5.
  A simple static viewer that reads `trips.json`/`trip.json` through the Worker and can be deployed on Cloudflare Pages, so people don't need Lovable. Reuse the local viewer's map code where it makes sense. Ends by re-running task 5's checks, so the viewer is covered too.
- [ ] **7. Go public (Job does this himself).** Size **S**. Depends on: 6.
  Flip the visibility and confirm CI is green on the public repo. Check Job's instance: a dry-run publish, `access.py list`, and the site in an incognito window.

## Next

| Item | Why | Size | Depends on |
|---|---|---|---|
| **Known issue:** early DJI clips (before ~2 Oct midday) have an uncertain camera offset | Left unplaced on the Thailand trip; fix in the editor (Shift time / place) | S | — |
| **Known issue:** last Bangalore clips on 10 Oct have no phone anchors | Unplaced on the Thailand trip; place them in the editor | S | — |

## Later

| Item | Why | Size | Depends on |
|---|---|---|---|
| Reverse-geocoded place names | Captions and day chips say "Chiang Mai", not just a pin | M | Data-contract change + Lovable prompt; names stay in protected `trip.json` only |
| Duplicate detection (perceptual hash) | Same photo from two sources appears twice | M | — |
