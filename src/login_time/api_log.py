"""Debug log of every request sent to the Quixant Hub API.

File: <project>/logs/api_sync.log (rotates at 2 MB, keeps 5 old files; git-ignored).
Never written: passwords, the Authorization header, the login response (it holds the token).
Thread-safe (the sync runs in a worker thread) thanks to the logging module.
"""

from __future__ import annotations

import json
import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

LOG_DIR = Path(__file__).resolve().parents[2] / "logs"
LOG_FILE = LOG_DIR / "api_sync.log"

_MAX_BODY = 4000
_MAX_LIST_RESPONSE = 400
_SECRET_KEYS = {"password", "pwd", "accesstoken", "access_token", "token", "jwt", "bearertoken"}

_logger = logging.getLogger("login_time.api")
_configured = False


def _setup() -> logging.Logger:
    global _configured
    if _configured:
        return _logger
    _configured = True
    _logger.setLevel(logging.INFO)
    _logger.propagate = False
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(LOG_FILE, maxBytes=2_000_000, backupCount=5, encoding="utf-8")
    except OSError:
        _logger.addHandler(logging.NullHandler())
        return _logger
    handler.setFormatter(logging.Formatter("%(asctime)s  %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
    _logger.addHandler(handler)
    return _logger


def mask_secrets(value: Any) -> Any:
    """Copy of value with secret-looking keys replaced by ***."""
    if isinstance(value, dict):
        return {k: ("***" if str(k).lower() in _SECRET_KEYS else mask_secrets(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [mask_secrets(item) for item in value]
    return value


def _short(text: str, limit: int) -> str:
    text = text.replace("\r", " ").replace("\n", " ")
    return text if len(text) <= limit else f"{text[:limit]}… ({len(text)} caratteri)"


def _body_text(body: bytes | None) -> str:
    if not body:
        return ""
    raw = body.decode("utf-8", errors="replace")
    try:
        return json.dumps(mask_secrets(json.loads(raw)), ensure_ascii=False)
    except json.JSONDecodeError:
        # form-encoded login body: hide password=...
        return re.sub(r"(password=)[^&]*", r"\1***", raw, flags=re.IGNORECASE)


def request(method: str, path: str, body: bytes | None) -> None:
    text = _body_text(body)
    _setup().info(f"    → {method} {path}" + (f"\n        payload: {_short(text, _MAX_BODY)}" if text else ""))


def response(path: str, status: int | None, raw_text: str, error: str = "") -> None:
    log = _setup()
    if error:
        log.info(f"    ✗ {path}: {_short(error, _MAX_BODY)}")
        return
    if path.startswith("/api/login"):
        log.info(f"    ← HTTP {status} (risposta di login non registrata: contiene il token)")
        return
    limit = _MAX_LIST_RESPONSE if ("/tickets/list" in path or "/search/jql" in path) else _MAX_BODY
    log.info(f"    ← HTTP {status}  {_short(raw_text, limit) if raw_text.strip() else '(risposta vuota)'}")


def event(message: str) -> None:
    """High-level line (which row is being sent, how the ticket UUID was found…)."""
    _setup().info(message)
