"""Jira login with Atlassian OAuth (browser + Microsoft + Duo), against a local fake Atlassian."""

import json
import socket
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock
from urllib import parse, request
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from login_time import api_log, config, jira_client, jira_oauth  # noqa: E402
from login_time.jira_client import JiraAuthError, JiraClient  # noqa: E402
from login_time.jira_oauth import OAuthError, OAuthLoginRequired, OAuthSession  # noqa: E402

import fake_jira  # noqa: E402
from test_jira import FakeTargetStore  # noqa: E402


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class Browser:
    """Stands in for the user's browser: after "Microsoft + Duo" it follows Atlassian's redirect."""

    def __init__(self, port: int, *, code=fake_jira.AUTH_CODE, error=None, state_override=None, delay=0.05, act=True):
        self.port, self.code, self.error, self.state_override, self.delay, self.act = port, code, error, state_override, delay, act
        self.opened: list[str] = []
        self.pages: list[tuple[int, str]] = []

    def get(self, query: dict) -> None:
        url = f"http://127.0.0.1:{self.port}/callback?{parse.urlencode(query)}"
        try:
            with request.urlopen(url, timeout=5) as response:
                self.pages.append((response.status, response.read().decode("utf-8")))
        except HTTPError as exc:
            self.pages.append((exc.code, exc.read().decode("utf-8")))

    def __call__(self, url: str) -> None:
        self.opened.append(url)
        if not self.act:
            return
        state = parse.parse_qs(parse.urlparse(url).query)["state"][0]

        def follow() -> None:
            time.sleep(self.delay)
            if self.state_override is not None:
                self.get({"code": "stolen", "state": self.state_override})
            query = {"error": self.error, "state": state} if self.error else {"code": self.code, "state": state}
            self.get(query)

        threading.Thread(target=follow, daemon=True).start()


class OAuthTestBase(unittest.TestCase):
    def setUp(self):
        self.fake = fake_jira.FakeJira().start()
        self.addCleanup(self.fake.stop)
        self.logged: list[str] = []
        patcher = mock.patch.object(jira_client, "GATEWAY", self.fake.url + "/ex/jira")
        patcher.start()
        self.addCleanup(patcher.stop)
        for name in ("request", "response", "event"):
            patcher = mock.patch.object(api_log, name, side_effect=lambda *a, **k: self.logged.append(repr((a, k))))
            patcher.start()
            self.addCleanup(patcher.stop)
        self.token_url = self.fake.url + "/oauth/token"
        self.resources_url = self.fake.url + "/oauth/token/accessible-resources"

    def login(self, browser=None, site=fake_jira.SITE_URL, client_id=fake_jira.CLIENT_ID, secret=fake_jira.CLIENT_SECRET, cancel=None):
        port = browser.port if browser else free_port()
        browser = browser or Browser(port)
        return jira_oauth.login(
            site, client_id, secret, cancel=cancel or threading.Event(), open_browser=browser,
            port=port, token_url=self.token_url, resources_url=self.resources_url, timeout=5,
        ), browser


class AuthorizeUrlTests(unittest.TestCase):
    def test_same_url_as_the_developer_console_plus_offline_access(self):
        url = jira_oauth.authorize_url("hV5yQfkZLMe7AEa0pZk00E8ByLUkb6g6", "st4te")
        parsed = parse.urlparse(url)
        query = parse.parse_qs(parsed.query)
        self.assertEqual(f"{parsed.scheme}://{parsed.netloc}{parsed.path}", "https://auth.atlassian.com/authorize")
        self.assertEqual(query["audience"], ["api.atlassian.com"])
        self.assertEqual(query["client_id"], ["hV5yQfkZLMe7AEa0pZk00E8ByLUkb6g6"])
        self.assertEqual(query["scope"], ["read:jira-work write:jira-work read:jira-user offline_access"])
        self.assertEqual(query["redirect_uri"], ["http://localhost:53682/callback"])
        self.assertEqual(query["state"], ["st4te"])
        self.assertEqual(query["response_type"], ["code"])
        self.assertEqual(query["prompt"], ["consent"])
        self.assertIn("scope=read%3Ajira-work%20write%3Ajira-work", url)  # %20 like the console, not "+"


class BrowserLoginTests(OAuthTestBase):
    def test_full_login_gives_a_working_session(self):
        result, browser = self.login()
        self.assertEqual(len(browser.opened), 1)
        self.assertEqual(browser.pages[-1][0], 200)
        self.assertIn("Login ricevuto", browser.pages[-1][1])
        self.assertEqual(result.session.cloud_id, fake_jira.CLOUD_ID)
        self.assertEqual(result.site_url, fake_jira.SITE_URL)
        self.assertTrue(result.session.refresh_token.startswith("rt-"))
        client = JiraClient(result.site_url, "", oauth=result.session, timeout=5)
        self.assertEqual(client.myself()["displayName"], "Marco Papa")
        self.assertTrue(client.uses_oauth and client.uses_gateway)
        self.assertTrue(self.fake.requests[-1][1].startswith(f"/ex/jira/{fake_jira.CLOUD_ID}/rest/api/3/myself"))
        self.assertTrue(self.fake.auth_headers[-1].startswith("Bearer at-"))

    def test_a_link_with_another_state_is_ignored(self):
        port = free_port()
        browser = Browser(port, state_override="not-ours")
        result, _ = self.login(browser)
        self.assertEqual(browser.pages[0][0], 400)  # the foreign link was refused…
        self.assertEqual(result.session.cloud_id, fake_jira.CLOUD_ID)  # …and the real one worked

    def test_cancel_on_the_consent_page(self):
        browser = Browser(free_port(), error="access_denied")
        with self.assertRaises(OAuthError) as ctx:
            self.login(browser)
        self.assertIn("Annulla", str(ctx.exception))

    def test_user_can_cancel_while_waiting(self):
        cancel = threading.Event()
        browser = Browser(free_port(), act=False)
        threading.Timer(0.3, cancel.set).start()
        started = time.monotonic()
        with self.assertRaises(OAuthError) as ctx:
            self.login(browser, cancel=cancel)
        self.assertIn("annullato", str(ctx.exception))
        self.assertLess(time.monotonic() - started, 3)
        # The port is free again for the next attempt.
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", browser.port))

    def test_ipv6_localhost_also_works(self):
        if not socket.has_ipv6:
            self.skipTest("no IPv6")
        port = free_port()
        try:
            with socket.socket(socket.AF_INET6) as probe:
                probe.bind(("::1", port))
        except OSError:
            self.skipTest("no IPv6 loopback")

        class Browser6(Browser):
            def get(self, query):
                url = f"http://[::1]:{self.port}/callback?{parse.urlencode(query)}"
                with request.urlopen(url, timeout=5) as response:
                    self.pages.append((response.status, response.read().decode("utf-8")))

        result, browser = self.login(Browser6(port))
        self.assertEqual(browser.pages[-1][0], 200)
        self.assertEqual(result.session.cloud_id, fake_jira.CLOUD_ID)

    def test_callback_listens_on_loopback_only(self):
        shared = jira_oauth._Shared("s")
        servers = jira_oauth._open_servers(free_port(), shared)
        try:
            self.assertTrue(all(server.server_address[0] in ("127.0.0.1", "::1") for server in servers))
        finally:
            for server in servers:
                server.server_close()

    def test_busy_port_is_explained(self):
        with socket.socket() as busy:
            busy.bind(("127.0.0.1", 0))
            busy.listen()
            browser = Browser(busy.getsockname()[1], act=False)
            with self.assertRaises(OAuthError) as ctx:
                self.login(browser)
        self.assertIn("occupata", str(ctx.exception))
        self.assertEqual(browser.opened, [])

    def test_wrong_secret(self):
        with self.assertRaises(OAuthError) as ctx:
            self.login(secret="wrong")
        self.assertIn("Client ID e Secret", str(ctx.exception))

    def test_site_not_authorized(self):
        self.fake.resource_url = "https://other.atlassian.net"
        with self.assertRaises(OAuthError) as ctx:
            self.login()
        self.assertIn("quixantplc.atlassian.net", str(ctx.exception))
        self.assertIn("other.atlassian.net", str(ctx.exception))

    def test_missing_scope(self):
        self.fake.resource_scopes = ["read:jira-work"]
        with self.assertRaises(OAuthError) as ctx:
            self.login()
        self.assertIn("write:jira-work", str(ctx.exception))

    def test_secrets_never_reach_the_log(self):
        result, _ = self.login()
        client = JiraClient(result.site_url, "", oauth=result.session, timeout=5)
        client.myself()
        self.fake.expire_access_tokens()
        client.myself()  # forces a refresh
        joined = "\n".join(self.logged)
        for secret in (fake_jira.CLIENT_SECRET, fake_jira.AUTH_CODE, "rt-1-", "rt-2-", "at-1", "at-2"):
            self.assertNotIn(secret, joined)
        self.assertIn("scambio del codice", joined)


class SessionTests(OAuthTestBase):
    def session(self):
        result, _ = self.login()
        rotated: list[str] = []
        result.session.on_rotate = rotated.append
        return result.session, rotated

    def test_expired_access_token_is_refreshed_and_rotation_is_saved(self):
        session, rotated = self.session()
        client = JiraClient(fake_jira.SITE_URL, "", oauth=session, timeout=5)
        first_refresh = session.refresh_token
        self.fake.expire_access_tokens()  # Atlassian refuses the current access token
        self.assertEqual(client.myself()["displayName"], "Marco Papa")
        self.assertEqual(self.fake.grants, ["authorization_code", "refresh_token"])
        self.assertNotEqual(session.refresh_token, first_refresh)
        self.assertEqual(rotated, [session.refresh_token])
        self.assertNotIn(first_refresh, self.fake.refresh_tokens)

    def test_refresh_before_expiry(self):
        session, rotated = self.session()
        session._expires_at = time.time() + 10  # inside the safety margin
        JiraClient(fake_jira.SITE_URL, "", oauth=session, timeout=5).myself()
        self.assertEqual(self.fake.grants.count("refresh_token"), 1)
        self.assertEqual(len(rotated), 1)

    def test_parallel_calls_refresh_only_once(self):
        session, rotated = self.session()
        session._access = ""
        client = JiraClient(fake_jira.SITE_URL, "", oauth=session, timeout=5)
        errors: list[BaseException] = []

        def call():
            try:
                client.myself()
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=call) for _ in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        self.assertEqual(self.fake.grants.count("refresh_token"), 1)
        self.assertEqual(len(rotated), 1)

    def test_revoked_or_expired_login_asks_for_duo_again(self):
        session, _ = self.session()
        self.fake.refresh_tokens.clear()
        self.fake.expire_access_tokens()
        with self.assertRaises(JiraAuthError) as ctx:
            JiraClient(fake_jira.SITE_URL, "", oauth=session, timeout=5).myself()
        self.assertIn("Duo", str(ctx.exception))

    def test_forget_drops_everything_from_memory(self):
        session, _ = self.session()
        session.forget()
        self.assertEqual(session.refresh_token, "")
        with self.assertRaises(OAuthLoginRequired):
            session.access_token()


class OAuthSettingsTests(unittest.TestCase):
    site = "https://quixantplc.atlassian.net"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.file = Path(self.tmp.name) / "jira_settings.json"
        self.store = FakeTargetStore()
        for patcher in (
            mock.patch.object(config, "_JIRA_SETTINGS_FILE", self.file),
            mock.patch.object(config, "credentials_store", self.store),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.store.JIRA_OAUTH_TARGET_PREFIX = "login_time/jira-oauth:"

    def test_secrets_go_to_credential_manager_and_old_token_is_removed(self):
        config.save_jira_settings(self.site, "u@x.com", "old-api-token")
        long_refresh = "rt-" + "x" * 2600
        config.save_jira_oauth(self.site, "u@x.com", "cid", "cloud-1", "the-secret", long_refresh)

        text = self.file.read_text(encoding="utf-8")
        self.assertEqual(json.loads(text), {
            "site": self.site, "email": "u@x.com", "auth": "oauth", "oauth_client_id": "cid", "oauth_cloud_id": "cloud-1",
        })
        self.assertNotIn("the-secret", text)
        self.assertNotIn("rt-", text)
        self.assertNotIn("login_time/jira:quixantplc.atlassian.net", self.store.items)  # API token gone
        # Long refresh token split over several entries, each small enough for Credential Manager.
        parts = [k for k in self.store.items if k.startswith("login_time/jira-oauth:quixantplc.atlassian.net")]
        self.assertGreater(len(parts), 2)
        self.assertTrue(all(len(v[1]) <= 1100 for v in self.store.items.values()))

        loaded = config.load_jira_oauth()
        self.assertEqual((loaded.client_id, loaded.cloud_id, loaded.client_secret, loaded.refresh_token),
                         ("cid", "cloud-1", "the-secret", long_refresh))
        self.assertEqual(config.load_jira_settings(), (self.site, "u@x.com", False))

    def test_rotation_replaces_the_refresh_token_and_cleans_old_parts(self):
        config.save_jira_oauth(self.site, "u@x.com", "cid", "cloud-1", "the-secret", "rt-" + "x" * 2600)
        config.save_jira_oauth_refresh(self.site, "rt-short")
        loaded = config.load_jira_oauth()
        self.assertEqual(loaded.refresh_token, "rt-short")
        self.assertEqual(loaded.client_secret, "the-secret")
        self.assertEqual([k for k in self.store.items if "#" in k], [])

    def test_app_saved_before_the_first_login(self):
        config.save_jira_oauth_app(self.site, "u@x.com", "cid", "the-secret")
        loaded = config.load_jira_oauth()
        self.assertEqual((loaded.client_id, loaded.client_secret, loaded.refresh_token), ("cid", "the-secret", ""))

    def test_disconnect_keeps_the_app_unless_asked(self):
        config.save_jira_oauth(self.site, "u@x.com", "cid", "cloud-1", "the-secret", "rt-1")
        config.forget_jira_oauth(self.site, keep_app=True)
        loaded = config.load_jira_oauth()
        self.assertEqual((loaded.client_secret, loaded.refresh_token), ("the-secret", ""))
        config.forget_jira_oauth(self.site, keep_app=False)
        self.assertIsNone(config.load_jira_oauth())
        self.assertEqual(self.store.items, {})
        self.assertNotIn("oauth", self.file.read_text(encoding="utf-8"))

    def test_token_setup_keeps_the_oauth_app_id(self):
        config.save_jira_oauth_app(self.site, "u@x.com", "cid", "the-secret")
        config.save_jira_settings(self.site, "u@x.com", "api-token")
        data = json.loads(self.file.read_text(encoding="utf-8"))
        self.assertEqual(data.get("oauth_client_id"), "cid")
        self.assertNotIn("auth", data)  # back to the API token
        self.assertIsNone(config.load_jira_oauth())


if __name__ == "__main__":
    unittest.main()
