import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from login_time import api_log, config, jira_client  # noqa: E402
from login_time.jira_client import JiraAuthError, JiraClient, adf_to_text, clean_text, format_started, text_to_adf  # noqa: E402
from login_time.jira_page import jira_date, status_of  # noqa: E402

import fake_jira  # noqa: E402


class AdfTests(unittest.TestCase):
    def test_text_to_adf_keeps_paragraphs_and_line_breaks(self):
        doc = text_to_adf("Ciao\nseconda riga\n\nNuovo paragrafo")
        self.assertEqual(doc["type"], "doc")
        self.assertEqual(len(doc["content"]), 2)
        first = doc["content"][0]["content"]
        self.assertEqual([n["type"] for n in first], ["text", "hardBreak", "text"])
        self.assertEqual(clean_text(adf_to_text(doc)), "Ciao\nseconda riga\n\nNuovo paragrafo")

    def test_adf_to_text_handles_mentions_lists_and_links(self):
        doc = {
            "type": "doc",
            "content": [
                {"type": "paragraph", "content": [{"type": "mention", "attrs": {"text": "@Giulia"}}, {"type": "text", "text": " guarda qui"}]},
                {"type": "bulletList", "content": [
                    {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "uno"}]}]},
                    {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "due"}]}]},
                ]},
                {"type": "paragraph", "content": [{"type": "inlineCard", "attrs": {"url": "https://example.com/x"}}]},
            ],
        }
        text = clean_text(adf_to_text(doc))
        self.assertIn("@Giulia guarda qui", text)
        self.assertIn("• uno", text)
        self.assertIn("• due", text)
        self.assertIn("https://example.com/x", text)

    def test_empty_values(self):
        self.assertEqual(adf_to_text(None), "")
        self.assertEqual(adf_to_text("plain"), "plain")


class FormatTests(unittest.TestCase):
    def test_format_started_uses_jira_format(self):
        moment = datetime(2026, 10, 30, 9, 0, tzinfo=timezone(timedelta(hours=1)))
        self.assertEqual(format_started(moment), "2026-10-30T09:00:00.000+0100")

    def test_format_started_naive_gets_local_offset(self):
        text = format_started(datetime(2026, 10, 30, 9, 30))
        self.assertRegex(text, r"^2026-10-30T09:30:00\.000[+-]\d{4}$")

    def test_jira_date_and_status(self):
        self.assertEqual(jira_date("2026-11-05", with_time=False), "05/11/2026")
        self.assertEqual(jira_date(""), "")
        self.assertRegex(jira_date("2026-10-29T16:20:00.000+0100"), r"^\d{2}/\d{2}/2026 \d{2}:\d{2}$")
        self.assertEqual(status_of({"status": {"name": "Done", "statusCategory": {"key": "done"}}}), ("Done", "synced"))
        self.assertEqual(status_of({}), ("", "neutral"))


class JiraClientTests(unittest.TestCase):
    def setUp(self):
        self.fake = fake_jira.FakeJira().start()
        self.addCleanup(self.fake.stop)
        patcher = mock.patch.object(jira_client, "GATEWAY", self.fake.url + "/ex/jira")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.logged: list[str] = []
        for name in ("request", "response", "event"):
            patcher = mock.patch.object(api_log, name, side_effect=lambda *a, **k: self.logged.append(repr((a, k))))
            patcher.start()
            self.addCleanup(patcher.stop)

    def client(self, token=fake_jira.CLASSIC_TOKEN):
        return JiraClient(self.fake.url, fake_jira.EMAIL, token, timeout=5)

    def test_classic_token_uses_the_site(self):
        client = self.client()
        me = client.myself()
        self.assertEqual(me["displayName"], "Marco Papa")
        self.assertFalse(client.uses_gateway)

    def test_scoped_token_switches_to_the_gateway(self):
        client = self.client(fake_jira.SCOPED_TOKEN)
        self.assertEqual(client.myself()["displayName"], "Marco Papa")
        self.assertTrue(client.uses_gateway)
        issues, _ = client.search("assignee = currentUser()")
        self.assertTrue(issues)
        self.assertTrue(self.fake.requests[-1][1].startswith(f"/ex/jira/{fake_jira.CLOUD_ID}/rest/api/3/search/jql"))

    def test_wrong_token_raises_auth_error(self):
        with self.assertRaises(JiraAuthError):
            self.client("wrong").myself()

    def test_search_payload_and_pagination(self):
        client = self.client()
        issues, token = client.search("assignee = currentUser() AND statusCategory != Done", max_results=2)
        self.assertEqual([i["key"] for i in issues], ["PF-412", "PF-398"])
        self.assertEqual(token, "2")
        method, _path, body = self.fake.requests[-1]
        self.assertEqual(method, "POST")
        self.assertEqual(body["jql"], "assignee = currentUser() AND statusCategory != Done")
        self.assertIn("summary", body["fields"])
        more, token = client.search("assignee = currentUser() AND statusCategory != Done", max_results=2, next_page_token=token)
        self.assertEqual([i["key"] for i in more], ["CS-77"])
        self.assertIsNone(token)
        self.assertEqual(self.fake.requests[-1][2]["nextPageToken"], "2")

    def test_issue_comments_transitions(self):
        client = self.client()
        issue = client.issue("PF-412")
        self.assertIn("boot", clean_text(adf_to_text(issue["fields"]["description"])))
        self.assertIn("fields=summary", self.fake.requests[-1][1])
        comments = client.comments("PF-412")
        self.assertEqual(comments[0]["author"]["displayName"], "Giulia Rossi")
        self.assertIn("orderBy=-created", self.fake.requests[-1][1])
        names = [t["name"] for t in client.transitions("PF-412")]
        self.assertEqual(names, ["To Do", "In Progress", "Done"])
        client.transition("PF-412", "31")
        self.assertEqual(self.fake.transitions_done, [("PF-412", "31")])
        self.assertEqual(self.fake.requests[-1][2], {"transition": {"id": "31"}})

    def test_add_comment_and_worklog_bodies(self):
        client = self.client()
        client.add_comment("PF-412", "Fatto\nil test")
        body = self.fake.requests[-1][2]["body"]
        self.assertEqual(body["type"], "doc")
        client.add_worklog("PF-412", 5400, datetime(2026, 10, 30, 14, 0, tzinfo=timezone(timedelta(hours=1))), "Analisi log")
        worklog = self.fake.worklogs[-1]
        self.assertEqual(worklog["timeSpentSeconds"], 5400)
        self.assertEqual(worklog["started"], "2026-10-30T14:00:00.000+0100")
        self.assertEqual(clean_text(adf_to_text(worklog["comment"])), "Analisi log")
        client.add_worklog("PF-398", 3600, datetime(2026, 10, 30, 9, 0, tzinfo=timezone.utc))
        self.assertNotIn("comment", self.fake.worklogs[-1])

    def test_token_never_reaches_the_log(self):
        client = self.client()
        client.myself()
        client.add_comment("PF-412", "ciao")
        self.assertTrue(self.fake.auth_headers)  # the header was really sent…
        joined = "\n".join(self.logged)
        self.assertNotIn(fake_jira.CLASSIC_TOKEN, joined)  # …but never logged
        self.assertNotIn(self.fake.auth_headers[0], joined)
        self.assertIn("jira /rest/api/3/myself", joined)

    def test_unknown_issue_gives_readable_error(self):
        with self.assertRaises(RuntimeError) as ctx:
            self.client().issue("XX-1")
        self.assertIn("does not exist", str(ctx.exception))


class FakeTargetStore:
    JIRA_TARGET_PREFIX = "login_time/jira:"

    def __init__(self, supported=True, writable=True):
        self.supported = supported
        self.writable = writable
        self.items: dict[str, tuple[str, str]] = {}

    def is_supported(self):
        return self.supported

    def read_credential(self, target="login_time/support.quixant.com"):
        return self.items.get(target)

    def write_credential(self, username, password, target="login_time/support.quixant.com", comment=""):
        if not self.writable:
            return False
        self.items[target] = (username, password)
        return True

    def delete_credential(self, target="login_time/support.quixant.com"):
        self.items.pop(target, None)
        return True


class JiraSettingsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.file = Path(self.tmp.name) / "jira_settings.json"
        patcher = mock.patch.object(config, "_JIRA_SETTINGS_FILE", self.file)
        patcher.start()
        self.addCleanup(patcher.stop)

    def use_store(self, store):
        patcher = mock.patch.object(config, "credentials_store", store)
        patcher.start()
        self.addCleanup(patcher.stop)
        return store

    def test_defaults_without_file(self):
        self.use_store(FakeTargetStore())
        self.assertEqual(config.load_jira_settings(), ("https://quixantplc.atlassian.net", "", False))

    def test_token_goes_to_credential_manager_not_to_the_file(self):
        store = self.use_store(FakeTargetStore())
        config.save_jira_settings("https://quixantplc.atlassian.net", "u@x.com", "tok-secret")
        self.assertEqual(store.items["login_time/jira:quixantplc.atlassian.net"], ("u@x.com", "tok-secret"))
        saved = json.loads(self.file.read_text(encoding="utf-8"))
        self.assertEqual(saved, {"site": "https://quixantplc.atlassian.net", "email": "u@x.com"})
        self.assertNotIn("tok-secret", self.file.read_text(encoding="utf-8"))
        self.assertEqual(config.load_jira_settings(), ("https://quixantplc.atlassian.net", "u@x.com", True))
        self.assertEqual(config.load_jira_token("https://quixantplc.atlassian.net"), "tok-secret")

    def test_windows_store_failure_never_writes_the_token_in_clear(self):
        self.use_store(FakeTargetStore(writable=False))
        with self.assertRaises(RuntimeError):
            config.save_jira_settings("https://quixantplc.atlassian.net", "u@x.com", "tok-secret")
        self.assertFalse(self.file.exists() and "tok-secret" in self.file.read_text(encoding="utf-8"))

    def test_forget_removes_the_token(self):
        store = self.use_store(FakeTargetStore())
        config.save_jira_settings("https://quixantplc.atlassian.net", "u@x.com", "tok-secret")
        config.forget_jira_token("https://quixantplc.atlassian.net")
        self.assertEqual(store.items, {})
        self.assertEqual(config.load_jira_settings(), ("https://quixantplc.atlassian.net", "u@x.com", False))

    def test_quixant_password_entry_is_separate(self):
        store = self.use_store(FakeTargetStore())
        store.items["login_time/support.quixant.com"] = ("u@x.com", "portal-pw")
        config.save_jira_settings("https://quixantplc.atlassian.net", "u@x.com", "tok-secret")
        config.forget_jira_token("https://quixantplc.atlassian.net")
        self.assertEqual(store.items, {"login_time/support.quixant.com": ("u@x.com", "portal-pw")})


if __name__ == "__main__":
    unittest.main()
