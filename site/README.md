# Reference viewer

A small static site for your Wander trips: a landing page of trips with covers and lock badges, and per trip a map, day-by-day filter, gallery and photo/video viewer, with the sign-in flow. Signed-in visitors can heart shots and filter to their favourites, when the Worker has favourites set up ([SETUP.md step 9](../SETUP.md#9-favourites-optional)); otherwise there are no hearts. The viewer's **Download** saves a shot named by when it was taken (on phones through the share sheet, so it can go to Photos); on a computer, the favourites in view download as one ZIP (up to 500 MB; pick a day for more). It reads only `trips.json` and `<slug>/trip.json` from your media host ([data contract](../SPEC.md#data-contract--build-your-own-site)), so you don't need Lovable or any build step. Plain HTML, CSS and JS modules; Leaflet for the map (the same tiles and photo pins as the local editor).

| File (in `public/`) | What it is |
|---|---|
| `config.js` | Defaults: media host (`media.example.com`) and site title |
| `config.local.js` | **Yours, not in git** (gitignored; create it). Its keys override `config.js`, e.g. `export default { media: "https://media.your-domain.com" };`. Optional: skipped when it's missing, with a console warning if it's there but broken |
| `index.html`, `style.css` | The page |
| `app.js` | Fetching, map, gallery, viewer, favourites, downloads, sign-in |
| `lib.js` | Pure helpers (URLs, dates in the trip's zone, sign-in link, favourites, download names, the ZIP writer), tested by `test/test_site.mjs` |
| `_headers` | Security headers for Cloudflare Pages |

## Try it locally

Put your media host in `site/public/config.local.js` (above), then:

```
python -m http.server 8000 -d site/public
```

Open http://127.0.0.1:8000. You'll see your trips and covers, but trips won't open: the page's origin isn't in the Worker's `SITE_ORIGINS`, and it isn't on your domain, so the sign-in cookie wouldn't reach it anyway. The page says so. Without `config.local.js` the page uses `config.js` (example.com) and says that instead; the browser's console shows one 404 for the missing file, which the page ignores.

## Deploy on Cloudflare Pages

1. Set `media` (and `title` if you like) in `public/config.local.js`. `wrangler pages deploy` uploads the folder as it is on your disk, `config.local.js` included. A Pages project connected to your fork builds from git, where `config.local.js` doesn't exist: set them in `config.js` in your fork instead.
2. Deploy the folder (Node 18+; `npx wrangler login` once):
   ```
   npx wrangler pages project create wander-site     # first time only
   npx wrangler pages deploy site/public --project-name wander-site
   ```
   Or in the dashboard: Workers & Pages → Create → Pages → upload `site/public`, or connect your fork with no build command and `site/public` as the output directory.
3. Pages project → **Custom domains** → add your site host, e.g. `wander.example.com`. It must be on the **same registrable domain** as the media host, so browsers send the Access cookie with image and video requests ([LEARNINGS.md, D7](../LEARNINGS.md#decisions)).
4. Add that origin to the Worker's `SITE_ORIGINS` in `worker/wrangler.toml` (comma-separated, e.g. `"https://wander.example.com"`) and redeploy the Worker (`cd worker && npx wrangler deploy`).
5. Check in a private window: the landing page lists your trips with 🔒 badges; open one → **Sign in** → enter the emailed code → you're back on the trip and photos load.

Trip links look like `/?trip=lisbon-2025`. On Pages, `/lisbon-2025` and `/lisbon-2025/` work too (Pages serves `index.html` for unknown paths when there's no `404.html`). That's why asset and home links are root-absolute (`/app.js`, `/`): serve the folder from the root of its host name, as above, not from a sub-path.

## How it follows the client rules

- Everything on the media host is fetched with `credentials: 'include'`; images and videos are plain `<img>`/`<video>` with no `crossorigin` attribute, so they carry the cookie.
- Files it fetches itself (to share or zip) also use `cache: 'no-store'`: an `<img>` may have cached the same URL without CORS headers, and the fetch would fail on that copy.
- Times are shown in the trip's zone (`tzOffsetMin`), never the visitor's.
- Trip data stays in memory; nothing is written to browser storage.
- Signing in goes through `/auth/<slug>?return=<this page>`; the page adds `signedin=1` so it can tell "not signed in" from "signed in, but not on this trip".

Tests: `cd site && npm test` (also run by CI).
