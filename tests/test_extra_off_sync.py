import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from login_time.ui import LoginWindow


class ExtraOffSyncTests(unittest.TestCase):
    def test_detects_locked_api_error(self):
        message = RuntimeError("HTTP 400 calling /api/extrahours/add: {'Message':'This entry is locked'}")
        self.assertTrue(LoginWindow._is_api_lock_error(message))

    def test_marks_only_selected_off_entry_as_synced(self):
        window = object.__new__(LoginWindow)
        window.work_logs = [
            {
                "ticket": "OFF",
                "month": "September 2026",
                "entry_type": "off",
                "api_synced": "",
                "api_synced_at": "",
            },
            {
                "ticket": "OFF",
                "month": "September 2026",
                "entry_type": "off",
                "api_synced": "",
                "api_synced_at": "",
            },
            {
                "ticket": "OFF",
                "month": "August 2026",
                "entry_type": "off",
                "api_synced": "",
                "api_synced_at": "",
            },
        ]

        window._mark_row_as_extra_hours_synced(window.work_logs[0])

        self.assertEqual(window.work_logs[0]["api_synced"], "true")
        self.assertEqual(window.work_logs[1]["api_synced"], "")
        self.assertEqual(window.work_logs[2]["api_synced"], "")

    def test_treats_locked_extra_off_entry_as_already_synced(self):
        window = object.__new__(LoginWindow)
        row = {"api_synced": "", "api_synced_at": ""}
        window._build_extra_hours_payload_for_row = lambda _row, _token: {}
        window.api_client = type(
            "Client",
            (),
            {"request_json": lambda *_args: (_ for _ in ()).throw(RuntimeError("This entry is locked"))},
        )()

        self.assertTrue(window._sync_extra_hours_row("token", row))
        self.assertEqual(row["api_synced"], "true")

    def test_builds_extra_off_payload_with_api_field_names(self):
        window = object.__new__(LoginWindow)
        window._request_extra_hours_guid = lambda _token: "528b9d16-e47b-431d-b066-3f683d23002f"
        row = {
            "working_time": "4h",
            "off_type": "Annual Leave",
            "log_date": "2026-09-02",
            "comment": "15th anniversary",
        }

        payload = window._build_extra_hours_payload_for_row(row, "token")

        self.assertEqual(
            payload,
            {
                "uuid": "528b9d16-e47b-431d-b066-3f683d23002f",
                "id_clockify_task": "652434fef8763231c98909ee",
                "hours": 4,
                "log_date_start": "02/09/2026",
                "log_date_end": "02/09/2026",
                "description": "15th anniversary",
            },
        )


if __name__ == "__main__":
    unittest.main()
