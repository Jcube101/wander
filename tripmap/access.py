#!/usr/bin/env python3
"""
Manage Cloudflare Access for Wander trips.

    python access.py setup <slug> "<Title>"     # crew group + policy + app; idempotent
    python access.py add <slug|all> <email>     # add to the trip's crew (or "Wander – All trips")
    python access.py remove <slug|all> <email>  # remove; --revoke also ends their live sessions
    python access.py list <slug|all>            # members, plus the app's destinations and policy

Write commands take --dry-run (print the plan, change nothing). setup and remove
ask y/N before writing unless --yes is given.

Every trip gets the same app and policy settings: APP_SETTINGS below, plus the
media host, name prefix and session lengths from the Wander config (config.py).
setup never deletes an app, policy or group; that stays a dashboard action.
Before any write, groups may only hold email rules and policies only group rules
with an allow decision; anything else (everyone, service tokens, IP ranges,
bypass...) is refused.

Credentials: CF_API_TOKEN and CF_ACCOUNT_ID from the environment, else from
%USERPROFILE%\\.wander\\cloudflare.env (outside the repo). The token is never printed.
"""
import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import config  # noqa: E402

API = "https://api.cloudflare.com/client/v4"
CRED_FILE = Path.home() / ".wander" / "cloudflare.env"
DASH = "–"  # names use an en dash: "Wander – All trips"
# An empty group can't be saved, so it holds an address that can't exist (RFC 2606 .invalid).
PLACEHOLDER = "nobody@wander.invalid"
# The same for every trip; change here, not per trip. The app's session length
# comes from the config (access.appSession), the policy's from access.policySession.
APP_SETTINGS = {
    "type": "self_hosted",
    "app_launcher_visible": False,
    "auto_redirect_to_identity": False,
    "http_only_cookie_attribute": False,
    "eager_redirect_cookie_setting": True,
    "enable_binding_cookie": False,
    "options_preflight_bypass": False,
}
CFG = None  # the Wander config, loaded by main() (or on first use)
# Read-only fields an app GET returns that a PUT must not send back.
APP_READ_ONLY = {"id", "uid", "aud", "created_at", "updated_at", "self_hosted_domains", "policies"}
# Worker paths that aren't trips (favs/ holds people's favourites).
RESERVED_SLUGS = {"all", "auth", "public", "me", "favs", "trips.json"}

TOKEN_HELP = """Cloudflare credentials not found (CF_API_TOKEN and CF_ACCOUNT_ID).

Create the token once:
  1. dash.cloudflare.com -> Manage Account -> Account API Tokens -> Create Token -> Custom token.
  2. Permissions (both Account-scoped, nothing else):
       Account | Access: Apps and Policies | Edit
       Account | Access: Organizations, Identity Providers, and Groups | Edit
     (API names "Access: Apps and Policies Write" and
      "Access: Organizations, Identity Providers, and Groups Write".)
  3. Account Resources: Include -> your account only. No zone permissions.
  4. Save {path} as two lines:
       CF_API_TOKEN=<token>
       CF_ACCOUNT_ID=<account id from the dashboard URL or Account home>
Keep that file outside the repo; never paste the token into chat."""


class CFError(Exception):
    """An API call failed; the message is safe to print."""


class Refused(Exception):
    """A write would grant access more broadly than email/group rules allow."""


def log(msg=""):
    print(msg, flush=True)


# ---------- credentials ----------

def read_env_file(path):
    values = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8-sig").splitlines():  # Notepad may add a BOM
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            values[k.strip()] = v.strip().strip('"').strip("'")
    return values


def load_credentials(path=None):
    """(token, account) with real env vars beating the file, or None if either is missing."""
    file_vals = read_env_file(path or CRED_FILE)
    token = os.environ.get("CF_API_TOKEN") or file_vals.get("CF_API_TOKEN")
    account = os.environ.get("CF_ACCOUNT_ID") or file_vals.get("CF_ACCOUNT_ID")
    return (token, account) if token and account else None


# ---------- guardrails ----------

def guard(path, body):
    """Refuse a group/policy/app write that could open a trip beyond named people."""
    kind = path.split("/")[0]
    name = body.get("name")
    if kind == "groups":
        allowed, what = {"email"}, "email"
    elif kind == "policies":
        if body.get("decision") != "allow":
            raise Refused(f"policy {name!r} has decision {body.get('decision')!r}; only 'allow' is permitted "
                          f"(never bypass or non_identity)")
        allowed, what = {"group"}, "rule-group"
    elif kind == "apps":
        for p in body.get("policies") or []:
            if not (isinstance(p, dict) and set(p) == {"id", "precedence"}):
                raise Refused(f"app {name!r} may only reference reusable policies by id, not {p!r}")
        return
    else:
        return
    if not body.get("include"):
        raise Refused(f"{kind[:-1]} {name!r} has an empty include list")
    for key in ("include", "exclude", "require"):
        for rule in body.get(key) or []:
            bad = sorted(set(rule) - allowed) if isinstance(rule, dict) else [repr(rule)]
            if bad:
                raise Refused(f"{kind[:-1]} {name!r}: {key} has a {', '.join(bad)} rule. Only {what} rules are "
                              f"allowed here (never everyone, service tokens, IP ranges or other selectors)")


# ---------- API ----------

class Client:
    def __init__(self, token, account):
        self._token = token
        self.account = account

    def call(self, method, path, body=None):
        if method in ("POST", "PUT"):
            guard(path, body or {})
        payload = self._send(method, path, body)
        if not payload.get("success"):
            msgs = "; ".join(f"{e.get('code')}: {e.get('message')}" for e in payload.get("errors") or [])
            raise CFError(f"{method} {path.split('?')[0]} failed: {msgs or 'no detail'}")
        return payload

    def _send(self, method, path, body):
        req = urllib.request.Request(
            f"{API}/accounts/{self.account}/access/{path}", method=method,
            data=None if body is None else json.dumps(body).encode(),
            headers={"Authorization": f"Bearer {self._token}", "Content-Type": "application/json",
                     "User-Agent": "wander-access"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            try:
                return json.load(e)
            except ValueError:
                raise CFError(f"{method} {path.split('?')[0]}: HTTP {e.code}") from None
        except (urllib.error.URLError, OSError) as e:
            raise CFError(f"{method} {path.split('?')[0]}: {getattr(e, 'reason', e)}") from None

    def get(self, path):
        return self.call("GET", path)["result"]

    def list(self, path):
        out, page = [], 1
        while True:
            p = self.call("GET", f"{path}?page={page}&per_page=50")
            items = p.get("result") or []
            out += items
            if not items or page >= (p.get("result_info") or {}).get("total_pages", 1):
                return out
            page += 1


# ---------- names and lookups ----------

def cfg():
    global CFG
    if CFG is None:
        CFG = config.load()
    return CFG


def app_settings():
    return {**APP_SETTINGS, "session_duration": cfg().app_session}


def trip_name(title):
    """Short name: the title without a trailing year ("Bali 2027" -> "Bali")."""
    return re.sub(r"\s+\d{4}$", "", title.strip()) or title.strip()


def all_group():
    return f"{cfg().access_prefix} {DASH} All trips"


def crew_name(trip):
    return f"{cfg().access_prefix} {DASH} {trip} crew"


def app_name(title):
    return f"{cfg().access_prefix} {DASH} {title}"


def policy_name(trip):
    return f"{cfg().access_prefix} {DASH} {trip} viewers"


def destinations(slug):
    host = cfg().media_host
    return [f"{host}/{slug}", f"{host}/auth/{slug}"]


def check_slug(slug):
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug) or slug in RESERVED_SLUGS:
        sys.exit(f"ERROR: {slug!r} isn't a trip slug (lowercase letters, digits and dashes; not {sorted(RESERVED_SLUGS)})")


def check_email(email):
    email = email.strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        sys.exit(f"ERROR: {email!r} doesn't look like an email address")
    if email == PLACEHOLDER:
        sys.exit(f"ERROR: {PLACEHOLDER} is the empty-group placeholder")
    return email


def by_name(items, name):
    hits = [i for i in items if i.get("name") == name]
    if len(hits) > 1:
        raise CFError(f"several objects are named {name!r}; fix it in the dashboard")
    return hits[0] if hits else None


def find_app(apps, slug, name=None):
    """The app guarding this slug: matched by destination first (names can drift; an
    app made in the dashboard may have any name), else by name. Several candidates
    is an error."""
    want = set(destinations(slug))
    hits = [a for a in apps if want & {d.get("uri") for d in a.get("destinations") or []}]
    if not hits and name:
        hits = [a for a in apps if a.get("name") == name]
    if len(hits) > 1:
        raise CFError(f"several Access apps cover {slug}: {[a.get('name') for a in hits]}; fix it in the dashboard")
    return hits[0] if hits else None


def otp_idp(client):
    otp = [i for i in client.list("identity_providers") if i.get("type") == "onetimepin"]
    if len(otp) != 1:
        raise CFError(f"expected exactly one One-time PIN login method, found {len(otp)}")
    return otp[0]["id"]


def members(group):
    return [r["email"]["email"] for r in group.get("include") or [] if "email" in r]


def group_body(group, emails):
    rules = [{"email": {"email": e}} for e in emails] or [{"email": {"email": PLACEHOLDER}}]
    return {"name": group["name"], "include": rules,
            "exclude": group.get("exclude") or [], "require": group.get("require") or []}


def resolve_group(client, target, trip=None):
    """The rule group behind <slug|all>. For a slug: the crew group the trip's policy
    includes, else the group named after --trip or the slug."""
    groups = client.list("groups")
    if target == "all":
        g = by_name(groups, all_group())
        if not g:
            raise CFError(f"rule group {all_group()!r} not found")
        return g
    check_slug(target)
    if not trip:
        app = find_app(client.list("apps"), target)
        all_id = (by_name(groups, all_group()) or {}).get("id")
        if app:
            ids = [r["group"]["id"] for p in app.get("policies") or [] for r in p.get("include") or []
                   if "group" in r and r["group"]["id"] != all_id]
            crews = [g for g in groups if g["id"] in ids]
            if len(crews) == 1:
                return crews[0]
        trip = re.sub(r"-\d{4}$", "", target).replace("-", " ").title()
    g = by_name(groups, crew_name(trip))
    if not g:
        raise CFError(f"rule group {crew_name(trip)!r} not found (run setup first, or pass --trip)")
    return g


# ---------- confirm ----------

def confirm(prompt, yes):
    if yes:
        return True
    try:
        return input(f"{prompt} [y/N] ").strip().lower() in ("y", "yes")
    except EOFError:
        return False


# ---------- setup ----------

def diff(live, want, keys):
    return [f"    {k}: {live.get(k)!r} -> {want[k]!r}" for k in keys if live.get(k) != want[k]]


def app_view(app):
    """The fields setup manages, normalised for comparing."""
    v = {k: app.get(k) for k in app_settings()}
    v["name"] = app.get("name")
    v["domain"] = app.get("domain")
    v["destinations"] = [d.get("uri") for d in app.get("destinations") or [] if d.get("type") == "public"]
    v["allowed_idps"] = sorted(app.get("allowed_idps") or [])
    v["policies"] = [(p.get("id"), p.get("precedence")) for p in app.get("policies") or []]
    return v


def policy_view(p):
    return {"name": p.get("name"), "decision": p.get("decision"), "include": p.get("include") or [],
            "exclude": p.get("exclude") or [], "require": p.get("require") or [],
            "session_duration": p.get("session_duration")}


def cmd_setup(client, args):
    check_slug(args.slug)
    trip = args.trip or trip_name(args.title)
    names = {"group": crew_name(trip), "policy": policy_name(trip), "app": app_name(args.title)}
    groups, policies, apps = client.list("groups"), client.list("policies"), client.list("apps")
    idp = otp_idp(client)
    everyone = by_name(groups, all_group())  # the all-trips group
    if not everyone:
        raise CFError(f"rule group {all_group()!r} not found; create it in the dashboard first")
    group = by_name(groups, names["group"])
    policy = by_name(policies, names["policy"])
    app = find_app(apps, args.slug, names["app"])
    for g in filter(None, (everyone, group)):  # a policy would grant whatever these hold
        guard("groups", g)
    ids = {"group": (group or {}).get("id") or "<new crew group>",
           "policy": (policy or {}).get("id") or "<new policy>"}

    def want_policy():
        return {"name": names["policy"], "decision": "allow",
                "include": [{"group": {"id": ids["group"]}}, {"group": {"id": everyone["id"]}}],
                "exclude": [], "require": [], "session_duration": cfg().policy_session}

    def want_app():
        dest = destinations(args.slug)
        return {"name": names["app"], "domain": dest[0], **app_settings(),
                "destinations": [{"type": "public", "uri": u} for u in dest],
                "allowed_idps": [idp], "policies": [{"id": ids["policy"], "precedence": 1}]}

    def want_app_view():
        w = want_app()
        return {**w, "destinations": [d["uri"] for d in w["destinations"]],
                "policies": [(p["id"], p["precedence"]) for p in w["policies"]]}

    steps, lines = [], []
    if group:
        lines.append(f"  rule group {names['group']!r}: exists ({len(members(group))} member rules)")
    else:
        lines.append(f"  rule group {names['group']!r}: CREATE (empty: holds {PLACEHOLDER} until you add people)")
        steps.append(("group", lambda: client.call("POST", "groups", group_body({"name": names["group"]}, []))))
    if policy:
        d = diff(policy_view(policy), want_policy(), ["decision", "include", "exclude", "require", "session_duration"])
        lines.append(f"  policy {names['policy']!r}: " + ("matches" if not d else "UPDATE"))
        lines += d
        if d:
            steps.append(("policy-update", lambda: client.call("PUT", f"policies/{policy['id']}", want_policy())))
    else:
        lines.append(f"  policy {names['policy']!r}: CREATE (allow: {names['group']} OR {all_group()}, "
                     f"session {cfg().policy_session})")
        steps.append(("policy", lambda: client.call("POST", "policies", want_policy())))
    if app:
        live = app_view(app)
        d = diff(live, want_app_view(), list(want_app_view()))
        lines.append(f"  app {app.get('name')!r}: " + ("matches" if not d else "UPDATE"))
        lines += d

        def update_app():
            body = {k: v for k, v in app.items() if k not in APP_READ_ONLY}
            body.update(want_app())
            return client.call("PUT", f"apps/{app['id']}", body)
        if d:
            steps.append(("app-update", update_app))
    else:
        lines.append(f"  app {names['app']!r}: CREATE ({', '.join(destinations(args.slug))}; One-time PIN only, "
                     f"App Launcher hidden, session {cfg().app_session})")
        steps.append(("app", lambda: client.call("POST", "apps", want_app())))

    log(f"Access setup for {args.slug}:")
    for line in lines:
        log(line)
    if not steps:
        log("Nothing to change.")
    elif args.dry_run:
        log(f"Dry run: {len(steps)} change(s) planned, nothing written.")
    elif not confirm(f"Apply {len(steps)} change(s)?", args.yes):
        log("Cancelled; nothing written.")
        return 1
    else:
        for kind, run in steps:
            result = run()["result"]
            if kind in ("group", "policy"):
                ids[kind] = result["id"]
            if kind in ("app", "app-update"):
                app = result
            log(f"  done: {kind}")
        log("Applied.")
    report_aud(args.slug, app)
    report_protection(args.slug)
    return 0


def report_aud(slug, app):
    """The app's AUD tag: the Worker checks favourites' tokens against it."""
    if app and app.get("aud"):
        log(f"App AUD tag: {app['aud']}")
        log(f'  Favourites: worker/wrangler.toml needs "{slug}" = "{app["aud"]}" in ACCESS_AUD; '
            f"then deploy the Worker (RUNBOOK.md -> New trip).")


def report_protection(slug):
    import publish
    ok, status = publish.check_protected(slug, cfg().media_host)
    if ok:
        log(f"Access check: {slug}/trip.json -> {status} (protected).")
    else:
        log(f"Access check: {slug}/trip.json -> {status} (NOT protected; don't publish).")


# ---------- members ----------

def cmd_add(client, args):
    email = check_email(args.email)
    group = resolve_group(client, args.target, args.trip)
    guard("groups", group)  # rewriting include keeps only emails; never drop other rules silently
    current = members(group)
    if email in [m.lower() for m in current]:
        log(f"{email} is already in {group['name']!r}; nothing to do.")
        return 0
    body = group_body(group, [m for m in current if m != PLACEHOLDER] + [email])
    if args.dry_run:
        log(f"Dry run: would add {email} to {group['name']!r}.")
        return 0
    client.call("PUT", f"groups/{group['id']}", body)
    log(f"Added {email} to {group['name']!r}.")
    return 0


def cmd_remove(client, args):
    email = check_email(args.email)
    group = resolve_group(client, args.target, args.trip)
    guard("groups", group)  # rewriting include keeps only emails; never drop other rules silently
    current = members(group)
    present = email in [m.lower() for m in current]
    if not present:
        log(f"{email} isn't in {group['name']!r}; nothing to remove.")
        if not args.revoke:
            return 0
    plan = ([f"remove {email} from {group['name']!r}"] if present else []) + \
           ([f"end all of {email}'s Access sessions (every app; they can sign in again where still allowed)"]
            if args.revoke else [])
    if args.dry_run:
        log("Dry run: would " + "; ".join(plan) + ".")
        return 0
    if not confirm("Will " + "; ".join(plan) + ". Continue?", args.yes):
        log("Cancelled; nothing written.")
        return 1
    if present:
        client.call("PUT", f"groups/{group['id']}", group_body(group, [m for m in current if m.lower() != email]))
        log(f"Removed {email} from {group['name']!r}.")
    if args.revoke:
        client.call("POST", "organizations/revoke_user", {"email": email})
        log(f"Revoked {email}'s Access sessions.")
    return 0


def cmd_list(client, args):
    group = resolve_group(client, args.target, args.trip)
    people = sorted(m for m in members(group) if m != PLACEHOLDER)
    log(f"{group['name']} ({len(people)}):")
    for m in people:
        log(f"  {m}")
    if not people:
        log("  (no members)")
    if args.target == "all":
        return 0
    app = find_app(client.list("apps"), args.target)
    if not app:
        log(f"No Access app covers {args.target} yet (run setup).")
        return 0
    names = {g["id"]: g["name"] for g in client.list("groups")}
    log(f"App {app.get('name')!r}: session {app.get('session_duration')}, "
        f"launcher {'shown' if app.get('app_launcher_visible') else 'hidden'}, AUD tag {app.get('aud')}")
    for d in app.get("destinations") or []:
        log(f"  destination {d.get('uri')}")
    for p in app.get("policies") or []:
        inc = [names.get(r["group"]["id"], r["group"]["id"]) if "group" in r else next(iter(r)) for r in p.get("include") or []]
        log(f"  policy {p.get('name')!r}: {p.get('decision')} if {' OR '.join(inc)}; session {p.get('session_duration')}")
    return 0


# ---------- main ----------

def build_parser():
    ap = argparse.ArgumentParser(description="Manage Cloudflare Access for Wander trips.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("setup", help="Create or check a trip's crew group, policy and app")
    s.add_argument("slug")
    s.add_argument("title")
    for name in ("add", "remove"):
        p = sub.add_parser(name, help=f"{name.title()} an email in a trip's crew, or 'all' for the all-trips group")
        p.add_argument("target", metavar="slug|all")
        p.add_argument("email")
    sub.choices["remove"].add_argument("--revoke", action="store_true",
                                       help="Also end that person's live Access sessions")
    lst = sub.add_parser("list", help="Show members, plus the app's destinations and policy")
    lst.add_argument("target", metavar="slug|all")
    for name, p in sub.choices.items():
        p.add_argument("--trip", help="Short trip name in group/policy names (default: title without the year)")
        if name != "list":
            p.add_argument("--dry-run", action="store_true", help="Print the plan; change nothing")
        if name in ("setup", "remove"):
            p.add_argument("--yes", action="store_true", help="Don't ask before writing")
    return ap


def main(argv=None, client=None):
    args = build_parser().parse_args(argv)
    try:  # never crash over the en dash on a non-UTF-8 console
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass
    global CFG
    try:
        CFG = config.load()
    except config.ConfigError as e:
        log(f"ERROR: {e}")
        return 2
    token = None
    if client is None:
        creds = load_credentials()
        if not creds:
            log(TOKEN_HELP.format(path=CRED_FILE))
            return 2
        token = creds[0]
        client = Client(*creds)
    try:
        return {"setup": cmd_setup, "add": cmd_add, "remove": cmd_remove, "list": cmd_list}[args.cmd](client, args)
    except Refused as e:
        log(f"REFUSED: {e}. That write was not sent.")
        return 3
    except CFError as e:
        msg = str(e)
        if token:
            msg = msg.replace(token, "***")
        log(f"ERROR: {msg}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
