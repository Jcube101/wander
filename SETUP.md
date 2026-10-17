# First-time setup

From nothing to your first trip online, behind sign-in. Plan on an hour or two, once. Everything here fits Cloudflare's free tier.

You'll end up with two host names on one domain you own, for example:

| Host | Serves | Set up in |
|---|---|---|
| `wander.example.com` | Your site (public page; trips load only for signed-in people) | Step 8 |
| `media.example.com` | Trip data and previews, through the Worker, behind Access | Steps 3–6 |

Both must be on the **same registrable domain** (`example.com` here). The sign-in cookie lives on the media host, and browsers only send it along with the site's image and video requests when the two are same-site ([LEARNINGS.md, D7](LEARNINGS.md#decisions)).

Commands run from the repo root. On mac/Linux use `python3` and `/` paths. Windows-tested; mac/Linux should work.

## 1. Accounts and tools

- A **Cloudflare account** (free) with your **domain added** to it, i.e. Cloudflare runs its DNS.
- **Python 3.9+** with Pillow, **exiftool**, **ffmpeg** and **rclone** on your PATH ([install commands](tripmap/README.md#one-time-setup)).
- **Node 18+** (for `npx wrangler`, Cloudflare's deploy tool).

```
git clone https://github.com/Jcube101/wander
cd wander
pip install pillow
```

## 2. Your config

Copy the template to your home folder and fill it in:

```
mkdir ~/.wander                                         # Windows: mkdir %USERPROFILE%\.wander
cp wander.config.example.json ~/.wander/config.json     # Windows: copy wander.config.example.json %USERPROFILE%\.wander\config.json
```

| Key | Example | Meaning |
|---|---|---|
| `site.url` | `https://wander.example.com` | Your site; printed after a publish |
| `media.host` | `media.example.com` | The Worker's host name (no `https://`) |
| `storage.remote` | `r2` | The rclone remote you create in step 4 |
| `storage.bucket` | `trip-media` | The R2 bucket from step 3 |
| `access.prefix` | `Wander` | Access names start with it: `Wander – All trips`, `Wander – Lisbon crew` |
| `access.appSession` / `policySession` | `24h` / `730h` | How long a sign-in lasts (per app / per policy) |
| `defaults.contact` | `""` | Optional "Request original" link in the local viewer |

`python tripmap/config.py` shows which file is used and what it says. (It looks at `$WANDER_CONFIG` first, then `wander.config.json` in the repo root, then `~/.wander/config.json`; the repo file is gitignored.)

## 3. The R2 bucket

Cloudflare dashboard → **R2 Object Storage** → **Create bucket**, named as in your config (e.g. `trip-media`).

- Leave public access **off** and don't give the bucket a custom domain or `r2.dev` URL. Only the Worker and your upload key should reach it.

## 4. A scoped upload key for rclone

R2 → **Manage API tokens** → **Create API token**:

- Permissions: **Object Read & Write**.
- Specify bucket(s): **only this bucket**.

Copy the Access Key ID, the Secret Access Key and the S3 endpoint (`https://<account id>.r2.cloudflarestorage.com`), then:

```
rclone config create r2 s3 provider=Cloudflare access_key_id=<KEY> secret_access_key=<SECRET> endpoint=<ENDPOINT> acl=private
rclone lsf r2:trip-media --s3-no-check-bucket       # no output and no error = it works
```

The key can't create buckets, which is why every rclone call Wander makes has `--s3-no-check-bucket`. The key lives in rclone's own config, never in this repo.

## 5. Deploy the Worker

```
cd worker
cp wrangler.example.toml wrangler.toml       # Windows: copy wrangler.example.toml wrangler.toml
```

In `wrangler.toml` (gitignored), set:

- `routes` → `pattern = "media.example.com"`, your media host. `custom_domain = true` makes Cloudflare create its DNS record; the name must not already have one.
- `bucket_name` → your bucket.
- `SITE_ORIGINS` → your site's origin, e.g. `"https://wander.example.com"`. Comma-separate extra origins (a builder's preview, say). Only these may read trips with the sign-in cookie, and sign-in only sends people back to them.

```
npm test
npx wrangler login
npx wrangler deploy
cd ..
```

Check it answers (404 is right until your first publish creates `trips.json`):

```
curl -s -o /dev/null -w "%{http_code}\n" https://media.example.com/trips.json
```

## 6. Cloudflare Access

Access is the only gate: the Worker serves any allowed file it's asked for, so a trip must have its Access app **before** it's published. `publish.py` checks this and refuses otherwise.

**Zero Trust, once:**

1. Dashboard → **Zero Trust**. The first time, pick a team name and the Free plan (up to 50 users).
2. Settings → Authentication → **Login methods**: add **One-time PIN** (people get a code by email; no accounts). Wander uses only this one.
3. Access → **Rule groups** → add a group named exactly `<prefix> – All trips` (with an en dash, e.g. `Wander – All trips`), including your own email. People in it see every trip.

**An API token for `access.py`,** so new trips and crew members need no dashboard clicks:

1. Dashboard → Manage Account → **Account API Tokens** → Create Token → **Custom token**.
2. Permissions, both **Account**-scoped, nothing else:
   - `Access: Apps and Policies` → Edit
   - `Access: Organizations, Identity Providers, and Groups` → Edit (groups, the One-time PIN lookup, session revoke)
3. Account Resources: your account only. No zone, Workers or R2 permissions.
4. Save it as `~/.wander/cloudflare.env` (outside the repo), two lines:
   ```
   CF_API_TOKEN=<token>
   CF_ACCOUNT_ID=<account id, from the dashboard URL or Account home>
   ```
   Real environment variables of the same names override the file. Never paste the token into a chat or a repo; to rotate it, roll it in the dashboard and replace the line.

`python tripmap/access.py list all` should now list your all-trips group.

## 7. Your first trip

Say the trip is "Lisbon 2025" (slug `lisbon-2025`) in a folder of photos and videos.

1. **Build** a quick version (thumbnails only) and look at it:
   ```
   python tripmap/build.py "<trip folder>" --name "Lisbon 2025" --tz +01:00 --quick
   python tripmap/launcher.py "<trip folder>"
   ```
   `--tz` is the trip's UTC offset (required). For DJI clips, add `--camera-offset` (the camera clock vs UTC). The launcher file now in the trip folder opens the editor.
2. **Fix** places, days and times in the editor, then **Apply to map**. Run **⋯ → Scan for new files** for the full build (1600 px photos and 720p videos; it can take a long time, and resumes if stopped).
3. **Access for the trip:**
   ```
   python tripmap/access.py setup lisbon-2025 "Lisbon 2025" --dry-run    # read the plan
   python tripmap/access.py setup lisbon-2025 "Lisbon 2025"              # create it (asks y/N)
   python tripmap/access.py add lisbon-2025 friend@example.com
   ```
   This makes the crew group `Wander – Lisbon crew`, the policy `Wander – Lisbon viewers` (crew OR all trips) and the app `Wander – Lisbon 2025` covering `media.example.com/lisbon-2025` and `/auth/lisbon-2025`.
4. **Publish:** check the plan first, then press **Publish** in the editor (or run it without `--dry-run`):
   ```
   python tripmap/publish.py "<trip folder>" --dry-run
   ```
5. **Check** that a stranger can't read it. This must print 302, 401 or 403, **never 200**:
   ```
   curl -s -o /dev/null -w "%{http_code}\n" https://media.example.com/lisbon-2025/trip.json
   ```

## 8. The site

Any static site can be the front end; it only reads JSON from the media host.

- **Use the reference viewer:** set your media host in `site/public/config.js` and deploy the folder to Cloudflare Pages ([site/README.md](site/README.md)). About ten minutes.
- **Build your own:** the [data contract](SPEC.md#data-contract--build-your-own-site) has the two file formats and the client rules (credentials, no `crossorigin` on media tags, times in the trip's zone, the `/auth/<slug>` sign-in hop). The live example was built with Lovable from that contract.

Wherever it's hosted, give it a host name on the same domain as the media host (e.g. `wander.example.com`) and make sure its origin is in the Worker's `SITE_ORIGINS` (step 5; redeploy after changing it).

## Next

- Everyday tasks (add photos, fix a place, give someone access, remove someone): [RUNBOOK.md](RUNBOOK.md).
- If something doesn't work: [RUNBOOK.md → Troubleshooting](RUNBOOK.md#troubleshooting) and [LEARNINGS.md](LEARNINGS.md).
- With [Claude Code](https://claude.com/claude-code), `/new-trip` walks through step 7 for a new trip. Keep your own instance notes (domains, where your trips live) in `~/.wander/NOTES.md`; the repo's CLAUDE.md loads them when present.
