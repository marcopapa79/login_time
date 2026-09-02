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

    def test_marks_all_month_off_entries_as_synced_when_locked(self):
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
        self.assertEqual(window.work_logs[1]["api_synced"], "true")
        self.assertEqual(window.work_logs[2]["api_synced"], "")


if __name__ == "__main__":
    unittest.main()
