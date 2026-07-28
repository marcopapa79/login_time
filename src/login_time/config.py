from __future__ import annotations

import json
from pathlib import Path
from typing import Dict

DEFAULT_USERNAME = "marco.papa@quixant.com"
DEFAULT_PASSWORD = "birindelli79"

_CREDENTIALS_FILE = Path(__file__).resolve().parents[2] / "credentials.json"
_WORKLOG_FILE = Path(__file__).resolve().parents[2] / "worklogs.json"
_TICKET_UUID_CACHE_FILE = Path(__file__).resolve().parents[2] / "ticket_uuid_cache.json"


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
                "entry_type": str(item.get("entry_type", "work")),
                "off_type": str(item.get("off_type", "")),
                "log_date": str(item.get("log_date", "")),
                "api_synced": str(item.get("api_synced", "")),
                "api_synced_at": str(item.get("api_synced_at", "")),
                "api_ticket_uuid": str(item.get("api_ticket_uuid", "")),
                "api_month_displacement": str(item.get("api_month_displacement", "")),
            }
        )
    return entries


def save_work_logs(entries: list[dict[str, str]]) -> None:
    """Persist worklog entries for future app sessions."""
    _WORKLOG_FILE.write_text(json.dumps(entries, indent=2), encoding="utf-8")


def load_ticket_uuid_cache() -> Dict[str, str]:
    """Load cached mapping between ticket code (e.g. QUIX-707) and UUID."""
    if not _TICKET_UUID_CACHE_FILE.exists():
        return {}

    try:
        raw = json.loads(_TICKET_UUID_CACHE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}

    if not isinstance(raw, dict):
        return {}

    cache: Dict[str, str] = {}
    for ticket, uuid in raw.items():
        if not isinstance(ticket, str) or not isinstance(uuid, str):
            continue
        key = ticket.strip().upper()
        value = uuid.strip().upper()
        if key and value:
            cache[key] = value

    return cache


def save_ticket_uuid_cache(cache: Dict[str, str]) -> None:
    """Persist cached ticket code -> UUID mapping."""
    normalized: Dict[str, str] = {}
    for ticket, uuid in cache.items():
        key = str(ticket).strip().upper()
        value = str(uuid).strip().upper()
        if key and value:
            normalized[key] = value

    _TICKET_UUID_CACHE_FILE.write_text(json.dumps(normalized, indent=2), encoding="utf-8")
