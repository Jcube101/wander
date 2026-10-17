---
description: Start a new Wander trip (preflight, quick build, launcher, Access after the owner's yes), then hand over the publish checklist
argument-hint: "<trip folder>" "<Title>" <+HH:MM tz, required> [camera offset +HH:MM, default +00:00]
---

# New trip

Arguments: `$ARGUMENTS` → trip folder, title, timezone, optional DJI camera offset. If any required one is missing, ask for it before doing anything.

The procedure is **RUNBOOK.md → "New trip"**. Read it now and follow it; it is the only place the steps are written out. Derive `<slug>` (as `build.py` does: lowercase, non-alphanumerics → `-`) and `<Trip>` (short name: the title without a trailing year, e.g. `Bali 2027` → `Bali`). Confirm `<Trip>` with the user if unsure. Run `python tripmap/config.py` to get the media host, remote and bucket (it fails with instructions if there's no config: stop and pass them on).

## Rules for this command
- **Never publish.** Not `publish.py`, not `--allow-unprotected`, not the editor's button.
- **Never run the full build** (no build without `--quick`). It can take hours; the user runs it with the editor's **Scan for new files**.
- **Never write emails, coordinates, file paths from the trip, or trip data into the repo**, and don't paste coordinates into chat. Counts and filenames are fine in the report.
- Scratch scripts go in your scratchpad, not the repo.
- **Access writes only after the user says yes** to the dry-run plan in this conversation. Never read `~/.wander/cloudflare.env`; `access.py` loads it itself.

## Do: runbook steps 1–3
1. **Preflight.** Check each tool, Pillow and the config, and that the slug isn't in `trips.json`. If the slug exists, stop and ask whether this is a republish.
2. **Quick build** with `--name`, `--tz`, `--camera-offset` (if given) and `--quick`. Then read `<folder>/_tripmap/trip.js` (strip `window.TRIP = ` and the trailing `;`) and report:
   - items (photos / videos) and days
   - items with no location (`lat` missing)
   - lines in `_tripmap/build_errors.txt` (if any) and "skipped (no usable time)" from the build output
   - DJI clips found (`tsrc == "dji-filename"`)
   - **Camera offset check:** for each DJI clip, find the nearest phone photo with a firm time (`tsrc` in `exif+offset`, `gps-time`) and note the signed gap. Report the median gap and the per-day medians. A median beyond ~30 min, or a consistent same-sign gap, means the offset is probably off. Suggest a corrected `--camera-offset` (current offset + median gap, rounded to 15 min) and offer to re-run step 2 with it. If there are no DJI clips or no firm-time phone photos, say the check can't be done.
3. **Launcher.** `python tripmap/launcher.py "<folder>"` (it writes the launcher into the trip folder, next to the media, pointing at this repo).

## Step 5: Access (after the user's yes)
5. Run `python tripmap/access.py setup <slug> "<Title>" --dry-run` (add `--trip "<Trip>"` if `<Trip>` isn't the title minus its year). Show the user the plan verbatim and ask whether to apply it.
   - Only on an explicit yes: run the same command with `--yes` instead of `--dry-run`, and report its output, including the final `Access check:` line.
   - If it prints the token instructions (exit 2), pass them on and skip this step; it goes on the checklist instead.
   - `REFUSED` or `ERROR`: report it and stop; don't work around it.
   - Don't add crew members here; the user adds them with `access.py add`.

## Then STOP and give the user this checklist
Fill in the real `<Title>`, `<Trip>`, `<slug>` and media host. Take the wording from runbook steps 4–7:

- [ ] **Crew:** `python tripmap/access.py add <slug> <email>` for each person (`list <slug>` to check). If step 5 was skipped: `access.py setup <slug> "<Title>" --dry-run`, then without `--dry-run`.
- [ ] **4. Edit + full build:** start the trip folder's launcher → fix things → Apply to map → **Scan for new files**.
- [ ] **6. Publish** from the editor (it refuses until step 5 is done).
- [ ] **7. Check:** `curl -s -o /dev/null -w "%{http_code}\n" https://<media host>/<slug>/trip.json` → 302/401/403, never 200; then incognito sign-in test.
