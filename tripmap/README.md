# TripMap

Point it at a trip folder → get an interactive map of every photo and video, with day-by-day filtering, a timeline strip, a "play the trip" mode, in-place viewing, a local editor for fixing locations/days/times, and one-click publishing to your Wander site. Originals are only read, never changed.

**The code runs from this repo.** A trip folder holds only its media, `overrides.json`, the built `_tripmap/`, and a one-file launcher. Change the code here and every trip picks it up.

Windows-tested; mac/Linux should work (the same Python, plus the `.sh` launcher). Commands below are run from the repo root; on mac/Linux use `python3` and `/` paths.

## One-time setup

Python 3.9+ with Pillow, plus exiftool, ffmpeg and (for publishing) rclone on your PATH:

| | Install |
|---|---|
| Windows | `pip install pillow` · `winget install Gyan.FFmpeg OliverBetz.ExifTool Rclone.Rclone` (then open a new terminal) |
| macOS | `pip3 install pillow` · `brew install ffmpeg exiftool rclone` |
| Debian/Ubuntu | `pip3 install pillow` · `sudo apt install ffmpeg libimage-exiftool-perl rclone` |

Publishing and Access also need the Wander config and an rclone remote for your bucket; see [SETUP.md](../SETUP.md). Building and editing don't.

## A new trip

1. **First build** (a quick look with thumbnails only, then the full build). `--tz` is the trip's UTC offset and is required:
   ```
   python tripmap/build.py "<trip folder>" --name "<Trip title>" --tz +01:00 --quick
   python tripmap/build.py "<trip folder>" --name "<Trip title>" --tz +01:00
   ```
   Check the line starting `clip CSV columns ->` if you use a `clip_locations.csv`. The full build makes 1600px photos and 720p video previews (from DJI `.LRF` proxies when present). Re-running skips anything already built, so you can stop and resume.
2. **Add the launcher:** `python tripmap/launcher.py "<trip folder>"` writes `Open Wander Editor.bat` (Windows) or `open-wander-editor.sh` (mac/Linux; `--sh`/`--bat` to choose) into the trip folder, pointing at this repo. If you move the repo, run it again with `--force`.
3. **Access before Publish:** `python tripmap/access.py setup <slug> "<Trip title>" --dry-run`, check the plan, then run it again without `--dry-run`. Add people with `python tripmap/access.py add <slug> <email>` (see [RUNBOOK.md](../RUNBOOK.md)).
4. Start the launcher, fix things, **Apply to map**, **Publish** (it refuses until step 3 is done).

## Options

| Option | Default | Meaning |
|---|---|---|
| `--name` | folder name | Trip title; also gives the web slug (`Lisbon 2025` → `lisbon-2025`) |
| `--slug` | from `--name` | Override the web name |
| `--tz` | **required** | The trip's UTC offset: day boundaries and displayed times. Negative offsets work as `--tz -05:00` |
| `--camera-offset` | `+00:00` | DJI clock vs UTC, for clips whose time comes from the filename |
| `--clip-locations` | `<trip>/clip_locations.csv` | Precomputed clip locations (optional) |
| `--match-window` | `120` | Minutes; shots without GPS borrow the nearest geotagged shot within this |
| `--quick` | off | Thumbnails only |
| `--data-only` | off | Rewrite map data only (what **Apply to map** runs) |
| `--contact` | `defaults.contact` in the config, else none | Adds "Request original" in the local viewer |

The build remembers its options (always including `--tz` and `--camera-offset`) in `_tripmap/build_args.json`, so the editor's buttons re-run it the same way.

## Editing (no terminal needed)

Double-click **`Open Wander Editor.bat`** in the trip folder (mac/Linux: run `open-wander-editor.sh`). A small window opens and your browser shows the map in edit mode at `http://127.0.0.1:8765/index.html?edit`. Keep the window open while you edit. The page is reachable only from your own computer.

The toolbar under the map has the filters on the left; on the right, the save status, **Apply to map**, **Publish**, a **⋯** menu (Scan for new files, Import, Backup, Automatic cover, Select all in view, Follow selection) and **?** (hints and shortcuts). Selecting shots brings up a selection bar over the bottom of the map with only the actions that apply to them.

- **Filter:** All / Needs review (estimated or unplaced) / No location (n) / Archived (n).
- **Select:** click shots in the strip, Shift-click for a range, double-click to view. Esc clears.
- **Where did this happen?** Selecting a placed shot zooms to its pin and highlights it. Selecting an unplaced one shows the nearest placed shots before and after it (same day preferred), with the time gap on each ("−12 min", "+40 min") and a dashed line between them; the selection bar says "Between … and …", and mentions it when a neighbour is on another day. With several shots selected, the earliest one's previous and the latest one's next neighbour count. Turn off **Follow selection** (⋯ menu, remembered in this browser) to keep the map still; it never moves while you're dragging it.
- **Location:** **Place at previous** / **Place at next** (`[` / `]`) copy that neighbour's location onto the selection. Or click the map or a pin to place the selection; drag a pin to move one; "Remove location" takes shots off the map.
- **Day and time:** "Move to day…" (keeps the clock time) or "Shift time" (e.g. `-1:30`, `+2`).
- **Set as cover** (exactly one published photo) / **Automatic cover** (⋯ menu): the trip's landing card and hero. ★ marks it in the strip.
- **Archive / Restore** (A / Shift+A): hide shots from the published trip. They stay here, dimmed, and their previews are removed from R2 on the next Publish.
- **Undo:** Ctrl+Z, or the Undo button (in the selection bar, or the toolbar when nothing is selected).
- Every change saves to `overrides.json` in the trip folder (previous version: `overrides.bak.json`).
- **Apply to map:** bakes fixes into the map in seconds.
- **Scan for new files** (⋯): builds previews for anything added to the trip folder.
- **Publish:** uploads to R2 (see below).
- **Backup / Import** (⋯): download or merge a fixes file.

## Publishing

**Publish** (or `python tripmap/publish.py "<trip folder>"`) uploads `_tripmap` to `<remote>:<bucket>/<slug>/` from your config:
1. Thumbnails, gallery images and previews that `trip.json` uses, cached for a week. Only new or changed files are sent.
2. `trip.json`, never cached.
3. Previews the trip no longer uses (archived shots) are deleted from R2. It stops before changing anything if that's over 20% of the trip (`--allow-mass-delete` to override).
4. Covers to `public/covers/`, and this trip merged into `trips.json`.

Add `--dry-run` to see the plan without changing anything. Only files `trip.json` references are uploaded, so `trip.js` and `index.html` (local editor files; `trip.js` holds folder paths) and archived shots never leave the disk. Data format: `SPEC.md` → Data contract.

## Size

The build prints the bundle size (about 2.5 GB for ~1,000 shots). R2's free tier is 10 GB. To shrink it, delete `_tripmap/media/*.mp4` and rebuild with `--crf 30` or `--video-height 540`.
