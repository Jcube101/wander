# Runbook

## Everyday
| Task | How |
|---|---|
| Fix locations / day / time | Double-click `Open Wander Editor.bat` in the trip folder → edit (filters, select, click map, Move to day, Shift time) → **Apply to map** → **Publish** |
| Add photos/videos | Drop anywhere in the trip folder → **Scan for new files** → **Publish** |
| Give someone access | Zero Trust → Access → Rule groups → add their email to the trip's crew (or `Wander – All trips`) |
| Remove someone | Delete their email from the group; optionally Zero Trust → Users → revoke session |
| Change the site design | Lovable prompt → re-publish in Lovable |
| Change the editor/builder | Edit in the repo → refresh the editor page (restart the launcher window if `serve.py` changed) → commit/PR |
| Change the Worker | `cd worker && npm test && npx wrangler deploy` |

## New trip
1. `python "C:\Users\jobjo\Github\wander\tripmap\build.py" "D:\<trip>" --name "<Title>" --tz +HH:MM` (add `--camera-offset` if a DJI clock is off; `--quick` first for a fast look).
2. Copy `tripmap\Open Wander Editor.bat` into the trip folder.
3. Fix things in edit mode → Apply to map → **Publish** (creates `<slug>/`, updates `trips.json` + cover).
4. Zero Trust: create rule group `Wander – <Trip> crew`; add self-hosted app `Wander – <Trip>` with destinations `media.job-joseph.com/<slug>` and `media.job-joseph.com/auth/<slug>`; Allow policy = crew OR All trips; One-time PIN; App Launcher off.
5. Incognito test: lock on the landing card → Sign in → photos load.

## Setup facts
- Bucket `trip-media` (R2), no public domain. rclone remote `r2` (key = Object Read & Write, this bucket only).
- Worker `wander-media`, custom domain `media.job-joseph.com`.
- `wander.job-joseph.com`: A 185.158.133.1, **DNS only** (Lovable). Don't proxy it — it doesn't help (see decisions).
- Zero Trust team `yellow-night-d03a`. Rule groups: `Wander – All trips`, `Wander – Thailand crew`. App `Wander – Thailand 2026`, policy `Wander – Thailand viewers`.

## Troubleshooting
- **Publish: `CreateBucket ... 403`** → an rclone call is missing `--s3-no-check-bucket`.
- **Site shows "This trip is private" for someone who should see it** → check their exact email in the rule group; ask them to sign out (`media.job-joseph.com/cdn-cgi/access/logout`) and back in.
- **Images missing but trip loads** → something added `crossorigin` to `<img>`/`<video>` in the site.
- **Video won't seek** → Worker Range handling; test with `curl -H "Range: bytes=0-99" -I <url>` while signed in.
