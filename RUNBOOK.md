# Runbook

How to do things once Wander is set up ([SETUP.md](SETUP.md)). Commands run from the repo root (mac/Linux: `python3`). `<media host>`, `<remote>` and `<bucket>` are the values in your config; `python tripmap/config.py` prints them.

## Everyday
| Task | How |
|---|---|
| Fix locations / day / time | Start the trip folder's launcher → edit (filters, select, click map, Move to day, Shift time) → **Apply to map** → **Publish** |
| Place an unplaced shot | **No location** filter → select it → the map shows the nearest placed shots before and after it, with time gaps → **Place at previous** (`[`) / **Place at next** (`]`), or click the map → **Apply to map** → **Publish** |
| Add photos/videos | Drop anywhere in the trip folder → ⋯ → **Scan for new files** → **Publish** |
| Change cover | Select one photo → **Set as cover** → **Apply to map** → **Publish**. Back to the automatic pick: ⋯ → **Automatic cover** → Apply → Publish |
| Hide a shot | Select → **Archive** (A) → **Apply to map** → **Publish**. Undo: **Archived** filter → select → **Restore** (Shift+A) → Apply → Publish |
| Check a publish first | `python tripmap/publish.py "<trip folder>" --dry-run` → upload count + delete list, nothing changed |
| Give someone access | `python tripmap/access.py add <slug> <email>` (or `add all <email>` for the all-trips group). Check with `list <slug>`. Fallback: Zero Trust → Access → Rule groups → add the email |
| Remove someone | `python tripmap/access.py remove <slug> <email>` (asks y/N); add `--revoke` to end their live sessions now (all apps; they can sign back in to trips they're still allowed). Fallback: delete the email from the group; Zero Trust → Users → revoke session. Their favourites file stays (unreachable without access); wipe it if you like ([Favourites](#favourites)) |
| Wipe someone's favourites | [Favourites](#favourites) |
| Change the site | Reference viewer: edit `site/public/`, then `npx wrangler pages deploy site/public --project-name <name>` ([site/README.md](site/README.md)). A builder like Lovable: prompt, then re-publish it there (edits only reach the live domain after publishing) |
| Change the editor/builder | Edit in the repo → `viewer.html`: refresh the editor page · `build.py`/`publish.py`: used on the next Apply/Scan/Publish · `serve.py`: restart the launcher → run the tests ([CONTRIBUTING.md](CONTRIBUTING.md#run-the-tests)) |
| Change the Worker | `cd worker && npm test && npx wrangler deploy`, then the checks under [Worker deploys](#worker-deploys) |
| Move the repo | Re-run `python tripmap/launcher.py "<trip folder>" --force` for each trip, so its launcher points at the new place |

## New trip
The Access app must exist **before** Publish; Access is the only gate. In Claude Code, `/new-trip` runs steps 1–3, shows you the step 5 Access plan and applies it once you say yes, then hands you a checklist for the rest. It never publishes.

`<Title>` e.g. `Bali 2027` → `<slug>` `bali-2027`; `<Trip>` = short name, e.g. `Bali`.

1. **Preflight**
   - `python`, `exiftool`, `ffmpeg`, `rclone` all on PATH; `python -c "import PIL"` works; `python tripmap/config.py` shows your config.
   - Slug is new: `rclone cat <remote>:<bucket>/trips.json --s3-no-check-bucket` must not list `<slug>` (unless you mean to republish it).
2. **Quick build**
   `python tripmap/build.py "<trip folder>" --name "<Title>" --tz +HH:MM --quick` (`--tz` is required; add `--camera-offset +HH:MM` for a DJI clock, default `+00:00`).
   Check: item count, how many have no location, `build_errors.txt`, DJI clips found, and whether the camera offset looks right (DJI clip times vs nearby phone photo times). Wrong offset → re-run with a corrected `--camera-offset`. The options are saved in `_tripmap/build_args.json`, so the editor's Scan reuses them.
3. **Launcher:** `python tripmap/launcher.py "<trip folder>"` puts `Open Wander Editor.bat` (Windows) or `open-wander-editor.sh` (mac/Linux) in the trip folder, pointing at this repo.
4. **Edit + full build:** start the launcher → fix things → **Apply to map** → **Scan for new files** (the full build; can take hours).
5. **Access:** `python tripmap/access.py setup <slug> "<Title>" --dry-run` → check the plan → run it again without `--dry-run` (asks y/N). It creates:
   - Rule group `<prefix> – <Trip> crew` (empty: holds `nobody@wander.invalid` until you add people).
   - Allow policy `<prefix> – <Trip> viewers` = `<prefix> – <Trip> crew` OR `<prefix> – All trips` (session from `access.policySession`).
   - Self-hosted app `<prefix> – <Title>`, destinations `<media host>/<slug>` and `<media host>/auth/<slug>`; One-time PIN only; App Launcher hidden; session from `access.appSession`.

   It ends with the app's AUD tag and the publish guard's check (`302/401/403` = protected). Then `access.py add <slug> <email>` for each crew member. `--trip <Name>` overrides `<Trip>`. Needs the API token ([SETUP.md step 6](SETUP.md#6-cloudflare-access)); without it, `access.py` prints how to make one. Fallback: create the same three by hand in Zero Trust.

   **Favourites** (if you use them): add the line `setup` printed, `"<slug>" = "<AUD tag>"`, to `ACCESS_AUD` in `worker/wrangler.toml` (`access.py list <slug>` shows the AUD again), then deploy the Worker and run the [checks](#worker-deploys). Until then the trip works, but its hearts are hidden (`/<slug>/favorites` answers 500).
6. **Publish** from the editor. `publish.py` refuses if step 5 is missing.
7. **Check**
   - `curl -s -o /dev/null -w "%{http_code}\n" https://<media host>/<slug>/trip.json` → 302/401/403. **Never 200.**
   - Incognito: lock on the landing card → Sign in → photos load.

## Worker deploys
Right after `npx wrangler deploy`, check (and if any check fails, run `npx wrangler rollback` first, then investigate):
- `https://<media host>/trips.json` → 200 (once a trip is published).
- `https://<media host>/<slug>/trip.json` without cookies → 302/401/403.
- `https://<media host>/<slug>/favorites` without cookies → 302/401/403, for a GET and for `curl -X POST -H "Origin: <site origin>" -H "Content-Type: text/plain" --data '{"id":"x","fav":true}' …`.
- `https://<media host>/favs/<slug>/0000.json` → 404.
- A cover listed in `trips.json` (`public/covers/…`) → 200.
- `curl -sI -H "Origin: <site origin>" https://<media host>/trips.json` shows `access-control-allow-origin: <site origin>` and `access-control-allow-credentials: true`.
- Signed-in favourites can't be checked from a terminal: in a browser, sign in to a trip, heart a shot, reload (still hearted), un-heart it.

## Favourites
Each signed-in visitor can heart shots in a trip; the Worker keeps one file per person per trip in the bucket ([SPEC.md → Favourites](SPEC.md#favourites)):

- **Where:** `favs/<slug>/<sha256(salt + lowercase email)>.json`, holding `{"version":1,"ids":[…],"updated":…}`. No email in it. The salt is the Worker secret `FAVS_SALT`; Cloudflare never shows a secret again, so keep your own copy in `~/.wander/favs-salt` (outside the repo; never paste it anywhere).
- **Never served, never published over:** the Worker answers 404 for any `favs/…` path, and `publish.py` only ever deletes inside `<slug>/thumbs|cards|media/`.
- **Archived shots** drop out of everyone's favourites (a GET leaves them out; the person's next change prunes them).
- **Wipe one person's favourites in a trip** (e.g. after removing them). The file name from their email:
  ```
  python -c "import hashlib,pathlib,sys; s=(pathlib.Path.home()/'.wander'/'favs-salt').read_text().strip(); print(hashlib.sha256((s+sys.argv[1].lower()).encode()).hexdigest())" friend@example.com
  rclone deletefile <remote>:<bucket>/favs/<slug>/<that hash>.json --s3-no-check-bucket
  ```
  Every trip of theirs: `rclone lsf <remote>:<bucket>/favs --s3-no-check-bucket -R --include "*/<that hash>.json"`, then `deletefile` each.
- **Wipe a whole trip's favourites:** `rclone purge <remote>:<bucket>/favs/<slug> --s3-no-check-bucket`.
- **First-time setup** (or a lost salt): [SETUP.md → Favourites](SETUP.md#9-favourites-optional). A new salt orphans every existing file (nobody's favourites are found any more); purge `favs/` afterwards.

## Archive notes
- Archived shots' previews are deleted from R2 on Publish, but a signed-in viewer's browser may keep cached copies for up to a week (`private, max-age=604800`).
- First publish after archiving (or any time in doubt): run `--dry-run` and check the delete list.
- Publish stops if it would remove > 20% of the trip's files. If that's really intended, run `publish.py ... --allow-mass-delete` from a terminal.

## Troubleshooting
- **"No Wander config found"** → create `~/.wander/config.json` from `wander.config.example.json` ([SETUP.md step 2](SETUP.md#2-your-config)). Building and editing work without one; publishing and Access don't.
- **Build: "the following arguments are required: --tz"** → every build needs the trip's UTC offset. For a trip built before `--tz` was required, add `"--tz", "+HH:MM"` (and the `--camera-offset` it used) to `_tripmap/build_args.json` so the editor's buttons work again.
- **Launcher: "Could not find serve.py"** → the repo moved; re-run `python tripmap/launcher.py "<trip folder>" --force`.
- **Publish: "isn't protected by Cloudflare Access"** → create the trip's Access app (New trip, step 5), or fix its destinations. `--allow-unprotected` skips the check (terminal only).
- **Publish: "would remove N of M files"** → the mass-delete guard. Check the Archived filter; `--dry-run` lists the files.
- **Publish: "files trip.json references are missing"** → previews not built yet; run **Scan for new files**.
- **Publish: "WARNING: R2 storage …"** → the bucket is projected over 8 GB (or over the 10 GB free tier, which costs a few cents/GB/month). The publish still ran. Free space by archiving shots you don't need, or rebuild a trip's previews smaller: add `--crf 30` and/or `--video-height 540` to the build options (in `_tripmap/build_args.json` for the editor's Scan), delete that trip's `_tripmap/media/*.mp4` so they're rebuilt, Scan, then Publish. `--dry-run` shows the projected size first.
- **Publish: "couldn't check R2 storage"** → only the size check failed; the publish carried on. Retry later.
- **Publish: `CreateBucket ... 403`** → an rclone call is missing `--s3-no-check-bucket`.
- **`access.py`: "REFUSED: …"** → a group holds something other than emails, or a policy something other than rule groups with Allow (e.g. Everyone, a service token, an IP range, Bypass). Fix it in the dashboard; the script won't write around it.
- **`access.py`: "several Access apps cover <slug>"** → two apps share a destination; delete or fix one in the dashboard (the script never deletes).
- **`access.py`: "rule group '… – All trips' not found"** → create it in Zero Trust ([SETUP.md step 6](SETUP.md#6-cloudflare-access)), named with your `access.prefix` and an en dash.
- **Site shows "This trip is private" for someone who should see it** → `access.py list <slug>` and check their exact email; ask them to sign out (`https://<media host>/cdn-cgi/access/logout`) and back in.
- **Site can't load trips at all** → its origin isn't in the Worker's `SITE_ORIGINS` (check `access-control-allow-origin`, see [Worker deploys](#worker-deploys)), or it's on a different registrable domain than the media host.
- **Images missing but trip loads** → something added `crossorigin` to `<img>`/`<video>` in the site.
- **No hearts on a trip** → `curl -s https://<media host>/<slug>/favorites` while signed in shows why: "Not configured…" (500) means the trip isn't in `ACCESS_AUD`, or `ACCESS_TEAM_DOMAIN`/`FAVS_SALT` is missing (New trip, step 5 → Favourites).
- **Hearts always say "sign in again"** although the trip loads → the Worker rejects the Access token (401). Check the trip's line in `ACCESS_AUD` against `access.py list <slug>` (AUD tag) and `ACCESS_TEAM_DOMAIN` against your Zero Trust team domain; redeploy.
- **Favourites POST fails before reaching the Worker** → the site sent `Content-Type: application/json` or a custom header, which needs a CORS preflight that Access refuses (LEARNINGS). Send `text/plain`.
- **Video won't seek** → Worker Range handling; test with `curl -H "Range: bytes=0-99" -I <url>` while signed in.
