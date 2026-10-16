# Wander

Private, per-trip travel archive. Photos and videos stay on my hard disk; small previews live in a private Cloudflare R2 bucket; friends sign in with their email to see only the trips they were on.

- **Site:** https://wander.job-joseph.com — front end lives in the Lovable-synced repo [`travelogue-map-memory`](https://github.com/Jcube101/travelogue-map-memory)
- **Media:** https://media.job-joseph.com — served by the Worker in `worker/`, gated per trip by Cloudflare Access

## What's here

| Folder | What it is |
|---|---|
| `tripmap/` | Local builder + editor. Reads a trip folder (EXIF, DJI clips, phone photos), builds thumbnails / gallery images / 720p previews, a local map editor for fixing locations, days and times, and a Publish step to R2. |
| `worker/` | Cloudflare Worker `wander-media` on `media.job-joseph.com`: serves an allow-list of files from the private bucket, Range requests for video, CORS for the site, `/auth/<slug>` sign-in hop, `/me`. |
| `docs/` | Architecture, runbook, data contract, decisions, known issues. |

## Quick start

```powershell
# one-time
pip install pillow
winget install Gyan.FFmpeg OliverBetz.ExifTool Rclone.Rclone

# per trip (code always runs from this repo)
$W = "C:\Users\jobjo\Github\wander\tripmap"
python "$W\build.py" "D:\<trip>" --name "<Trip title>"
copy "$W\Open Wander Editor.bat" "D:\<trip>\"
# edit + publish
double-click D:\<trip>\Open Wander Editor.bat
```

Worker: `cd worker && npm test && npx wrangler deploy`

Project docs: [`SPEC.md`](SPEC.md) (what it must do), [`ROADMAP.md`](ROADMAP.md), [`LEARNINGS.md`](LEARNINGS.md) (gotchas).

See [`docs/runbook.md`](docs/runbook.md) for the full routine and [`docs/architecture.md`](docs/architecture.md) for how the pieces fit.
