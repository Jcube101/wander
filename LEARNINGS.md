# Wander — Learnings

Hard-won lessons. Each one: **symptom → cause → fix/rule**. Add new ones here, not in CLAUDE.md.

## Cloudflare / hosting

| Symptom | Cause | Fix / rule |
|---|---|---|
| Worker route and Access on `wander.` did nothing | `wander.job-joseph.com` is an A record to Lovable's own Cloudflare account; no O2O for A records, so this zone's Workers/Access never run | Lock the media host (`media.`) instead; keep `wander.` DNS-only |
| Risk: Access allows a path the Worker reads differently | Encoded or odd paths (`%2F`, `..`, `//`) can be normalised differently by each | Worker refuses any `%`, `..`, `//`; keys used exactly as sent |
| Publishing before the Access app existed made the trip public | Access is the only gate; without an app the Worker serves the trip to anyone | `publish.py` refuses to publish an unprotected trip (Access app first, then Publish) |
| Trip page loads but images are blank | `crossorigin` on `<img>`/`<video>` makes the browser drop the Access cookie | Never put `crossorigin` on media tags |
| Site change "didn't work" | Lovable edits only reach the live domain after publishing | Re-publish in Lovable after every change |

## R2 / rclone

| Symptom | Cause | Fix / rule |
|---|---|---|
| `CreateBucket ... 403` on publish | Bucket-scoped key can't create buckets, and rclone checks by default | Every rclone call gets `--s3-no-check-bucket` |
| ETA said 23 h | rclone's early estimate is noise | Ignore it; 2.3 GB took ~10 min |

## Metadata

| Symptom | Cause | Fix / rule |
|---|---|---|
| DJI clips unplaced or at wrong times | DJI Pocket 4P writes no GPS; its clock drifts (~+07:45 vs UTC on Thailand) | Time = filename + `--camera-offset`; location = nearest phone photo or manual fix |
| WhatsApp items at odd times or other trips | WhatsApp strips EXIF | Date from filename + file time; drop items >1 day outside the trip; never auto-locate |
| Some Sony phone JPEGs fail with an empty error | Not confirmed. Full-size decodes failed with an empty error message, mostly during parallel builds | Reduced-size `draft` decoding, sequential retry, log `repr(e)` |

## Viewer / editor

| Symptom | Cause | Fix / rule |
|---|---|---|
| Map tiles stopped loading | CARTO raster tiles now need an API key | Esri tiles + OSM |
| Edit mode lost after picking a day | `history.replaceState` dropped `?edit` | Keep `location.search` when rewriting the URL |
| Hidden element still showed | A CSS `display` rule beat the `[hidden]` attribute | Add an explicit `[hidden]{display:none}` rule |
| Day chips stretched tall | Grid rows shared spare height | `grid-template-rows: auto auto 1fr auto` |

## Site / data contract

| Symptom | Cause | Fix / rule |
|---|---|---|
| Captions said "gps" | Site displayed the internal `loc` field | `loc` is a source code — never display it |
| Landing hero blurry | 640 px card used as a full-width hero | Publish a 1600 px `coverImage` too |

## Dev workflow

| Symptom | Cause | Fix / rule |
|---|---|---|
| `git init` ran in the home folder | Backslash path broke `cd` in Git Bash, next command ran anyway | Use forward slashes (`~/Github/wander`); chain with `&&` |
| Shell killed itself | `pkill -f <pattern>` matched its own command line | Kill by port or PID |
| Every code change had to be made twice: in the repo and in the copy inside the trip folder on D: | The code was copied into each trip folder | Run from the repo; each trip folder only holds `Open Wander Editor.bat` |
| Time spent "fixing" non-bugs | Reports were often misdiagnoses | Investigate and reproduce before fixing |
