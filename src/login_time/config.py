from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
from dataclasses import dataclass
from datetime import datetime
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


def load_saved_username() -> tuple[str, bool]:
    """(username, a password is saved) without keeping the password around."""
    creds = load_credentials()
    return creds["username"], bool(creds["password"])


def forget_saved_password() -> bool:
    """Delete the stored password (Credential Manager and any copy in credentials.json).
    The email stays, so the login form is still prefilled."""
    username, _password = _read_credentials_file()
    stored = credentials_store.read_credential() if credentials_store.is_supported() else None
    username = username or (stored[0] if stored else "") or DEFAULT_USERNAME
    removed = credentials_store.delete_credential() if credentials_store.is_supported() else True
    _write_credentials_file(username, None)
    return removed


# ---------------------------------------------------------------- Jira Cloud

DEFAULT_JIRA_SITE = "https://quixantplc.atlassian.net"
_JIRA_SETTINGS_FILE = _PROJECT_DIR / "jira_settings.json"


def _jira_target(site: str) -> str:
    host = site.replace("https://", "").replace("http://", "").strip("/").lower()
    return credentials_store.JIRA_TARGET_PREFIX + host


def _read_jira_file() -> Dict[str, str]:
    if not _JIRA_SETTINGS_FILE.exists():
        return {}
    try:
        raw = json.loads(_JIRA_SETTINGS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return {str(k): str(v) for k, v in raw.items()} if isinstance(raw, dict) else {}


def load_jira_settings() -> tuple[str, str, bool]:
    """(site, email, a token is saved). The token itself is read only when connecting."""
    data = _read_jira_file()
    site = data.get("site") or DEFAULT_JIRA_SITE
    email = data.get("email", "")
    return site, email, bool(load_jira_token(site))


def load_jira_token(site: str) -> str:
    if credentials_store.is_supported():
        stored = credentials_store.read_credential(_jira_target(site))
        return stored[1] if stored else ""
    return _read_jira_file().get("token", "")


def save_jira_settings(site: str, email: str, token: str) -> None:
    """site + email in jira_settings.json (git-ignored), token in Windows Credential Manager."""
    payload: Dict[str, str] = {"site": site, "email": email}
    # Keep the OAuth app id (not secret) so switching back to the browser login is quick.
    payload.update({k: v for k, v in _read_jira_file().items() if k in ("oauth_client_id", "oauth_cloud_id")})
    if credentials_store.is_supported():
        # Windows: the token goes ONLY to Credential Manager; never fall back to a clear-text file.
        if not credentials_store.write_credential(
            email, token, target=_jira_target(site), comment="login_time - Jira Cloud API token"
        ):
            raise RuntimeError("Gestore credenziali di Windows non disponibile")
    else:
        payload["token"] = token  # only off Windows (development/tests), file is git-ignored
    _atomic_write(_JIRA_SETTINGS_FILE, json.dumps(payload, indent=2))


# ---- Jira OAuth (browser login with Microsoft + Duo, see jira_oauth.py)
# jira_settings.json: "auth": "oauth", "oauth_client_id", "oauth_cloud_id" (not secrets).
# Credential Manager "login_time/jira-oauth:<host>": {"client_secret", "refresh_token"} as JSON.
# Atlassian refresh tokens can be longer than one credential entry holds (2560 bytes),
# so long values are split over "<target>", "<target>#1", "<target>#2", …
_LONG_SECRET_CHUNK = 1000  # characters (UTF-16 in Credential Manager → 2000 bytes)
_LONG_SECRET_MARK = "LT1:"
_JIRA_SECRET_LOCK = threading.Lock()


@dataclass
class JiraOAuthSettings:
    site: str
    email: str
    client_id: str
    cloud_id: str
    client_secret: str
    refresh_token: str


def _jira_oauth_target(site: str) -> str:
    host = site.replace("https://", "").replace("http://", "").strip("/").lower()
    return credentials_store.JIRA_OAUTH_TARGET_PREFIX + host


def _write_long_secret(target: str, username: str, value: str, comment: str) -> bool:
    chunks = [value[i:i + _LONG_SECRET_CHUNK] for i in range(0, len(value), _LONG_SECRET_CHUNK)] or [""]
    for index, chunk in enumerate(chunks[1:], start=1):
        if not credentials_store.write_credential(username, chunk, target=f"{target}#{index}", comment=comment):
            return False
    head = f"{_LONG_SECRET_MARK}{len(chunks)}:{chunks[0]}"
    if not credentials_store.write_credential(username, head, target=target, comment=comment):
        return False
    _delete_long_secret_parts(target, start=len(chunks))
    return True


def _read_long_secret(target: str) -> str:
    stored = credentials_store.read_credential(target)
    if stored is None:
        return ""
    head = stored[1]
    if not head.startswith(_LONG_SECRET_MARK):
        return head
    count_text, _, first = head[len(_LONG_SECRET_MARK):].partition(":")
    parts = [first]
    for index in range(1, int(count_text or 1)):
        part = credentials_store.read_credential(f"{target}#{index}")
        if part is None:
            return ""  # incomplete: treat as missing (a new login rewrites it)
        parts.append(part[1])
    return "".join(parts)


def _delete_long_secret_parts(target: str, start: int = 1) -> None:
    index = start
    while credentials_store.read_credential(f"{target}#{index}") is not None:
        credentials_store.delete_credential(f"{target}#{index}")
        index += 1


def _delete_long_secret(target: str) -> None:
    credentials_store.delete_credential(target)
    _delete_long_secret_parts(target)


def _read_jira_oauth_secret(site: str) -> Dict[str, str]:
    if credentials_store.is_supported():
        raw = _read_long_secret(_jira_oauth_target(site))
    else:
        raw = _read_jira_file().get("oauth_secret", "")  # only off Windows (development/tests)
    try:
        data = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        return {}
    return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}


def _write_jira_oauth_secret(site: str, email: str, secret: Dict[str, str]) -> None:
    raw = json.dumps(secret)
    if credentials_store.is_supported():
        if not _write_long_secret(_jira_oauth_target(site), email, raw, "login_time - Jira OAuth (login Microsoft + Duo)"):
            raise RuntimeError("Gestore credenziali di Windows non disponibile")
        return
    data = _read_jira_file()
    data["oauth_secret"] = raw
    _atomic_write(_JIRA_SETTINGS_FILE, json.dumps(data, indent=2))


def load_jira_oauth() -> JiraOAuthSettings | None:
    """OAuth settings when the Jira page is set to the browser login, else None.
    refresh_token is "" when a new login is needed (expired, revoked or "Scollega")."""
    data = _read_jira_file()
    if data.get("auth") != "oauth":
        return None
    site = data.get("site") or DEFAULT_JIRA_SITE
    secret = _read_jira_oauth_secret(site)
    return JiraOAuthSettings(
        site=site,
        email=data.get("email", ""),
        client_id=data.get("oauth_client_id", ""),
        cloud_id=data.get("oauth_cloud_id", ""),
        client_secret=secret.get("client_secret", ""),
        refresh_token=secret.get("refresh_token", ""),
    )


def save_jira_oauth(site: str, email: str, client_id: str, cloud_id: str, client_secret: str, refresh_token: str) -> None:
    """Switch the Jira page to the browser login. Secret + refresh token go to Credential Manager;
    the old API token is removed from this PC (revoke it on id.atlassian.com too)."""
    with _JIRA_SECRET_LOCK:
        _write_jira_oauth_secret(site, email, {"client_secret": client_secret, "refresh_token": refresh_token})
        data = {k: v for k, v in _read_jira_file().items() if k in ("oauth_secret",)}
        data.update({"site": site, "email": email, "auth": "oauth", "oauth_client_id": client_id, "oauth_cloud_id": cloud_id})
        _atomic_write(_JIRA_SETTINGS_FILE, json.dumps(data, indent=2))
    if credentials_store.is_supported():
        credentials_store.delete_credential(_jira_target(site))


def save_jira_oauth_refresh(site: str, refresh_token: str) -> None:
    """Atlassian rotated the refresh token: store the new one (called from worker threads)."""
    with _JIRA_SECRET_LOCK:
        data = _read_jira_file()
        secret = _read_jira_oauth_secret(site)
        secret["refresh_token"] = refresh_token
        _write_jira_oauth_secret(site, data.get("email", ""), secret)


def save_jira_oauth_app(site: str, email: str, client_id: str, client_secret: str) -> None:
    """Remember Client ID / Secret before the first login (the refresh token comes after it)."""
    with _JIRA_SECRET_LOCK:
        secret = _read_jira_oauth_secret(site)
        secret["client_secret"] = client_secret
        _write_jira_oauth_secret(site, email, secret)
        data = _read_jira_file()
        data.update({"site": site, "email": email, "auth": "oauth", "oauth_client_id": client_id})
        _atomic_write(_JIRA_SETTINGS_FILE, json.dumps(data, indent=2))


def forget_jira_oauth(site: str, *, keep_app: bool) -> None:
    """Remove the refresh token (next time: login + Duo). keep_app=False also removes the
    Client ID / Secret and goes back to the API-token setup."""
    with _JIRA_SECRET_LOCK:
        secret = _read_jira_oauth_secret(site)
        data = _read_jira_file()
        if keep_app and secret.get("client_secret"):
            _write_jira_oauth_secret(site, data.get("email", ""), {"client_secret": secret["client_secret"]})
            return
        if credentials_store.is_supported():
            _delete_long_secret(_jira_oauth_target(site))
        for key in ("auth", "oauth_client_id", "oauth_cloud_id", "oauth_secret"):
            data.pop(key, None)
        if data:
            _atomic_write(_JIRA_SETTINGS_FILE, json.dumps(data, indent=2))


def forget_jira_token(site: str) -> None:
    if credentials_store.is_supported():
        credentials_store.delete_credential(_jira_target(site))
    data = _read_jira_file()
    data.pop("token", None)
    if data:
        _atomic_write(_JIRA_SETTINGS_FILE, json.dumps(data, indent=2))


def save_credentials(username: str, password: str) -> None:
    """Persist credentials for next app openings (password in Credential Manager when available)."""
    if credentials_store.is_supported() and credentials_store.write_credential(username, password):
        _write_credentials_file(username, None)
        return
    _write_credentials_file(username, password)


# ---------------------------------------------------------------- worklogs.json version
# The "database" is worklogs.json in the data folder (often OneDrive, shared between PCs).
# We remember which version of the file the app has in memory (modification time + content
# hash), so the UI can show "last updated" and notice when another PC replaced the file.
# The modification time travels with the file when OneDrive syncs it to the other PCs.
_UNREADABLE = "unreadable"
_worklog_seen: Dict[str, object] = {"mtime": None, "mtime_ns": None, "size": None, "digest": None}
_pending_backup_notice: list[Path] = []  # backups made by save_work_logs, not yet shown to the user


@dataclass(frozen=True)
class WorklogFileState:
    path: Path
    loaded_mtime: float | None  # mtime of the version the app has in memory (load or last save)
    disk_mtime: float | None  # mtime of the file on disk now; None = file missing
    changed_on_disk: bool  # the file on disk is not the version the app has in memory


def worklog_file_path() -> Path:
    return _WORKLOG_FILE


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _remember_worklog_version(data: bytes | None, *, readable: bool = True) -> None:
    """Record the version on disk as the one now in memory (data=None: no file)."""
    try:
        st = _WORKLOG_FILE.stat() if data is not None else None
    except OSError:
        st = None
    _worklog_seen.update(
        mtime=st.st_mtime if st else None,
        mtime_ns=st.st_mtime_ns if st else None,
        size=st.st_size if st else None,
        digest=(_digest(data) if readable else _UNREADABLE) if data is not None else None,
    )


def _disk_differs_from_memory() -> tuple[bool, os.stat_result | None]:
    """(file on disk is a different version than the one in memory, its stat)."""
    try:
        st = _WORKLOG_FILE.stat()
    except OSError:
        return _worklog_seen["digest"] is not None, None  # we had a file, now it is gone
    if st.st_mtime_ns == _worklog_seen["mtime_ns"] and st.st_size == _worklog_seen["size"]:
        return False, st
    try:
        data = _WORKLOG_FILE.read_bytes()
    except OSError:
        return True, st
    if _worklog_seen["digest"] not in (None, _UNREADABLE) and _digest(data) == _worklog_seen["digest"]:
        # Same content with a new date (e.g. re-synced unchanged): adopt the new date.
        _worklog_seen.update(mtime=st.st_mtime, mtime_ns=st.st_mtime_ns, size=st.st_size)
        return False, st
    return True, st


def worklog_file_state() -> WorklogFileState:
    """Where worklogs.json is, which version the app shows and whether the disk has another one."""
    changed, st = _disk_differs_from_memory()
    loaded = _worklog_seen["mtime"]
    return WorklogFileState(
        path=_WORKLOG_FILE,
        loaded_mtime=float(loaded) if isinstance(loaded, (int, float)) else None,
        disk_mtime=st.st_mtime if st else None,
        changed_on_disk=changed,
    )


def _backup_worklog_file() -> Path | None:
    """Copy the current worklogs.json aside (worklogs.backup-YYYYmmdd-HHMMSS.json)."""
    if not _WORKLOG_FILE.exists():
        return None
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = _WORKLOG_FILE.with_name(f"{_WORKLOG_FILE.stem}.backup-{stamp}{_WORKLOG_FILE.suffix}")
    try:
        shutil.copy2(_WORKLOG_FILE, target)
    except OSError:
        return None
    return target


def take_worklog_backup_notice() -> Path | None:
    """Most recent backup made while saving (once: the next call returns None)."""
    if not _pending_backup_notice:
        return None
    latest = _pending_backup_notice[-1]
    _pending_backup_notice.clear()
    return latest


def load_work_logs() -> list[dict[str, str]]:
    """Load local worklog entries shown in dashboard."""
    if not _WORKLOG_FILE.exists():
        _remember_worklog_version(None)
        return []

    try:
        data = _WORKLOG_FILE.read_bytes()
    except OSError:
        _remember_worklog_version(None)
        return []
    try:
        raw = json.loads(data.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        # Unreadable file: the next save keeps a backup copy instead of silently replacing it.
        _remember_worklog_version(data, readable=False)
        return []

    if not isinstance(raw, list):
        _remember_worklog_version(data, readable=False)
        return []
    _remember_worklog_version(data)

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
                # Id of the entry on the portal (working_hours/form response), used to update/delete it.
                "api_entry_id": str(item.get("api_entry_id", "")),
                # Set when the hours were sent as a ticket message (ticket_posts/create).
                "api_post_uuid": str(item.get("api_post_uuid", "")),
                # "update" = edited after sync, the next sync updates the existing portal entry.
                "api_pending_action": str(item.get("api_pending_action", "")),
                # JSON with the values still on the portal, to find the entry when its Id is unknown.
                "api_prev_values": str(item.get("api_prev_values", "")),
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


def save_work_logs(entries: list[dict[str, str]]) -> Path | None:
    """Persist worklog entries for future app sessions.

    If the file on disk is not the version the app loaded (another PC saved it in the
    meantime, or it was unreadable), that file is copied aside first and the copy's path
    is returned, so nothing is lost silently.
    """
    backup = None
    changed, _st = _disk_differs_from_memory()
    if changed or _worklog_seen["digest"] == _UNREADABLE:
        backup = _backup_worklog_file()
        if backup is not None:
            _pending_backup_notice.append(backup)
    _atomic_write(_WORKLOG_FILE, json.dumps(entries, indent=2))
    try:
        _remember_worklog_version(_WORKLOG_FILE.read_bytes())
    except OSError:
        _remember_worklog_version(None)
    return backup


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
