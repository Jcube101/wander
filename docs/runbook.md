# Runbook

## Everyday
| Task | How |
|---|---|
| Fix locations / day / time | Double-click `Open Wander Editor.bat` in the trip folder → edit (filters, select, click map, Move to day, Shift time) → **Apply to map** → **Publish** |
| Add photos/videos | Drop anywhere in the trip folder → **Scan for new files** → **Publish** |
| Hide a shot | Select → **Archive** (A) → **Apply to map** → **Publish**. Undo: **Archived** filter → select → **Restore** (Shift+A) → Apply → Publish |
| Check a publish first | `python "C:\Users\jobjo\Github\wander\tripmap\publish.py" "D:\<trip>" --dry-run` → upload count + delete list, nothing changed |
| Give someone access | Zero Trust → Access → Rule groups → add their email to the trip's crew (or `Wander – All trips`) |
| Remove someone | Delete their email from the group; optionally Zero Trust → Users → revoke session |
| Change the site design | Lovable prompt → re-publish in Lovable |
| Change the editor/builder | Edit in the repo → `viewer.html`: refresh the editor page · `build.py`/`publish.py`: used on the next Apply/Scan/Publish · `serve.py`: restart the launcher window → commit to main. CI runs the tests on every push; check with `gh run list --limit 1` |
| Change the Worker | `cd worker && npm test && npx wrangler deploy` |

## New trip
The Access app must exist **before** Publish; Access is the only gate. In Claude Code, `/new-trip` runs steps 1–3 and hands you a checklist for 4–7.

`<Title>` e.g. `Bali 2027` → `<slug>` `bali-2027`; `<Trip>` = short name, e.g. `Bali`.

1. **Preflight**
   - `python`, `exiftool`, `ffmpeg`, `rclone` all on PATH; `python -c "import PIL"` works.
   - Slug is new: `rclone cat r2:trip-media/trips.json --s3-no-check-bucket` must not list `<slug>` (unless you mean to republish it).
2. **Quick build**
   `python "C:\Users\jobjo\Github\wander\tripmap\build.py" "D:\<trip>" --name "<Title>" --tz +HH:MM --quick` (add `--camera-offset +HH:MM` for a DJI clock).
   Check: item count, how many have no location, `build_errors.txt`, DJI clips found, and whether the camera offset looks right (DJI clip times vs nearby phone photo times). Wrong offset → re-run with a corrected `--camera-offset`. The options are saved in `_tripmap\build_args.json`, so the editor's Scan reuses them.
3. **Launcher:** copy `tripmap\Open Wander Editor.bat` into the trip folder.
4. **Edit + full build:** double-click the launcher → fix things → **Apply to map** → **Scan for new files** (the full build; can take hours).
5. **Access** (Zero Trust):
   - Rule group `Wander – <Trip> crew` with the crew's emails.
   - Self-hosted app `Wander – <Title>`, destinations `media.job-joseph.com/<slug>` and `media.job-joseph.com/auth/<slug>`.
   - Allow policy `Wander – <Trip> viewers` = `Wander – <Trip> crew` OR `Wander – All trips`.
   - One-time PIN login; App Launcher off.
6. **Publish** from the editor. `publish.py` refuses if step 5 is missing.
7. **Check**
   - `curl -sI https://media.job-joseph.com/<slug>/trip.json` → 302/401/403. **Never 200.**
   - Incognito: lock on the landing card → Sign in → photos load.

## Setup facts
- Bucket `trip-media` (R2), no public domain. rclone remote `r2` (key = Object Read & Write, this bucket only).
- Worker `wander-media`, custom domain `media.job-joseph.com`.
- `wander.job-joseph.com`: A 185.158.133.1, **DNS only** (Lovable). Don't proxy it — it doesn't help (see decisions).
- Zero Trust team `yellow-night-d03a`. Rule groups: `Wander – All trips`, `Wander – Thailand crew`. App `Wander – Thailand 2026`, policy `Wander – Thailand viewers`.

## Archive notes
- Archived shots' previews are deleted from R2 on Publish, but a signed-in viewer's browser may keep cached copies for up to a week (`private, max-age=604800`).
- First publish after the archive change (or any time in doubt): run `--dry-run` and check the delete list.
- Publish stops if it would remove > 20% of the trip's files. If that's really intended, run `publish.py ... --allow-mass-delete` from a terminal.

## Troubleshooting
- **Publish: "isn't protected by Cloudflare Access"** → create the trip's Access app (New trip, step 5), or fix its destinations. `--allow-unprotected` skips the check (terminal only).
- **Publish: "would remove N of M files"** → the mass-delete guard. Check the Archived filter; `--dry-run` lists the files.
- **Publish: "files trip.json references are missing"** → previews not built yet; run **Scan for new files**.
- **Publish: "WARNING: R2 storage …"** → the bucket is projected over 8 GB (or over the 10 GB free tier, which costs a few cents/GB/month). The publish still ran. Free space by archiving shots you don't need, or rebuild a trip's previews smaller: add `--crf 30` and/or `--video-height 540` to the build options (in `_tripmap\build_args.json` for the editor's Scan), delete that trip's `_tripmap\media\*.mp4` so they're rebuilt, Scan, then Publish. `--dry-run` shows the projected size first.
- **Publish: "couldn't check R2 storage"** → only the size check failed; the publish carried on. Retry later.
- **Publish: `CreateBucket ... 403`** → an rclone call is missing `--s3-no-check-bucket`.
- **Site shows "This trip is private" for someone who should see it** → check their exact email in the rule group; ask them to sign out (`media.job-joseph.com/cdn-cgi/access/logout`) and back in.
- **Images missing but trip loads** → something added `crossorigin` to `<img>`/`<video>` in the site.
- **Video won't seek** → Worker Range handling; test with `curl -H "Range: bytes=0-99" -I <url>` while signed in.
