# TripMap

Point it at a trip folder → get an interactive map of every photo and video, with day-by-day filtering, a timeline strip, a "play the trip" mode, and in-place viewing. Originals are only read, never changed.

## One-time setup (Windows)

```powershell
pip install pillow
winget install Gyan.FFmpeg        # then open a NEW terminal so ffmpeg is on PATH
exiftool -ver                     # you already have this
```

Keep `build.py` and `viewer.html` together in one folder, e.g. `D:\TripMap\`.

## Run it

**1. Quick look (thumbnails only, a few minutes):**

```powershell
python D:\TripMap\build.py "D:\2026_ Thailand Trip" --name "Thailand 2026" --quick
```

Check the line starting `clip CSV columns ->`. It should name the file, lat, lon and time columns from your `clip_locations.csv`. If it picked the wrong one, pass e.g. `--csv-time-col <name>`.

Then open `D:\2026_ Thailand Trip\_tripmap\index.html` by double-clicking it.

**2. Full build (adds 1600px photos + 720p video previews):** same command without `--quick`. It uses the camera's `.LRF` proxies as the source, so it doesn't decode the 4K files. Re-running skips anything already built, so you can stop and resume.

## Defaults tuned for this trip

| Option | Default | Meaning |
|---|---|---|
| `--tz` | `+07:00` | Zone for day boundaries and displayed times |
| `--camera-offset` | `+07:45` | DJI clock vs UTC, used only for clips the CSV has no time for |
| `--clip-locations` | `<input>\clip_locations.csv` | Your precomputed clip locations. Clips the CSV leaves blank stay off the map (shown in the strip with a `?`) |
| `--match-window` | `120` | Minutes. Anything else without GPS borrows the nearest geotagged shot within this window |
| `--contact` | none | Adds a "Request original" button, e.g. `--contact you@gmail.com` or `--contact https://wa.me/91XXXXXXXXXX` |

## Fixing locations and days (no terminal needed)

Double-click **`TripMap\Open TripMap.bat`**. A small window opens and your browser shows the map in edit mode. Keep that window open while you edit, and close it when you're done. The map is only reachable from your own computer.

- **Filter:** All / Needs review (estimated or unplaced) / No location.
- **Select:** click shots in the strip, Shift-click for a range, double-click to view one.
- **Location:** click the map, or an existing pin, to place the selected shots. Drag a pin to move one. "Remove location" takes shots off the map.
- **Day and time:** "Move to day…" moves the selected shots to another day and keeps their clock time. "Shift time" moves them by e.g. `-1:30` or `+2` hours, which is useful when a camera clock was off.
- **Undo:** Ctrl+Z.
- Every change saves straight to `overrides.json` in the trip folder. The previous version is kept as `overrides.bak.json`.
- **Apply to map** bakes your fixes into the map in a few seconds. Do it whenever you like, once at the end is fine.
- **Scan for new files** picks up photos or videos you've added anywhere in the trip folder and builds only their previews.
- **Backup** downloads a copy of your fixes. **Import** merges a fixes file, e.g. one exported earlier.

Without the helper (opening `index.html?edit` directly), fixes are kept in that browser. Use **Export overrides.json**, save it into the trip folder, then run the build with `--data-only`.

## Keeping it under R2's free 10 GB

The build prints the bundle size at the end. If it's too big, delete `_tripmap\media\*.mp4` and rebuild with `--crf 30` or `--video-height 540`.

## Publishing to R2 (the Wander site)

Click **Publish** in edit mode, or run `python TripMap\publish.py "D:\2026_ Thailand Trip"`. It uploads `_tripmap` to `r2:trip-media/<slug>/`. Thumbnails, gallery images and previews go first, cached for a week. The map data goes after, never cached, so fixes show up straight away. Last, it updates `trips.json`, the list of trips Wander shows on its home page. Only new or changed files are sent. Local settings files are never uploaded.

What the website reads:
- `https://media.job-joseph.com/trips.json` lists every trip: slug, title, dates, cover image and counts.
- `https://media.job-joseph.com/<slug>/trip.json` holds one trip: its days, plus items with time, day, location, and `thumb` / `card` / `media` paths relative to that folder.

## Next trip

Same command, different folder: `python build.py "D:\2027_ Vietnam" --name "Vietnam 2027" --tz +07:00`. Without a `clip_locations.csv`, it falls back to nearest-in-time matching automatically.
