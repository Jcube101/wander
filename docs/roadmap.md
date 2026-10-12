# Roadmap

## Done
- [x] Builder: metadata, DJI/phone/WhatsApp time handling, CSV + nearest-shot location, previews, gallery cards, incremental builds
- [x] Local editor: filters, multi-select placement, drag, move-to-day, shift-time, undo, autosave to overrides.json
- [x] One-click Apply / Scan / Publish via local helper
- [x] R2 bucket + Publish (safe ordering, cache headers, trips.json, public covers)
- [x] Wander site (Lovable): landing + trip pages, gallery, map, timeline, viewer, play journey
- [x] Private per-trip access: Worker on media., Cloudflare Access apps, sign-in flow, lock badges, signed-in indicator

## Next
- [ ] pytest suite for build.py (fixture trip folder + stubbed exiftool/ffmpeg) and publish.py (stubbed rclone)
- [ ] Script Access setup via Cloudflare API (create crew group + app when a new trip is published; add/remove emails by command)
- [ ] Choose cover photo in edit mode
- [ ] Reverse-geocode place names (city/landmark) into trip.json; show in captions and day chips
- [ ] Duplicate detection (perceptual hash)
- [ ] Optional: original-file request flow (temporary signed links)
