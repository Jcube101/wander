# TripMap

Point it at a trip folder → get an interactive map of every photo and video, with day-by-day filtering, a timeline strip, a "play the trip" mode, in-place viewing, a local editor for fixing locations/days/times, and one-click publishing to the Wander site. Originals are only read, never changed.

**The code runs from this repo.** A trip folder holds only its media, `overrides.json`, the built `_tripmap\`, and a one-file launcher. Change the code here and every trip picks it up.

## One-time setup (Windows)

```powershell
pip install pillow
winget install Gyan.FFmpeg OliverBetz.ExifTool Rclone.Rclone   # then open a NEW terminal
rclone config create r2 s3 provider=Cloudflare access_key_id="KEY" secret_access_key="SECRET" endpoint="ENDPOINT" acl=private
```

In PowerShell, set this once per window: `$W = "C:\Users\jobjo\Github\wander\tripmap"`

## A new trip

1. **First build** (a quick look with thumbnails only, then the full build):
   ```powershell
   python "$W\build.py" "D:\<trip>" --name "<Trip title>" --tz +07:00 --quick
   python "$W\build.py" "D:\<trip>" --name "<Trip title>" --tz +07:00
   ```
   Check the line starting `clip CSV columns ->` if you use a `clip_locations.csv`. The full build makes 1600px photos and 720p video previews (from DJI `.LRF` proxies when present). Re-running skips anything already built, so you can stop and resume.
2. **Add the launcher:** copy `Open Wander Editor.bat` from this folder into the trip folder (next to the photos, not inside `_tripmap`). If the repo isn't at `C:\Users\jobjo\Github\wander`, edit the `WANDER=` line in it.
3. **Access before Publish:** `python "$W\access.py" setup <slug> "<Trip title>" --dry-run`, check the plan, then run it again without `--dry-run`. Add people with `python "$W\access.py" add <slug> <email>` (see `docs/runbook.md`).
4. Double-click the launcher, fix things, **Apply to map**, **Publish** (it refuses until step 3 is done).

## Options

| Option | Default | Meaning |
|---|---|---|
| `--name` | folder name | Trip title; also gives the web slug (`Thailand 2026` → `thailand-2026`) |
| `--slug` | from `--name` | Override the web name |
| `--tz` | `+07:00` | Zone for day boundaries and displayed times |
| `--camera-offset` | `+07:45` | DJI clock vs UTC, for clips whose time comes from the filename |
| `--clip-locations` | `<trip>\clip_locations.csv` | Precomputed clip locations (optional) |
| `--match-window` | `120` | Minutes; shots without GPS borrow the nearest geotagged shot within this |
| `--quick` | off | Thumbnails only |
| `--data-only` | off | Rewrite map data only (what **Apply to map** runs) |
| `--contact` | none | Adds "Request original" in the local viewer |

The build remembers its options in `_tripmap\build_args.json`, so the editor's buttons re-run it the same way.

## Editing (no terminal needed)

Double-click **`Open Wander Editor.bat`** in the trip folder. A small window opens and your browser shows the map in edit mode at `http://127.0.0.1:8765/index.html?edit`. Keep the window open while you edit. The page is reachable only from your own computer.

- **Filter:** All / Needs review (estimated or unplaced) / No location / Archived.
- **Set as cover** (one photo selected) / **Automatic cover**: the trip's landing card and hero. ★ marks it in the strip.
- **Archive / Restore** (A / Shift+A): hide shots from the published trip. They stay here, dimmed, and their previews are removed from R2 on the next Publish.
- **Select:** click shots in the strip, Shift-click for a range, double-click to view.
- **Location:** click the map or a pin to place the selection; drag a pin to move one; "Remove location" takes shots off the map.
- **Day and time:** "Move to day…" (keeps the clock time) or "Shift time" (e.g. `-1:30`, `+2`).
- **Undo:** Ctrl+Z.
- Every change saves to `overrides.json` in the trip folder (previous version: `overrides.bak.json`).
- **Apply to map:** bakes fixes into the map in seconds.
- **Scan for new files:** builds previews for anything added to the trip folder.
- **Publish:** uploads to R2 (see below).
- **Backup / Import:** download or merge a fixes file.

## Publishing

**Publish** (or `python "$W\publish.py" "D:\<trip>"`) uploads `_tripmap` to `r2:trip-media/<slug>/`:
1. Thumbnails, gallery images and previews that `trip.json` uses, cached for a week. Only new or changed files are sent.
2. `trip.json`, never cached.
3. Previews the trip no longer uses (archived shots) are deleted from R2. It stops before changing anything if that's over 20% of the trip (`--allow-mass-delete` to override).
4. Covers to `public/covers/`, and this trip merged into `trips.json`.

Add `--dry-run` to see the plan without changing anything. Only files `trip.json` references are uploaded, so `trip.js` and `index.html` (local editor files; `trip.js` holds folder paths) and archived shots never leave the disk. Data format: `docs/data-contract.md`.

## Size

The build prints the bundle size (about 2.5 GB for ~1,000 shots). R2's free tier is 10 GB. To shrink it, delete `_tripmap\media\*.mp4` and rebuild with `--crf 30` or `--video-height 540`.
