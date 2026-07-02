from __future__ import annotations

import json
from pathlib import Path
from typing import Dict

DEFAULT_USERNAME = "marco.papa@quixant.com"
DEFAULT_PASSWORD = "Birindelli79"

_CREDENTIALS_FILE = Path(__file__).resolve().parents[2] / "credentials.json"
_WORKLOG_FILE = Path(__file__).resolve().parents[2] / "worklogs.json"


def load_credentials() -> Dict[str, str]:
    """Load credentials from file, falling back to safe defaults."""
    if not _CREDENTIALS_FILE.exists():
        return {"username": DEFAULT_USERNAME, "password": DEFAULT_PASSWORD}

    try:
        raw = json.loads(_CREDENTIALS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"username": DEFAULT_USERNAME, "password": DEFAULT_PASSWORD}

    username = raw.get("username") or DEFAULT_USERNAME
    password = raw.get("password") or DEFAULT_PASSWORD
    return {"username": str(username), "password": str(password)}


def save_credentials(username: str, password: str) -> None:
    """Persist credentials for next app openings."""
    payload = {"username": username, "password": password}
    _CREDENTIALS_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_work_logs() -> list[dict[str, str]]:
    """Load local worklog entries shown in dashboard."""
    if not _WORKLOG_FILE.exists():
        return []

    try:
        raw = json.loads(_WORKLOG_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []

    if not isinstance(raw, list):
        return []

    entries: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        entries.append(
            {
                "working_time": str(item.get("working_time", "")),
                "month": str(item.get("month", "")),
                "work_log": str(item.get("work_log", "")),
                "ticket": str(item.get("ticket", "")),
                "comment": str(item.get("comment", "")),
                "description": str(item.get("description", "")),
            }
        )
    return entries


def save_work_logs(entries: list[dict[str, str]]) -> None:
    """Persist worklog entries for future app sessions."""
    _WORKLOG_FILE.write_text(json.dumps(entries, indent=2), encoding="utf-8")
