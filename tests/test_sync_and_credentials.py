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

    def test_non_windows_store_is_not_supported(self):
        if sys.platform != "win32":
            self.assertFalse(credentials_store.is_supported())
            self.assertIsNone(credentials_store.read_credential())


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
        window.api_client.request_json.side_effect = lambda *args: sent.append(args)
        window._build_api_payload_for_row = lambda row, token: ("UUID-1", {"MonthDisplacement": "-1"})
        window._cache_ticket_uuid = lambda *_a: None
        row = {"ticket": "QUIX-707", "entry_type": "work", "api_synced": ""}

        window._sync_row_with_portal("token", row)

        self.assertEqual(sent[0][1], "/api/working_hours/form")
        self.assertEqual(row["api_synced"], "true")
        self.assertEqual(row["api_ticket_uuid"], "UUID-1")
        self.assertEqual(row["api_month_displacement"], "-1")


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
