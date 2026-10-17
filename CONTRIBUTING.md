# Contributing

Thanks for looking! Wander is a small personal project, maintained in spare time, so replies to issues and pull requests may be slow. Small, focused changes are the easiest to say yes to.

## Set up a dev environment

You don't need a real trip, a Cloudflare account or any credentials to work on the code. Everything external (exiftool, ffmpeg, rclone, the network, the Cloudflare API) is stubbed in the tests.

- **Python 3.9+** with Pillow: `pip install pillow`
- **Node 18+** for the Worker and the browser-side tests (no npm packages to install)

```
git clone https://github.com/Jcube101/wander
cd wander
pip install pillow
```

To try the tools for real you'll also want exiftool and ffmpeg ([tripmap/README.md](tripmap/README.md#one-time-setup)) and a folder of your own photos. `python tripmap/build.py "<folder>" --name "Test" --tz +00:00 --quick` and then `python tripmap/serve.py "<folder>"` gets you the local map and editor without any Cloudflare setup.

## Run the tests

The same three commands CI runs on every push (`.github/workflows/test.yml`):

```
python -m unittest discover tripmap/tests     # builder, editor server, publish, access, config, launchers
node --test tripmap/tests/test_viewer.mjs      # editor helpers from viewer.html
cd worker && npm test                          # the Worker, with a mocked R2 bucket
```

Tests use `wander.config.example.json` (example.com and a made-up trip), never your own config. `tripmap/tests/test_build_rules.py` locks in how times and locations are worked out; if you change that behaviour on purpose, change the test with it and say why.

## Rules every change must keep

- **Never commit personal data:** no photos or videos, no coordinates, no `trip.json`/`trips.json`/`overrides.json`/`clip_locations.csv`, no keys or tokens, no real emails (use `@example.com`). `.gitignore` enforces most of this; please don't weaken it.
- **The Worker's path rules stay strict:** keys are used exactly as sent, and any `%`-encoding, `..` or `//` is refused, so Cloudflare Access and the Worker can never disagree about a path. The Worker only serves its allow-list of file types and never decides *who* may see a trip (Access does).
- **No database.** Identity is the Cloudflare Access cookie; data is static JSON in R2.
- **Local-only files never go online:** `trip.js` and `index.html` in `_tripmap/` hold folder paths; `publish.py` never uploads them and the Worker refuses them.
- **Data contract:** `trip.json`/`trips.json` are the interface sites build on ([SPEC.md](SPEC.md#data-contract--build-your-own-site)). A change there needs the spec updated in the same pull request.

## Report a bug or propose a change

1. **Open an issue first.** Say what you did, what you expected and what happened (for build problems: the build's last lines and your OS). Please leave out photos, coordinates and email addresses. For a new feature, describe the problem before the solution, so we can agree on the approach before you spend time on it.
2. **Then a pull request,** small and about one thing. Include tests for behaviour changes, keep the docs in step (README, SPEC, RUNBOOK), and make sure the three test commands above pass.
3. **Security problems** (anything that could show a trip to the wrong person): please don't open a public issue. Use GitHub's "Report a vulnerability" (Security tab) instead.

By contributing you agree that your contribution is licensed under the [MIT License](LICENSE).
