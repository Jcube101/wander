"""Tests for access.py: setup mirrors an existing trip's app, idempotence, member add/remove,
--dry-run/--revoke, guardrails, credentials and token hygiene. All HTTP is faked.
Run: python -m unittest discover tripmap/tests"""
import contextlib
import copy
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# Tests always use the committed example config, never the machine's own.
os.environ["WANDER_CONFIG"] = str(Path(__file__).resolve().parents[2] / "wander.config.example.json")
import access  # noqa: E402

D = access.DASH
TOKEN = "tok-SENTINEL-1234567890"
OTP = "idp-otp"
ALL_ID, CREW_ID, POL_ID, APP_ID = "g-all", "g-crew", "p-lis", "a-lis"


def existing_trip():
    """An existing trip as the API returns it (made up, fake emails). Its app was
    made in the dashboard before the naming scheme, so it is called "media"."""
    groups = [
        {"id": ALL_ID, "name": f"Wander {D} All trips", "include": [{"email": {"email": "a@example.com"}}],
         "exclude": [], "require": []},
        {"id": CREW_ID, "name": f"Wander {D} Lisbon crew", "include": [{"email": {"email": "b@example.com"}}],
         "exclude": [], "require": []},
    ]
    policy = {"id": POL_ID, "name": f"Wander {D} Lisbon viewers", "decision": "allow",
              "include": [{"group": {"id": CREW_ID}}, {"group": {"id": ALL_ID}}], "exclude": [], "require": [],
              "session_duration": "730h", "reusable": True, "connection_rules": {"rdp": {}}}
    app = {"id": APP_ID, "uid": APP_ID, "aud": "aud", "name": "media", "type": "self_hosted",
           "domain": "media.example.com/lisbon-2025",
           "destinations": [{"type": "public", "uri": "media.example.com/lisbon-2025"},
                            {"type": "public", "uri": "media.example.com/auth/lisbon-2025"}],
           "self_hosted_domains": ["media.example.com/lisbon-2025", "media.example.com/auth/lisbon-2025"],
           "allowed_idps": [OTP], "auto_redirect_to_identity": False, "app_launcher_visible": False,
           "session_duration": "24h", "http_only_cookie_attribute": False, "eager_redirect_cookie_setting": True,
           "enable_binding_cookie": False, "options_preflight_bypass": False, "tags": [],
           "created_at": "x", "updated_at": "x",
           "policies": [dict(policy, precedence=1)]}
    return groups, [policy], [app]


class FakeCF(access.Client):
    """In-memory Access API. Records every call; only _send is replaced, so the
    real guard and error handling run."""

    def __init__(self, groups=(), policies=(), apps=()):
        super().__init__(TOKEN, "acct")
        self.state = {"groups": copy.deepcopy(list(groups)), "policies": copy.deepcopy(list(policies)),
                      "apps": copy.deepcopy(list(apps)),
                      "identity_providers": [{"id": OTP, "type": "onetimepin", "name": ""}]}
        self.calls = []
        self.n = 0

    def writes(self):
        return [c for c in self.calls if c[0] != "GET"]

    def _send(self, method, path, body):
        self.calls.append((method, path, copy.deepcopy(body)))
        base = path.split("?")[0]
        parts = base.split("/")
        if method == "GET" and len(parts) == 1:
            items = self.state[parts[0]]
            return {"success": True, "result": copy.deepcopy(items), "result_info": {"total_pages": 1}}
        if method == "POST" and base == "organizations/revoke_user":
            return {"success": True, "result": True}
        if method == "POST":
            self.n += 1
            obj = dict(body, id=f"new-{parts[0]}-{self.n}")
            self.state[parts[0]].append(obj)
            return {"success": True, "result": obj}
        if method == "PUT":
            items = self.state[parts[0]]
            i = next(i for i, o in enumerate(items) if o["id"] == parts[1])
            items[i] = dict(body, id=parts[1])
            return {"success": True, "result": items[i]}
        return {"success": False, "errors": [{"code": 0, "message": f"unhandled {method} {path}"}]}


def run(argv, cf, answer=None):
    """main() with captured output; protection check stubbed; input() answers `answer`."""
    out = io.StringIO()
    inp = mock.patch("builtins.input", side_effect=EOFError if answer is None else [answer])
    with mock.patch.object(access, "report_protection", lambda slug: access.log(f"Access check: {slug} stub")), \
            inp, contextlib.redirect_stdout(out):
        code = access.main(argv, client=cf)
    return code, out.getvalue()


class Setup(unittest.TestCase):
    def test_new_trip_creates_group_policy_app_mirroring_the_existing_trip(self):
        groups, policies, apps = existing_trip()
        cf = FakeCF(groups, policies, apps)
        code, out = run(["setup", "bali-2027", "Bali 2027", "--yes"], cf)
        self.assertEqual(code, 0, out)
        w = cf.writes()
        self.assertEqual([(m, p) for m, p, _ in w], [("POST", "groups"), ("POST", "policies"), ("POST", "apps")])
        group, policy, app = (b for _, _, b in w)
        self.assertEqual(group["name"], f"Wander {D} Bali crew")
        self.assertEqual(group["include"], [{"email": {"email": "nobody@wander.invalid"}}])
        self.assertEqual(policy["name"], f"Wander {D} Bali viewers")
        self.assertEqual(policy["decision"], "allow")
        self.assertEqual(policy["include"], [{"group": {"id": "new-groups-1"}}, {"group": {"id": ALL_ID}}])
        self.assertEqual(policy["session_duration"], policies[0]["session_duration"])
        self.assertEqual(app["name"], f"Wander {D} Bali 2027")
        self.assertEqual([d["uri"] for d in app["destinations"]],
                         ["media.example.com/bali-2027", "media.example.com/auth/bali-2027"])
        self.assertEqual(app["domain"], "media.example.com/bali-2027")
        self.assertEqual(app["policies"], [{"id": "new-policies-2", "precedence": 1}])
        first = apps[0]
        for k in ("type", "allowed_idps", *access.app_settings()):
            self.assertEqual(app[k], first[k], k)
        self.assertIn("Applied.", out)
        self.assertIn("Access check: bali-2027", out)

    def test_existing_matching_trip_changes_nothing(self):
        groups, policies, apps = existing_trip()
        apps[0]["name"] = f"Wander {D} Lisbon 2025"
        cf = FakeCF(groups, policies, apps)
        code, out = run(["setup", "lisbon-2025", "Lisbon 2025", "--yes"], cf)
        self.assertEqual(code, 0, out)
        self.assertEqual(cf.writes(), [])
        self.assertIn("Nothing to change.", out)

    def test_existing_trip_with_drift_shows_diff_and_updates_only_after_yes(self):
        groups, policies, apps = existing_trip()  # live app is named "media"
        apps[0]["app_launcher_visible"] = True
        policies[0]["session_duration"] = "24h"
        cf = FakeCF(groups, policies, apps)
        code, out = run(["setup", "lisbon-2025", "Lisbon 2025"], cf, answer="n")
        self.assertEqual(code, 1)
        self.assertIn(f"name: 'media' -> 'Wander {D} Lisbon 2025'", out)
        self.assertIn("app_launcher_visible: True -> False", out)
        self.assertIn("session_duration: '24h' -> '730h'", out)
        self.assertEqual(cf.writes(), [])

        code, out = run(["setup", "lisbon-2025", "Lisbon 2025"], cf, answer="y")
        self.assertEqual(code, 0, out)
        self.assertEqual([(m, p) for m, p, _ in cf.writes()], [("PUT", f"policies/{POL_ID}"), ("PUT", f"apps/{APP_ID}")])
        app_body = cf.writes()[1][2]
        self.assertNotIn("id", app_body)
        self.assertNotIn("self_hosted_domains", app_body)
        self.assertEqual(app_body["tags"], [])  # untouched live fields are sent back
        self.assertEqual(app_body["policies"], [{"id": POL_ID, "precedence": 1}])

    def test_found_by_destination_not_duplicated(self):
        cf = FakeCF(*existing_trip())
        run(["setup", "lisbon-2025", "Lisbon 2025", "--dry-run"], cf)
        self.assertNotIn(("POST", "apps"), [(m, p) for m, p, _ in cf.calls])

    def test_dry_run_makes_no_writes(self):
        cf = FakeCF(*existing_trip())
        code, out = run(["setup", "bali-2027", "Bali 2027", "--dry-run", "--yes"], cf)
        self.assertEqual(code, 0)
        self.assertEqual(cf.writes(), [])
        self.assertIn("3 change(s) planned, nothing written", out)

    def test_never_deletes(self):
        cf = FakeCF(*existing_trip())
        run(["setup", "bali-2027", "Bali 2027", "--yes"], cf)
        run(["setup", "lisbon-2025", "Lisbon 2025", "--yes"], cf)
        self.assertNotIn("DELETE", [m for m, _, _ in cf.calls])

    def test_bad_slug(self):
        with self.assertRaises(SystemExit):
            run(["setup", "auth", "Auth"], FakeCF(*existing_trip()))


class Members(unittest.TestCase):
    def test_add_and_add_again(self):
        cf = FakeCF(*existing_trip())
        code, out = run(["add", "lisbon-2025", "C@Example.com"], cf)
        self.assertEqual(code, 0, out)
        (m, p, body), = cf.writes()
        self.assertEqual((m, p), ("PUT", f"groups/{CREW_ID}"))
        self.assertEqual(access.members(body), ["b@example.com", "c@example.com"])
        code, out = run(["add", "lisbon-2025", "c@example.com"], cf)
        self.assertEqual(len(cf.writes()), 1)
        self.assertIn("already in", out)

    def test_add_to_all_trips(self):
        cf = FakeCF(*existing_trip())
        run(["add", "all", "c@example.com"], cf)
        self.assertEqual(cf.writes()[0][1], f"groups/{ALL_ID}")

    def test_add_replaces_placeholder(self):
        groups, policies, apps = existing_trip()
        groups[1]["include"] = [{"email": {"email": access.PLACEHOLDER}}]
        cf = FakeCF(groups, policies, apps)
        run(["add", "lisbon-2025", "c@example.com"], cf)
        self.assertEqual(access.members(cf.writes()[0][2]), ["c@example.com"])

    def test_remove_missing_is_noop(self):
        cf = FakeCF(*existing_trip())
        code, out = run(["remove", "lisbon-2025", "z@example.com", "--yes"], cf)
        self.assertEqual(code, 0)
        self.assertEqual(cf.writes(), [])
        self.assertIn("isn't in", out)

    def test_remove_last_member_leaves_placeholder(self):
        cf = FakeCF(*existing_trip())
        code, out = run(["remove", "lisbon-2025", "b@example.com", "--yes"], cf)
        self.assertEqual(code, 0, out)
        self.assertEqual(cf.writes()[0][2]["include"], [{"email": {"email": "nobody@wander.invalid"}}])

    def test_remove_asks_first(self):
        cf = FakeCF(*existing_trip())
        code, _ = run(["remove", "lisbon-2025", "b@example.com"], cf, answer="n")
        self.assertEqual((code, cf.writes()), (1, []))

    def test_remove_dry_run_and_revoke(self):
        cf = FakeCF(*existing_trip())
        run(["remove", "lisbon-2025", "b@example.com", "--revoke", "--dry-run"], cf)
        self.assertEqual(cf.writes(), [])
        run(["remove", "lisbon-2025", "b@example.com", "--revoke", "--yes"], cf)
        self.assertEqual([(m, p) for m, p, _ in cf.writes()],
                         [("PUT", f"groups/{CREW_ID}"), ("POST", "organizations/revoke_user")])
        self.assertEqual(cf.writes()[1][2], {"email": "b@example.com"})

    def test_add_dry_run(self):
        cf = FakeCF(*existing_trip())
        code, out = run(["add", "lisbon-2025", "c@example.com", "--dry-run"], cf)
        self.assertEqual((code, cf.writes()), (0, []))
        self.assertIn("would add", out)

    def test_list_hides_placeholder_and_shows_app(self):
        groups, policies, apps = existing_trip()
        groups[1]["include"].append({"email": {"email": access.PLACEHOLDER}})
        code, out = run(["list", "lisbon-2025"], FakeCF(groups, policies, apps))
        self.assertEqual(code, 0, out)
        self.assertIn("b@example.com", out)
        self.assertNotIn(access.PLACEHOLDER, out)
        self.assertIn("destination media.example.com/auth/lisbon-2025", out)
        self.assertIn(f"allow if Wander {D} Lisbon crew OR Wander {D} All trips", out)


class Guardrails(unittest.TestCase):
    def assertRefused(self, path, body):
        cf = FakeCF()
        with self.assertRaises(access.Refused):
            cf.call("PUT" if "/" in path else "POST", path, body)
        self.assertEqual(cf.calls, [])  # nothing sent

    def test_groups_only_take_emails(self):
        for rule in ({"everyone": {}}, {"service_token": {"token_id": "x"}}, {"any_valid_service_token": {}},
                     {"ip": {"ip": "0.0.0.0/0"}}, {"ip_list": {"id": "x"}}, {"email_domain": {"domain": "example.com"}}):
            for key in ("include", "exclude", "require"):
                with self.subTest(rule=rule, key=key):
                    body = {"name": "g", "include": [{"email": {"email": "a@example.com"}}], key: [rule]}
                    if key == "include":
                        body["include"].append(rule)
                    self.assertRefused("groups/x", body)

    def test_policies_only_allow_groups(self):
        good = {"name": "p", "decision": "allow", "include": [{"group": {"id": "g"}}]}
        for decision in ("bypass", "non_identity", "deny"):
            with self.subTest(decision=decision):
                self.assertRefused("policies", dict(good, decision=decision))
        for rule in ({"everyone": {}}, {"service_token": {"token_id": "x"}}, {"ip": {"ip": "10.0.0.0/8"}},
                     {"email": {"email": "a@example.com"}}):
            with self.subTest(rule=rule):
                self.assertRefused("policies", dict(good, include=[{"group": {"id": "g"}}, rule]))

    def test_empty_include_refused(self):
        self.assertRefused("groups", {"name": "g", "include": []})

    def test_app_inline_policy_refused(self):
        self.assertRefused("apps", {"name": "a", "policies": [{"decision": "bypass", "include": [{"everyone": {}}]}]})

    def test_setup_refuses_when_live_group_is_open(self):
        groups, policies, apps = existing_trip()
        groups[0]["include"].append({"everyone": {}})
        cf = FakeCF(groups, policies, apps)
        code, out = run(["setup", "bali-2027", "Bali 2027", "--yes"], cf)
        self.assertEqual(code, 3)
        self.assertIn("REFUSED", out)
        self.assertEqual(cf.writes(), [])

    def test_add_refuses_group_with_other_rules(self):
        groups, policies, apps = existing_trip()
        groups[1]["include"].append({"ip": {"ip": "1.2.3.4/32"}})
        cf = FakeCF(groups, policies, apps)
        code, out = run(["add", "lisbon-2025", "c@example.com"], cf)
        self.assertEqual((code, cf.writes()), (3, []))


class Credentials(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.file = Path(self.tmp.name) / "cloudflare.env"
        env = {k: v for k, v in os.environ.items() if k not in ("CF_API_TOKEN", "CF_ACCOUNT_ID")}
        patcher = mock.patch.dict(os.environ, env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        p2 = mock.patch.object(access, "CRED_FILE", self.file)
        p2.start()
        self.addCleanup(p2.stop)

    def test_missing_prints_setup_instructions(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = access.main(["list", "all"])
        self.assertEqual(code, 2)
        for s in ("Access: Apps and Policies", "Access: Organizations, Identity Providers, and Groups",
                  str(self.file), "CF_API_TOKEN=", "CF_ACCOUNT_ID="):
            self.assertIn(s, out.getvalue())

    def test_file_with_bom_and_env_override(self):
        self.file.write_text('﻿CF_API_TOKEN="from-file"\n# note\nCF_ACCOUNT_ID=acct-file\n', encoding="utf-8")
        self.assertEqual(access.load_credentials(), ("from-file", "acct-file"))
        os.environ["CF_ACCOUNT_ID"] = "acct-env"
        self.assertEqual(access.load_credentials(), ("from-file", "acct-env"))


class TokenHygiene(unittest.TestCase):
    def fake_urlopen(self, status=200, payload=None):
        def urlopen(req, timeout=None):
            self.seen.append(req)
            body = io.BytesIO(json.dumps(payload).encode())
            if status >= 400:
                raise access.urllib.error.HTTPError(req.full_url, status, "err", {}, body)
            return contextlib.nullcontext(body)
        return urlopen

    def run_real(self, argv, **kw):
        self.seen = []
        out = io.StringIO()
        with mock.patch.dict(os.environ, {"CF_API_TOKEN": TOKEN, "CF_ACCOUNT_ID": "acct"}), \
                mock.patch.object(access.urllib.request, "urlopen", self.fake_urlopen(**kw)), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = access.main(argv)
        return code, out.getvalue()

    def test_token_sent_only_as_bearer_and_never_printed(self):
        groups, _, _ = existing_trip()
        code, out = self.run_real(["list", "all"], payload={"success": True, "result": groups,
                                                          "result_info": {"total_pages": 1}})
        self.assertEqual(code, 0, out)
        self.assertNotIn(TOKEN, out)
        req = self.seen[0]
        self.assertEqual(req.get_header("Authorization"), f"Bearer {TOKEN}")
        self.assertNotIn(TOKEN, req.full_url)

    def test_api_error_never_prints_token(self):
        code, out = self.run_real(["list", "all"], status=403, payload={
            "success": False, "errors": [{"code": 10000, "message": f"Authentication error {TOKEN}"}]})
        self.assertEqual(code, 1)
        self.assertIn("Authentication error", out)
        self.assertNotIn(TOKEN, out)


if __name__ == "__main__":
    unittest.main()
