# Data contract (tripmap → website)

Base: `https://media.job-joseph.com`. All paths below are relative to it unless noted.

## `trips.json` (public)
```json
{
  "version": 1,
  "trips": [{
    "slug": "thailand-2026",
    "title": "Thailand 2026",
    "start": "2026-09-29", "end": "2026-10-10", "days": 12,
    "cover": "public/covers/thailand-2026-card.jpg?v=3f9a1c07be",
    "coverImage": "public/covers/thailand-2026.jpg?v=8d21e4a0c5",
    "counts": { "items": 1034, "photos": 545, "videos": 489, "onMap": 882 },
    "data": "thailand-2026/trip.json",
    "updated": "2026-10-12T19:25:06+00:00"
  }]
}
```
Sorted newest trip first. `cover` ≤640px, `coverImage` 1600px (falls back to `cover`). Both may end in `?v=<hash>` (changes when the cover image changes); use the value as-is.

## `<slug>/trip.json` (protected by Access)
```json
{
  "version": 1, "title": "...", "slug": "...", "generated": "ISO time",
  "tzOffsetMin": 420,
  "start": "YYYY-MM-DD", "end": "YYYY-MM-DD",
  "cover": "cards/<id>.jpg",
  "counts": { "items": 0, "photos": 0, "videos": 0, "onMap": 0 },
  "days": [{ "key": "YYYY-MM-DD", "n": 1, "count": 3 }],
  "items": [{
    "id": "12-hex", "type": "photo|video",
    "t": 1790632024, "day": "YYYY-MM-DD", "dayN": 1,
    "lat": 13.7, "lon": 100.5,
    "loc": "gps|csv|matched|manual|cleared",
    "conf": "high|medium|low",
    "dur": 12.0, "orig": "DJI_2026...MP4",
    "thumb": "thumbs/<id>.jpg", "card": "cards/<id>.jpg", "ar": 1.778,
    "media": "media/<id>.jpg|mp4"
  }]
}
```
- Item paths are relative to `<slug>/`.
- `lat`/`lon` may be absent (unplaced shot). `loc` is an internal *source code*, never a place name — don't display it. `cleared` = deliberately unplaced (no `lat`/`lon`).
- `t` is unix seconds; show times using `tzOffsetMin` (the trip's zone), never the viewer's.
- `day`/`dayN` are computed in the trip zone; `days[].n` counts from the first day (gaps keep their numbers).

## Worker endpoints
- `GET /me` → `{ "email": string|null }` (from the Access cookie; display only).
- `GET /auth/<slug>?return=<url>` → behind the trip's Access app; 302 to `return` if it's an https `*.job-joseph.com` URL, else to `https://wander.job-joseph.com/<slug>`.
- Logout: `/cdn-cgi/access/logout` (Cloudflare).

## Client rules
- `fetch(..., { credentials: 'include' })` for everything on the media host.
- No `crossorigin` attribute on `<img>`/`<video>` (it would drop the cookie).
- Never persist trip data in browser storage.
