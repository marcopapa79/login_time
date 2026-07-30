from __future__ import annotations

import json
from pathlib import Path
from typing import Dict

DEFAULT_USERNAME = "marco.papa@quixant.com"
DEFAULT_PASSWORD = "birindelli79"

_CREDENTIALS_FILE = Path(__file__).resolve().parents[2] / "credentials.json"
_WORKLOG_FILE = Path(__file__).resolve().parents[2] / "worklogs.json"
_TICKET_UUID_CACHE_FILE = Path(__file__).resolve().parents[2] / "ticket_uuid_cache.json"

# Clockify task name -> id mapping used by extra-hours API flows.
CLOCKIFY_TASKS: Dict[str, str] = {
    "Administration": "64e634463e2c1102ee9ab801",
    "Customer Meeting": "64e6344d66b77570d7510aaf",
    "Customer Support": "64e6345466b77570d7510ba9",
    "Demos": "64e63459ebeee150226d30f6",
    "Internal Meeting": "64e6345e97f5910c716e1a16",
    "Research": "64e6346debeee150226d337c",
    "Suppliers": "64e6347894577124655aab45",
    "Trade Show": "64e63480ebeee150226d35a2",
    "Training": "64e6348866b77570d7511303",
    "Annual Leave": "652434fef8763231c98909ee",
    "Sick Leave": "652435024eff40535144f947",
    "Project Management": "68e736e7070e6c76ade5e033",
    "Hardware": "68e736e7070e6c76ade5e034",
    "Meeting": "68e736e7070e6c76ade5e035",
    "Software": "68e736e7117c9a0f0778770b",
    "Mechanical": "68e736e7117c9a0f0778770c",
    "Documentation": "68e736e75598f9482af8a6ef",
    "Support": "68e736e75598f9482af8a6f0",
}

_CLOCKIFY_TASK_ALIASES: Dict[str, str] = {
    "ferie": "Annual Leave",
    "annual leave": "Annual Leave",
    "sick leave": "Sick Leave",
    "malattia": "Sick Leave",
}


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


def get_clockify_tasks() -> Dict[str, str]:
    """Return a copy of configured Clockify tasks (name -> id)."""
    return dict(CLOCKIFY_TASKS)


def get_clockify_task_id(task_name: str) -> str:
    """Resolve Clockify task id from task name, with a few common aliases."""
    raw = str(task_name).strip()
    if not raw:
        return ""

    if raw in CLOCKIFY_TASKS:
        return CLOCKIFY_TASKS[raw]

    canonical = _CLOCKIFY_TASK_ALIASES.get(raw.lower(), raw)
    if canonical in CLOCKIFY_TASKS:
        return CLOCKIFY_TASKS[canonical]

    for name, task_id in CLOCKIFY_TASKS.items():
        if name.lower() == raw.lower():
            return task_id

    return ""
