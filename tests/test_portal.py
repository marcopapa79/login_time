import sys
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from login_time.api_client import ApiResponse, QuixantHubClient  # noqa: E402
from login_time.portal import PortalTickets, find_entry_id, html_to_text, portal_hours, text_to_html  # noqa: E402
from login_time.ui import LoginWindow  # noqa: E402


class HelpersTests(unittest.TestCase):
    def test_portal_hours_formats(self):
        self.assertEqual(portal_hours("1 d 1 h"), 9)
        self.assertEqual(portal_hours("1d"), 8)
        self.assertEqual(portal_hours("8h"), 8)
        self.assertEqual(portal_hours("30 m"), 0.5)
        self.assertEqual(portal_hours("0,5h"), 0.5)
        self.assertIsNone(portal_hours(""))
        self.assertEqual(portal_hours("1 w"), 40)
        self.assertEqual(portal_hours("2 w 1 d 4 h"), 92)
        self.assertEqual(portal_hours("1 w 2 d"), 56)
        self.assertIsNone(portal_hours("1 y"))

    def test_html_text_round_trip(self):
        self.assertEqual(html_to_text("<p>Hi&nbsp;Marco,</p><ul><li>one</li><li>two</li></ul>"), "Hi Marco,\n\n• one\n• two")
        self.assertEqual(text_to_html("a < b\nriga 2\n\nsecondo"), "<p>a &lt; b<br />riga 2</p><p>secondo</p>")

    def test_find_entry_id_skips_claimed_duplicates(self):
        entries = [
            {"Id": "A", "Username": "me@x", "Month": "October 2026", "WorkingTime": "1d", "Reason": "support customer"},
            {"Id": "B", "Username": "me@x", "Month": "October 2026", "WorkingTime": "8h", "Reason": "support  customer"},
            {"Id": "C", "Username": "other@x", "Month": "October 2026", "WorkingTime": "1d", "Reason": "support customer"},
        ]
        args = dict(username="ME@x", month_label="October 2026", hours=8.0, reason="support customer")
        self.assertEqual(find_entry_id(entries, **args), "A")
        self.assertEqual(find_entry_id(entries, exclude_ids={"A"}, **args), "B")
        self.assertEqual(find_entry_id(entries, exclude_ids={"A", "B"}, **args), "")


class PortalTicketsTests(unittest.TestCase):
    def test_create_post_sends_the_page_fields(self):
        client = QuixantHubClient()
        sent = {}

        def fake_query(path, token, query=None):
            if path == "/api/tickets/newguid":
                return ApiResponse(200, {"guid": "6b6b6b01-dd21-42c7-952d-54f6430a3fb0"}, "")
            if path.startswith("/api/tickets/select/"):
                return ApiResponse(200, {"form": {"id_ticket": 3304}}, "")
            raise AssertionError(path)

        def fake_send(method, path, token=None, body=None, content_type=None):
            sent.update(method=method, path=path, body=parse_qs(body.decode()), content_type=content_type)
            return ApiResponse(200, {"id_ticket": 3304, "new_post_uuid": "b0f2", "mail_enqueue": True, "mail_error": ""}, "")

        client.request_query = fake_query
        client._send = fake_send
        with mock.patch("login_time.portal.api_log"):
            result = PortalTickets(client).create_post("tok", "BA8175AA-58CD", "ciao", public=False, time_spent="1h")

        self.assertEqual(sent["path"], "/api/ticket_posts/create")
        self.assertTrue(sent["content_type"].startswith("application/x-www-form-urlencoded"))
        self.assertEqual(sent["body"]["id_ticket"], ["3304"])
        self.assertEqual(sent["body"]["public"], ["false"])
        self.assertEqual(sent["body"]["time_spent"], ["1h"])
        self.assertEqual(sent["body"]["text"], ["<p>ciao</p>"])
        self.assertEqual(result["post_uuid"], "6b6b6b01-dd21-42c7-952d-54f6430a3fb0")


class UpdateFlowTests(unittest.TestCase):
    def window_with(self, row, list_entries):
        window = object.__new__(LoginWindow)
        window.work_logs = [row]
        window.credentials = {"username": "me@x", "password": "p"}
        window.ticket_uuid_cache = {}
        window._render_worklogs = lambda: None
        window._toast = lambda *_a, **_k: None
        window._cache_ticket_uuid = lambda *_a: None
        window.api_client = mock.Mock()
        window.sent = []

        def request_json(method, path, token, payload):
            window.sent.append(dict(payload))
            return ApiResponse(200, payload.get("Id", "NEW-ID"), "")

        window.api_client.request_json.side_effect = request_json
        window.api_client.request_query.return_value = ApiResponse(200, list_entries, "")
        return window

    def synced_row(self, **extra):
        row = {
            "ticket": "FABA-33", "entry_type": "work", "month": "October 2026", "log_date": "2026-10-29",
            "working_time": "8h", "comment": "support customer", "work_log": "support customer",
            "api_synced": "true", "api_synced_at": "2026-10-29T14:48:48+01:00",
            "api_ticket_uuid": "BA8175AA-58CD-4C65-A68D-180604210D3C", "api_month_displacement": "0",
            "api_entry_id": "", "api_pending_action": "", "api_prev_values": "", "api_resend_of": "", "api_post_uuid": "",
        }
        row.update(extra)
        return row

    def test_edit_then_sync_updates_the_existing_entry(self):
        portal_entry = {"Id": "0d71e4a4-cfce-4fea-8136-3b895dfbb624", "Username": "me@x", "Month": "October 2026",
                        "WorkingTime": "1d", "Reason": "support customer"}
        row = self.synced_row()
        window = self.window_with(row, [portal_entry])
        with mock.patch("login_time.ui.save_work_logs"), mock.patch("login_time.ui.api_log"):
            window._save_log_edit(0, "6h", "support customer + test", mock.Mock(), mode="update")
            self.assertEqual(row["api_pending_action"], "update")
            self.assertIn("8h", row["api_prev_values"])
            window._sync_row_with_portal("tok", row)

        self.assertEqual(window.sent[-1]["Id"], "0d71e4a4-cfce-4fea-8136-3b895dfbb624")
        self.assertEqual(window.sent[-1]["WorkingTime"], "6h")
        self.assertEqual(row["api_synced"], "true")
        self.assertEqual(row["api_pending_action"], "")
        self.assertEqual(row["api_entry_id"], "0D71E4A4-CFCE-4FEA-8136-3B895DFBB624")

    def test_update_without_portal_match_fails_instead_of_duplicating(self):
        row = self.synced_row(api_pending_action="update", api_synced="")
        window = self.window_with(row, [])
        with mock.patch("login_time.ui.api_log"):
            with self.assertRaises(RuntimeError):
                window._sync_row_with_portal("tok", row)
        self.assertEqual(window.sent, [])


if __name__ == "__main__":
    unittest.main()
