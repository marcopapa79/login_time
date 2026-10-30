import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from login_time import config, credentials_store  # noqa: E402
from login_time.ui import LoginWindow  # noqa: E402


class FakeStore:
    def __init__(self, stored=None, writable=True):
        self.stored = stored
        self.writable = writable

    def is_supported(self):
        return True

    def read_credential(self):
        return self.stored

    def write_credential(self, username, password):
        if not self.writable:
            return False
        self.stored = (username, password)
        return True

    def delete_credential(self):
        self.stored = None
        return True


class CredentialStorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cred_file = Path(self.tmp.name) / "credentials.json"
        patcher = mock.patch.object(config, "_CREDENTIALS_FILE", self.cred_file)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    def use_store(self, store):
        patcher = mock.patch.object(config, "credentials_store", store)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_plain_text_password_is_moved_out_of_the_file(self):
        store = FakeStore()
        self.use_store(store)
        self.cred_file.write_text(json.dumps({"username": "u@x.com", "password": "secret"}), encoding="utf-8")

        creds = config.load_credentials()

        self.assertEqual(creds, {"username": "u@x.com", "password": "secret"})
        self.assertEqual(store.stored, ("u@x.com", "secret"))
        self.assertEqual(json.loads(self.cred_file.read_text(encoding="utf-8")), {"username": "u@x.com"})

    def test_password_stays_in_file_if_store_write_fails(self):
        self.use_store(FakeStore(writable=False))
        self.cred_file.write_text(json.dumps({"username": "u@x.com", "password": "secret"}), encoding="utf-8")

        config.load_credentials()

        self.assertEqual(json.loads(self.cred_file.read_text(encoding="utf-8"))["password"], "secret")

    def test_save_writes_only_username_to_file(self):
        store = FakeStore()
        self.use_store(store)

        config.save_credentials("u@x.com", "new-secret")

        self.assertEqual(store.stored, ("u@x.com", "new-secret"))
        self.assertNotIn("password", json.loads(self.cred_file.read_text(encoding="utf-8")))
        self.assertEqual(config.load_credentials()["password"], "new-secret")

    def test_forget_removes_password_and_keeps_email(self):
        store = FakeStore(stored=("u@x.com", "secret"))
        self.use_store(store)
        self.cred_file.write_text(json.dumps({"username": "u@x.com"}), encoding="utf-8")

        config.forget_saved_password()

        self.assertIsNone(store.stored)
        self.assertEqual(json.loads(self.cred_file.read_text(encoding="utf-8")), {"username": "u@x.com"})
        self.assertEqual(config.load_saved_username(), ("u@x.com", False))

    def test_load_saved_username_does_not_return_the_password(self):
        self.use_store(FakeStore(stored=("u@x.com", "secret")))
        self.cred_file.write_text(json.dumps({"username": "u@x.com"}), encoding="utf-8")
        self.assertEqual(config.load_saved_username(), ("u@x.com", True))

    def test_non_windows_store_is_not_supported(self):
        if sys.platform != "win32":
            self.assertFalse(credentials_store.is_supported())
            self.assertIsNone(credentials_store.read_credential())


class LoginFlowTests(unittest.TestCase):
    """_handle_login with the password field empty / typed (no Tk window needed)."""

    def make_window(self, *, saved_user="u@x.com", saved_password="secret", typed_user="u@x.com", typed_password="", remember=False):
        window = object.__new__(LoginWindow)
        window.has_saved_password = bool(saved_password)
        window.credentials = {"username": saved_user, "password": ""}
        window.api_token = ""
        window.api_token_user = ""
        window.user_entry = mock.Mock(get=mock.Mock(return_value=typed_user))
        window.pass_entry = mock.Mock(get=mock.Mock(return_value=typed_password))
        window.remember_var = mock.Mock(get=mock.Mock(return_value=remember))
        window.login_error = mock.Mock()
        window._show_dashboard = mock.Mock()
        self.loader = mock.patch("login_time.ui.load_credentials", return_value={"username": saved_user, "password": saved_password})
        self.saver = mock.patch("login_time.ui.save_credentials")
        self.loader.start()
        self.save_mock = self.saver.start()
        self.addCleanup(self.loader.stop)
        self.addCleanup(self.saver.stop)
        return window

    def test_empty_field_uses_the_saved_password(self):
        window = self.make_window()
        window._handle_login()
        window._show_dashboard.assert_called_once()
        self.assertEqual(window.credentials["password"], "secret")
        window.pass_entry.delete.assert_called_once()

    def test_empty_field_without_saved_password_is_refused(self):
        window = self.make_window(saved_password="")
        window._handle_login()
        window._show_dashboard.assert_not_called()

    def test_different_password_needs_remember(self):
        window = self.make_window(typed_password="other")
        window._handle_login()
        window._show_dashboard.assert_not_called()
        window = self.make_window(typed_password="other", remember=True)
        window._handle_login()
        self.save_mock.assert_called_once_with("u@x.com", "other")
        self.assertEqual(window.credentials["password"], "other")

    def test_logout_clears_password_and_token(self):
        window = object.__new__(LoginWindow)
        window.credentials = {"username": "u@x.com", "password": "secret"}
        window.api_token = "tok"
        window.api_token_user = "u@x.com"
        window.clockify_user_uuid = "x"
        window._clear_session_secrets()
        self.assertEqual(window.credentials, {"username": "u@x.com", "password": ""})
        self.assertEqual(window.api_token, "")


class EditAndResendTests(unittest.TestCase):
    def make_window(self, row):
        window = object.__new__(LoginWindow)
        window.work_logs = [row]
        window._render_worklogs = lambda: None
        window._toast = lambda *_a, **_k: None
        return window

    def synced_row(self):
        return {
            "working_time": "4h",
            "work_log": "old",
            "comment": "old",
            "api_synced": "true",
            "api_synced_at": "2026-10-20T17:30:00+02:00",
            "api_ticket_uuid": "AAAA",
            "api_month_displacement": "0",
            "api_resend_of": "",
        }

    def test_local_only_edit_keeps_sync_state(self):
        row = self.synced_row()
        window = self.make_window(row)
        with mock.patch("login_time.ui.save_work_logs"):
            window._save_log_edit(0, "5h", "fixed", mock.Mock(), resend=False)
        self.assertEqual(row["working_time"], "5h")
        self.assertEqual(row["api_synced"], "true")
        self.assertEqual(row["api_resend_of"], "")

    def test_resend_edit_marks_previous_sync(self):
        row = self.synced_row()
        window = self.make_window(row)
        with mock.patch("login_time.ui.save_work_logs"):
            window._save_log_edit(0, "5h", "fixed", mock.Mock(), resend=True)
        self.assertEqual(row["api_synced"], "")
        self.assertEqual(row["api_resend_of"], "2026-10-20T17:30:00+02:00")

    def test_confirm_resend_can_skip_edited_rows(self):
        window = object.__new__(LoginWindow)
        fresh = {"ticket": "QUIX-1", "api_resend_of": "", "log_date": "2026-10-21", "working_time": "1h"}
        edited = {"ticket": "QUIX-2", "api_resend_of": "2026-10-20T17:30:00+02:00", "log_date": "2026-10-20", "working_time": "2h"}
        with mock.patch("login_time.ui.messagebox.askyesnocancel", return_value=False):
            self.assertEqual(window._confirm_resend_rows([fresh, edited]), [fresh])
        with mock.patch("login_time.ui.messagebox.askyesnocancel", return_value=None):
            self.assertIsNone(window._confirm_resend_rows([fresh, edited]))


class SyncRowTests(unittest.TestCase):
    def test_work_row_is_sent_and_marked_on_the_copy(self):
        window = object.__new__(LoginWindow)
        sent = []
        window.api_client = mock.Mock()
        from login_time.api_client import ApiResponse

        def fake_request(*args):
            sent.append(args)
            return ApiResponse(200, "0d71e4a4-cfce-4fea-8136-3b895dfbb624", "")

        window.api_client.request_json.side_effect = fake_request
        window._build_api_payload_for_row = lambda row, token: ("UUID-1", {"MonthDisplacement": "-1"})
        window._cache_ticket_uuid = lambda *_a: None
        row = {"ticket": "QUIX-707", "entry_type": "work", "api_synced": ""}

        with mock.patch("login_time.ui.api_log"):
            window._sync_row_with_portal("token", row)

        self.assertEqual(sent[0][1], "/api/working_hours/form")
        self.assertEqual(row["api_synced"], "true")
        self.assertEqual(row["api_ticket_uuid"], "UUID-1")
        self.assertEqual(row["api_month_displacement"], "-1")
        self.assertEqual(row["api_entry_id"], "0D71E4A4-CFCE-4FEA-8136-3B895DFBB624")


class TicketResolutionTests(unittest.TestCase):
    PAYLOAD = {
        "data": [
            {"internal_id": "SFTC-33", "uuid": "b83dce9a-1ca0-4f55-9819-90c175a34775"},
            {"internal_id": "QUIX-707", "uuid": "79a15ca4-aea5-48df-854b-0e45d891bcd7"},
            {"internal_id": "FABA-33", "uuid": "11111111-2222-3333-4444-555555555555"},
        ]
    }

    def client(self, payloads):
        from login_time.api_client import ApiResponse, QuixantHubClient

        client = QuixantHubClient()
        calls = iter(payloads)
        client.request_query = lambda *_a, **_k: ApiResponse(200, next(calls), "")
        return client

    def test_faba_33_never_resolves_to_sftc_33(self):
        client = self.client([self.PAYLOAD])
        uuid, matched, _source = client.resolve_ticket("tok", "FABA-33")
        self.assertEqual(matched, "FABA-33")
        self.assertEqual(uuid, "11111111-2222-3333-4444-555555555555")

    def test_exact_match_in_a_later_list_beats_a_number_only_match(self):
        first = {"data": [{"internal_id": "33", "uuid": "aaaaaaaa-0000-0000-0000-000000000000"}]}
        second = {"data": [{"internal_id": "FABA-33", "uuid": "bbbbbbbb-0000-0000-0000-000000000000"}]}
        client = self.client([first, second, {}, {}, {}, {}])
        self.assertEqual(client.resolve_ticket("tok", "FABA-33")[1], "FABA-33")

    def test_different_prefixes_do_not_match(self):
        from login_time.api_client import QuixantHubClient

        client = QuixantHubClient()
        self.assertFalse(client._ticket_matches("SFTC-33", "FABA-33"))
        self.assertTrue(client._ticket_matches("707", "QUIX-707"))
        self.assertTrue(client._ticket_matches("quix-707", "QUIX-707"))

    def test_mismatched_code_from_portal_blocks_the_send(self):
        window = object.__new__(LoginWindow)
        window.ticket_uuid_cache = {}
        window.api_client = mock.Mock()
        window.api_client.resolve_ticket.return_value = ("B83DCE9A-1CA0-4F55-9819-90C175A34775", "SFTC-33", "list2")
        window._cache_ticket_uuid = mock.Mock()
        with mock.patch("login_time.ui.api_log"):
            with self.assertRaises(RuntimeError):
                window._resolve_ticket_uuid_cached("tok", "FABA-33")
        window._cache_ticket_uuid.assert_not_called()


class ApiLogTests(unittest.TestCase):
    def test_password_and_token_are_masked(self):
        from login_time import api_log

        masked = api_log.mask_secrets({"username": "u", "password": "p", "nested": [{"accessToken": "t"}]})
        self.assertEqual(masked, {"username": "u", "password": "***", "nested": [{"accessToken": "***"}]})
        self.assertNotIn("secret", api_log._body_text(b"username=u&password=secret"))


class DateHelpersTests(unittest.TestCase):
    def test_business_days_skip_weekends_and_holidays(self):
        window = object.__new__(LoginWindow)
        # 30/10/2026 Fri, 31 Sat, 1/11 Sun (holiday anyway), 2/11 Mon
        days = window._business_days_between(date(2026, 10, 30), date(2026, 11, 2))
        self.assertEqual(days, [date(2026, 10, 30), date(2026, 11, 2)])

    def test_parse_user_date_formats(self):
        window = object.__new__(LoginWindow)
        self.assertEqual(window._parse_user_date("23/10/2026"), date(2026, 10, 23))
        self.assertEqual(window._parse_user_date("2026-10-23"), date(2026, 10, 23))
        self.assertIsNone(window._parse_user_date("31/02/2026"))


if __name__ == "__main__":
    unittest.main()
