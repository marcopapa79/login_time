"""Date of the database (worklogs.json) shown in the app, and protection when another PC changed it."""

import json
import os
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from login_time import config  # noqa: E402
from login_time.config import WorklogFileState  # noqa: E402
from login_time.ui import LoginWindow  # noqa: E402


def set_mtime(path: Path, when: datetime) -> None:
    ts = when.timestamp()
    os.utime(path, (ts, ts))


class WorklogVersionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.file = Path(self.tmp.name) / "worklogs.json"
        for patcher in (
            mock.patch.object(config, "_WORKLOG_FILE", self.file),
            mock.patch.dict(config._worklog_seen, {"mtime": None, "mtime_ns": None, "size": None, "digest": None}),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        config._pending_backup_notice.clear()

    def write(self, rows, when: datetime) -> None:
        self.file.write_text(json.dumps(rows, indent=2), encoding="utf-8")
        set_mtime(self.file, when)

    def backups(self):
        return sorted(self.file.parent.glob("worklogs.backup-*.json"))

    def test_load_remembers_the_date_of_the_file(self):
        when = datetime(2026, 11, 3, 18, 2, 5)
        self.write([{"ticket": "QUIX-1"}], when)
        rows = config.load_work_logs()
        state = config.worklog_file_state()
        self.assertEqual(rows[0]["ticket"], "QUIX-1")
        self.assertAlmostEqual(state.loaded_mtime, when.timestamp(), places=3)
        self.assertFalse(state.changed_on_disk)

    def test_save_moves_the_date_forward_without_backup(self):
        self.write([], datetime(2026, 11, 1, 9, 0))
        config.load_work_logs()
        before = time.time()
        self.assertIsNone(config.save_work_logs([{"ticket": "QUIX-2"}]))
        state = config.worklog_file_state()
        self.assertGreaterEqual(state.loaded_mtime, before - 2)
        self.assertFalse(state.changed_on_disk)
        self.assertEqual(self.backups(), [])
        self.assertIsNone(config.take_worklog_backup_notice())

    def test_newer_file_from_another_pc_is_noticed_and_kept_as_backup(self):
        self.write([{"ticket": "OLD"}], datetime(2026, 11, 1, 9, 0))
        config.load_work_logs()
        self.write([{"ticket": "FROM-OTHER-PC"}], datetime(2026, 11, 4, 11, 30))

        state = config.worklog_file_state()
        self.assertTrue(state.changed_on_disk)
        self.assertGreater(state.disk_mtime, state.loaded_mtime)

        backup = config.save_work_logs([{"ticket": "OLD"}, {"ticket": "NEW-HERE"}])
        self.assertIsNotNone(backup)
        self.assertEqual(json.loads(backup.read_text(encoding="utf-8")), [{"ticket": "FROM-OTHER-PC"}])
        self.assertEqual(config.take_worklog_backup_notice(), backup)
        self.assertIsNone(config.take_worklog_backup_notice())
        self.assertFalse(config.worklog_file_state().changed_on_disk)
        # A second save does not make another copy.
        self.assertIsNone(config.save_work_logs([{"ticket": "OLD"}]))

    def test_same_content_with_new_date_is_not_a_change(self):
        self.write([{"ticket": "A"}], datetime(2026, 11, 1, 9, 0))
        config.load_work_logs()
        later = datetime(2026, 11, 2, 10, 0)
        set_mtime(self.file, later)
        state = config.worklog_file_state()
        self.assertFalse(state.changed_on_disk)
        self.assertAlmostEqual(state.loaded_mtime, later.timestamp(), places=3)

    def test_reload_adopts_the_version_on_disk(self):
        self.write([{"ticket": "OLD"}], datetime(2026, 11, 1, 9, 0))
        config.load_work_logs()
        newer = datetime(2026, 11, 4, 11, 30)
        self.write([{"ticket": "NEW"}], newer)
        rows = config.load_work_logs()
        state = config.worklog_file_state()
        self.assertEqual(rows[0]["ticket"], "NEW")
        self.assertFalse(state.changed_on_disk)
        self.assertAlmostEqual(state.loaded_mtime, newer.timestamp(), places=3)

    def test_unreadable_file_is_copied_before_being_replaced(self):
        self.file.write_text('[{"ticket": "QUIX', encoding="utf-8")  # cut in the middle
        self.assertEqual(config.load_work_logs(), [])
        backup = config.save_work_logs([{"ticket": "QUIX-9"}])
        self.assertIsNotNone(backup)
        self.assertEqual(backup.read_text(encoding="utf-8"), '[{"ticket": "QUIX')

    def test_missing_file_then_created_elsewhere(self):
        config.load_work_logs()
        state = config.worklog_file_state()
        self.assertIsNone(state.loaded_mtime)
        self.assertFalse(state.changed_on_disk)
        self.write([{"ticket": "X"}], datetime(2026, 11, 4, 8, 0))
        self.assertTrue(config.worklog_file_state().changed_on_disk)

    def test_deleted_file_is_reported(self):
        self.write([], datetime(2026, 11, 1, 9, 0))
        config.load_work_logs()
        self.file.unlink()
        state = config.worklog_file_state()
        self.assertTrue(state.changed_on_disk)
        self.assertIsNone(state.disk_mtime)


class DbStatusTextTests(unittest.TestCase):
    path = Path("C:/Users/marco/OneDrive/login_time_data/worklogs.json")

    def window(self):
        return object.__new__(LoginWindow)

    def state(self, loaded, disk, changed):
        ts = lambda d: d.timestamp() if d else None  # noqa: E731
        return WorklogFileState(self.path, ts(loaded), ts(disk), changed)

    def test_normal_shows_date_at_top_and_bottom(self):
        when = datetime(2026, 11, 4, 11, 24, 15)
        texts = self.window()._db_status_texts(self.state(when, when, False))
        self.assertEqual(texts["chip"], "DB aggiornato 04/11/2026 11:24")
        self.assertTrue(str(texts["footer"]).startswith("Database aggiornato mer 04/11/2026 11:24:15 · "))
        self.assertFalse(texts["warn"])
        self.assertFalse(texts["reload"])

    def test_newer_on_disk_asks_to_reload(self):
        texts = self.window()._db_status_texts(
            self.state(datetime(2026, 11, 3, 18, 0), datetime(2026, 11, 4, 11, 30, 2), True)
        )
        self.assertTrue(texts["warn"])
        self.assertTrue(texts["reload"])
        self.assertIn("Ricarica", str(texts["chip"]))
        self.assertIn("mer 04/11/2026 11:30:02", str(texts["footer"]))
        self.assertIn("mar 03/11/2026 18:00:00", str(texts["footer"]))

    def test_older_on_disk_is_flagged(self):
        texts = self.window()._db_status_texts(
            self.state(datetime(2026, 11, 4, 11, 0), datetime(2026, 11, 2, 9, 0), True)
        )
        self.assertTrue(texts["warn"])
        self.assertIn("più vecchio", str(texts["chip"]))

    def test_missing_file(self):
        texts = self.window()._db_status_texts(self.state(datetime(2026, 11, 4, 11, 0), None, True))
        self.assertTrue(texts["warn"])
        self.assertFalse(texts["reload"])
        self.assertIn("non trovato", str(texts["chip"]))

    def test_not_created_yet(self):
        texts = self.window()._db_status_texts(self.state(None, None, False))
        self.assertEqual(texts["chip"], "DB non ancora salvato")

    def test_age(self):
        now = datetime.now()
        age = LoginWindow._db_age
        self.assertEqual(age((now - timedelta(seconds=20)).timestamp()), "adesso")
        self.assertEqual(age((now + timedelta(minutes=3)).timestamp()), "adesso")
        self.assertEqual(age((now - timedelta(minutes=5, seconds=5)).timestamp()), "5 min fa")
        self.assertEqual(age((now - timedelta(days=3)).timestamp()), "3 giorni fa")


if __name__ == "__main__":
    unittest.main()
