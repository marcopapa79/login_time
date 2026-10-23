from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Dict

from . import credentials_store

DEFAULT_USERNAME = "marco.papa@quixant.com"
# No default password: it is typed at first login and stored in Windows Credential Manager.
DEFAULT_PASSWORD = ""

_PROJECT_DIR = Path(__file__).resolve().parents[2]
_LOCAL_SETTINGS_FILE = _PROJECT_DIR / "local_settings.json"


def _resolve_data_dir() -> Path:
    """Data folder: LOGIN_TIME_DATA_DIR env var, else local_settings.json "data_dir", else project folder."""
    value = os.environ.get("LOGIN_TIME_DATA_DIR", "").strip()
    if not value and _LOCAL_SETTINGS_FILE.exists():
        try:
            raw = json.loads(_LOCAL_SETTINGS_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            raw = {}
        if isinstance(raw, dict):
            value = str(raw.get("data_dir") or "").strip()
    if not value:
        return _PROJECT_DIR
    path = Path(os.path.expandvars(value)).expanduser()
    return path if path.is_absolute() else _PROJECT_DIR / path


_DATA_DIR = _resolve_data_dir()

_CREDENTIALS_FILE = _PROJECT_DIR / "credentials.json"
_WORKLOG_FILE = _DATA_DIR / "worklogs.json"
_TICKET_UUID_CACHE_FILE = _DATA_DIR / "ticket_uuid_cache.json"
_WRITE_LOCK = threading.Lock()

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


def _read_credentials_file() -> tuple[str, str]:
    if not _CREDENTIALS_FILE.exists():
        return "", ""
    try:
        raw = json.loads(_CREDENTIALS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return "", ""
    if not isinstance(raw, dict):
        return "", ""
    return str(raw.get("username") or ""), str(raw.get("password") or "")


def _write_credentials_file(username: str, password: str | None) -> None:
    payload: Dict[str, str] = {"username": username}
    if password is not None:
        payload["password"] = password
    _CREDENTIALS_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def credentials_storage_label() -> str:
    """Human readable place where the password is kept."""
    return "Gestore credenziali di Windows" if credentials_store.is_supported() else "credentials.json"


def load_credentials() -> Dict[str, str]:
    """Load username/password.

    On Windows the password lives in Credential Manager. A plain-text password still
    found in credentials.json is moved there once and removed from the file.
    """
    file_username, file_password = _read_credentials_file()
    username = file_username or DEFAULT_USERNAME

    if credentials_store.is_supported():
        if file_password:
            if credentials_store.write_credential(username, file_password):
                _write_credentials_file(username, None)
            return {"username": username, "password": file_password}
        stored = credentials_store.read_credential()
        if stored is not None and stored[1]:
            return {"username": file_username or stored[0] or username, "password": stored[1]}
        return {"username": username, "password": DEFAULT_PASSWORD}

    return {"username": username, "password": file_password or DEFAULT_PASSWORD}


def save_credentials(username: str, password: str) -> None:
    """Persist credentials for next app openings (password in Credential Manager when available)."""
    if credentials_store.is_supported() and credentials_store.write_credential(username, password):
        _write_credentials_file(username, None)
        return
    _write_credentials_file(username, password)


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
                # Set when a row already on the portal was edited and queued again:
                # holds the previous sync timestamp so the app can warn about duplicates.
                "api_resend_of": str(item.get("api_resend_of", "")),
            }
        )
    return entries


def _atomic_write(path: Path, text: str) -> None:
    """Write via a temp file + rename, so a crash mid-write never truncates the file."""
    with _WRITE_LOCK:  # the sync worker thread may save the UUID cache
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(text, encoding="utf-8")
        os.replace(tmp_path, path)


def save_work_logs(entries: list[dict[str, str]]) -> None:
    """Persist worklog entries for future app sessions."""
    _atomic_write(_WORKLOG_FILE, json.dumps(entries, indent=2))


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

    _atomic_write(_TICKET_UUID_CACHE_FILE, json.dumps(normalized, indent=2))


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
