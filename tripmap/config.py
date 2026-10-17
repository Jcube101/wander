#!/usr/bin/env python3
"""
Instance settings: where your Wander lives (site, media host, bucket, Access names).

The first file found wins:
  1. the file named by the WANDER_CONFIG environment variable
  2. wander.config.json in the repo root (gitignored)
  3. ~/.wander/config.json  (%USERPROFILE%\\.wander\\config.json on Windows)

Start from wander.config.example.json in the repo root. Only publish.py and
access.py need it; build.py and the editor run without one.

    python config.py      # show which file is used and what it says
"""
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
EXAMPLE = REPO / "wander.config.example.json"
HOME_FILE = Path.home() / ".wander" / "config.json"
REPO_FILE = REPO / "wander.config.json"

HELP = f"""No Wander config found. Publishing and Access need one.

Copy {EXAMPLE.name} to {HOME_FILE}
(or to {REPO_FILE.name} in the repo root) and fill in your own values:
media host, rclone remote and bucket, site URL. See SETUP.md."""

HOST = re.compile(r"[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+")
BUCKET = re.compile(r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]")
REMOTE = re.compile(r"[\w.-]+")
DURATION = re.compile(r"\d+(h|m)")


class ConfigError(Exception):
    """The config is missing or wrong; the message says how to fix it."""


@dataclass(frozen=True)
class Config:
    path: Path
    media_host: str      # e.g. media.example.com (no scheme)
    rclone_remote: str   # rclone remote name, e.g. r2
    bucket: str          # R2 bucket, e.g. trip-media
    site_url: str        # e.g. https://wander.example.com, or "" if not set
    access_prefix: str   # Access names start with this: "Wander – Bali crew"
    app_session: str     # Access app session length, e.g. 24h
    policy_session: str  # Access policy session length, e.g. 730h
    contact: str         # build.py --contact default ("Request original" link)

    @property
    def remote(self):
        """rclone destination for the bucket, e.g. r2:trip-media"""
        return f"{self.rclone_remote}:{self.bucket}"


def candidates():
    env = os.environ.get("WANDER_CONFIG")
    if env:
        return [Path(env).expanduser()]
    return [REPO_FILE, HOME_FILE]


def find():
    """The config file in use, or None."""
    env = os.environ.get("WANDER_CONFIG")
    if env and not Path(env).expanduser().is_file():
        raise ConfigError(f"WANDER_CONFIG points at {env}, which doesn't exist.")
    return next((p for p in candidates() if p.is_file()), None)


def _get(data, dotted, default=None):
    cur = data
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def parse(data, path):
    """Validate a loaded config dict and return a Config."""
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: expected a JSON object")
    problems = []

    def need(dotted, pattern, what, default=None):
        v = _get(data, dotted, default)
        if not isinstance(v, str) or not pattern.fullmatch(v):
            problems.append(f"{dotted} should be {what} (got {v!r})")
            return ""
        return v

    host = need("media.host", HOST, "a bare host name like media.example.com")
    remote = need("storage.remote", REMOTE, "an rclone remote name like r2")
    bucket = need("storage.bucket", BUCKET, "an R2 bucket name like trip-media")
    app_s = need("access.appSession", DURATION, "a duration like 24h", "24h")
    pol_s = need("access.policySession", DURATION, "a duration like 730h", "730h")
    site = _get(data, "site.url") or ""
    if site and not (isinstance(site, str) and re.fullmatch(r"https://[^/\s]+", site.rstrip("/"))):
        problems.append(f"site.url should be like https://wander.example.com (got {site!r})")
    prefix = _get(data, "access.prefix", "Wander")
    if not isinstance(prefix, str) or not prefix.strip():
        problems.append(f"access.prefix should be a short name like Wander (got {prefix!r})")
    contact = _get(data, "defaults.contact", "") or ""
    if not isinstance(contact, str):
        problems.append(f"defaults.contact should be text (got {contact!r})")
    if problems:
        raise ConfigError(f"{path}:\n  " + "\n  ".join(problems))
    return Config(path=Path(path), media_host=host, rclone_remote=remote, bucket=bucket,
                  site_url=site.rstrip("/"), access_prefix=prefix.strip(), app_session=app_s,
                  policy_session=pol_s, contact=contact)


def load(required=True):
    """The Config, or None when there's no file and required is False."""
    path = find()
    if path is None:
        if required:
            raise ConfigError(HELP)
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))  # Notepad may add a BOM
    except ValueError as e:
        raise ConfigError(f"{path} isn't valid JSON: {e}") from None
    return parse(data, path)


def main():
    try:
        cfg = load()
    except ConfigError as e:
        print(e)
        return 1
    print(f"Config: {cfg.path}")
    for k in ("media_host", "remote", "site_url", "access_prefix", "app_session", "policy_session", "contact"):
        print(f"  {k}: {getattr(cfg, k)!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
