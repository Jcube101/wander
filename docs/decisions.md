# Decisions

**D1 — Originals stay on the external disk; only previews go online.** 140 GB of originals is too much for cheap hosting and isn't needed for viewing. Bundle is ~2.5 GB per trip (thumbs 200px, cards 640px, photos 1600px, video 720p H.264). Friends request originals directly.

**D2 — Cloudflare R2 over S3.** Zero egress fees (video replays cost nothing), 10 GB free, same Cloudflare account as the domain, S3-compatible tooling (rclone).

**D3 — Lovable for the public site; local viewer kept as the editor.** Lovable gives the design and Job iterates there; the editing tools (bulk placement, day/time shifts) stay local where they can write files and run the builder. No credits spent on editor features.

**D4 — Location fixes as an overrides file, not EXIF edits.** Originals are never modified; `overrides.json` (keyed by relative path) is applied at build time. Manual fixes also act as anchors for nearest-in-time matching.

**D5 — Two subdomains total, trips as paths.** `wander.` (site) and `media.` (data). New trips are folders/routes, not subdomains.

**D6 — No database; Cloudflare Access is the source of truth for who sees what.** Per-trip rule groups + one Access app per trip. Free up to 50 users. Rejected: Clerk (would still need a Worker to protect media, plus auth code), Supabase (no free DBs left, and not needed).

**D7 — The lock is on `media.`, not `wander.`.** `wander` is a Lovable-hosted A record (185.158.133.1) on Lovable's own Cloudflare account; this zone's Workers and Access don't run for it (O2O only applies to CNAMEs). Tried proxying + Worker route: request bypassed the Worker. So: app shell is public, all trip data/media sits behind Access on `media.`. Sign-in uses a top-level `/auth/<slug>` hop; the Access cookie is same-site with wander, so `<img>`/`<video>` and credentialed fetches carry it.

**D8 — Worker serves an allow-list and refuses encoded paths.** Prevents Access/Worker path disagreements (e.g. `%2F`) and exposure of non-public files (`trip.js` has local paths).

**D9 — Esri tiles in the local viewer.** CARTO began requiring an API key.
