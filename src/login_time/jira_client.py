"""Jira Cloud client for login_time (no Tk code here).

Authentication: Atlassian API token + account email (HTTP Basic), the method Atlassian
documents for scripts on accounts that sign in with SSO / two-step verification.
The token is created once by the user on id.atlassian.com after the normal
Microsoft + Duo login, and stored in Windows Credential Manager (see jira_settings).

- Classic tokens call the site directly:      https://<site>.atlassian.net/rest/api/3/...
- Tokens with scopes go through the gateway:  https://api.atlassian.com/ex/jira/<cloudId>/rest/api/3/...
  (cloudId from https://<site>.atlassian.net/_edge/tenant_info). Detected automatically.

Endpoints (REST API v3): myself, search/jql (the old /search was removed), issue/<key>,
issue/<key>/comment, issue/<key>/transitions, issue/<key>/worklog.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib import error, parse, request

from . import api_log

GATEWAY = "https://api.atlassian.com/ex/jira"
LIST_FIELDS = ["summary", "status", "priority", "issuetype", "project", "duedate", "updated", "assignee"]
DETAIL_FIELDS = LIST_FIELDS + ["description", "reporter", "created", "labels", "timetracking", "parent"]


class JiraAuthError(RuntimeError):
    """Token rejected (expired, revoked, wrong email or blocked by the admins)."""


@dataclass(slots=True)
class JiraResponse:
    status: int
    payload: Any


# ---------------------------------------------------------------- Atlassian Document Format

def text_to_adf(text: str) -> dict[str, Any]:
    """Plain text → ADF document: one paragraph per block, line breaks kept."""
    paragraphs = [p for p in text.replace("\r\n", "\n").split("\n\n") if p.strip()]
    content = []
    for paragraph in paragraphs or [text]:
        nodes: list[dict[str, Any]] = []
        for index, line in enumerate(paragraph.split("\n")):
            if index:
                nodes.append({"type": "hardBreak"})
            if line:
                nodes.append({"type": "text", "text": line})
        content.append({"type": "paragraph", "content": nodes})
    return {"type": "doc", "version": 1, "content": content}


def adf_to_text(node: Any) -> str:
    """ADF (descriptions, comments) → readable plain text."""
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "".join(adf_to_text(child) for child in node)
    if not isinstance(node, dict):
        return ""
    kind = node.get("type")
    attrs = node.get("attrs") or {}
    children = adf_to_text(node.get("content"))
    if kind == "text":
        return str(node.get("text", ""))
    if kind == "hardBreak":
        return "\n"
    if kind in {"mention", "emoji", "status", "date"}:
        return str(attrs.get("text") or attrs.get("shortName") or attrs.get("timestamp") or "")
    if kind in {"inlineCard", "blockCard", "embedCard"}:
        return str(attrs.get("url", ""))
    if kind == "listItem":
        return "• " + children.strip() + "\n"
    if kind in {"bulletList", "orderedList"}:
        return children + "\n"
    if kind in {"paragraph", "heading", "blockquote", "codeBlock", "panel", "rule", "mediaSingle", "table", "tableRow"}:
        return children.rstrip() + "\n\n"
    if kind in {"tableCell", "tableHeader"}:
        return children.strip() + " | "
    return children


def clean_text(text: str) -> str:
    lines = [line.rstrip() for line in text.replace("\xa0", " ").split("\n")]
    out = "\n".join(lines).strip()
    while "\n\n\n" in out:
        out = out.replace("\n\n\n", "\n\n")
    return out


# ---------------------------------------------------------------- client

class JiraClient:
    def __init__(self, site: str, email: str, token: str, timeout: int = 30) -> None:
        site = site.strip().rstrip("/")
        if not site.startswith("http"):
            site = "https://" + site
        self.site = site
        self.email = email.strip()
        self._token = token.strip()
        self.timeout = timeout
        self._base: str | None = None  # site or gateway, decided by connect()

    # ---- low level
    def _auth_header(self) -> str:
        raw = f"{self.email}:{self._token}".encode("utf-8")
        return "Basic " + base64.b64encode(raw).decode("ascii")

    def _send(self, method: str, url: str, payload: Any = None, *, auth: bool = True) -> JiraResponse:
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {"Accept": "application/json", "User-Agent": "login_time/1.0"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if auth:
            headers["Authorization"] = self._auth_header()  # never logged
        log_path = "jira " + url.replace(self.site, "").replace(GATEWAY, "gateway")
        api_log.request(method, log_path, body)
        req = request.Request(url, data=body, headers=headers, method=method)
        try:
            with request.urlopen(req, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8", errors="replace")
                api_log.response(log_path, response.status, raw)
                return JiraResponse(response.status, json.loads(raw) if raw.strip() else None)
        except error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            api_log.response(log_path, exc.code, "", error=f"HTTP {exc.code}: {raw}")
            if exc.code in (401, 403):
                raise JiraAuthError(self._auth_message(exc.code, raw)) from exc
            raise RuntimeError(f"Jira HTTP {exc.code}: {self._error_text(raw)}") from exc
        except (error.URLError, TimeoutError) as exc:
            reason = getattr(exc, "reason", exc)
            api_log.response(log_path, None, "", error=f"rete: {reason}")
            raise RuntimeError(f"Jira non raggiungibile: {reason}") from exc

    @staticmethod
    def _error_text(raw: str) -> str:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return raw[:300]
        messages = list(data.get("errorMessages") or []) + [f"{k}: {v}" for k, v in (data.get("errors") or {}).items()]
        return "; ".join(messages) or raw[:300]

    def _auth_message(self, code: int, raw: str) -> str:
        detail = self._error_text(raw)
        return (
            f"Jira ha rifiutato il token (HTTP {code}). Controlla email e token: potrebbe essere scaduto, "
            f"revocato o mancare uno scope. {detail}".strip()
        )

    def _api(self, method: str, path: str, *, params: dict[str, Any] | None = None, payload: Any = None) -> JiraResponse:
        base = self._base or self.connect()
        url = f"{base}/rest/api/3/{path.lstrip('/')}"
        if params:
            url += "?" + parse.urlencode({k: v for k, v in params.items() if v is not None})
        return self._send(method, url, payload)

    # ---- connection
    def connect(self) -> str:
        """Find which base URL accepts the token (classic → site, scoped → gateway)."""
        try:
            self._send("GET", f"{self.site}/rest/api/3/myself")
            self._base = self.site
            return self._base
        except JiraAuthError as site_error:
            try:
                info = self._send("GET", f"{self.site}/_edge/tenant_info", auth=False).payload
                cloud_id = str((info or {}).get("cloudId", ""))
            except Exception:  # noqa: BLE001 - keep the first error, it is the useful one
                raise site_error from None
            if not cloud_id:
                raise site_error
            gateway = f"{GATEWAY}/{cloud_id}"
            self._send("GET", f"{gateway}/rest/api/3/myself")
            self._base = gateway
            api_log.event("    jira: token con scope → uso il gateway api.atlassian.com")
            return gateway

    @property
    def uses_gateway(self) -> bool:
        return bool(self._base and self._base.startswith(GATEWAY))

    def myself(self) -> dict[str, Any]:
        payload = self._api("GET", "myself").payload
        return payload if isinstance(payload, dict) else {}

    # ---- issues
    def search(self, jql: str, *, fields: list[str] | None = None, max_results: int = 50, next_page_token: str | None = None) -> tuple[list[dict[str, Any]], str | None]:
        body: dict[str, Any] = {"jql": jql, "fields": fields or LIST_FIELDS, "maxResults": max_results}
        if next_page_token:
            body["nextPageToken"] = next_page_token
        payload = self._api("POST", "search/jql", payload=body).payload or {}
        issues = [issue for issue in payload.get("issues", []) if isinstance(issue, dict)]
        token = payload.get("nextPageToken")
        if payload.get("isLast") is True:
            token = None
        return issues, token

    def issue(self, key: str) -> dict[str, Any]:
        payload = self._api("GET", f"issue/{parse.quote(key)}", params={"fields": ",".join(DETAIL_FIELDS)}).payload
        return payload if isinstance(payload, dict) else {}

    def comments(self, key: str, max_results: int = 30) -> list[dict[str, Any]]:
        payload = self._api(
            "GET", f"issue/{parse.quote(key)}/comment", params={"orderBy": "-created", "maxResults": max_results}
        ).payload or {}
        return [c for c in payload.get("comments", []) if isinstance(c, dict)]

    def add_comment(self, key: str, text: str) -> dict[str, Any]:
        return self._api("POST", f"issue/{parse.quote(key)}/comment", payload={"body": text_to_adf(text)}).payload or {}

    def transitions(self, key: str) -> list[dict[str, Any]]:
        payload = self._api("GET", f"issue/{parse.quote(key)}/transitions").payload or {}
        return [t for t in payload.get("transitions", []) if isinstance(t, dict)]

    def transition(self, key: str, transition_id: str) -> None:
        self._api("POST", f"issue/{parse.quote(key)}/transitions", payload={"transition": {"id": str(transition_id)}})

    def add_worklog(self, key: str, seconds: int, started: datetime, comment: str = "") -> dict[str, Any]:
        body: dict[str, Any] = {"timeSpentSeconds": int(seconds), "started": format_started(started)}
        if comment.strip():
            body["comment"] = text_to_adf(comment)
        return self._api("POST", f"issue/{parse.quote(key)}/worklog", payload=body).payload or {}

    def browse_url(self, key: str) -> str:
        return f"{self.site}/browse/{key}"


def format_started(moment: datetime) -> str:
    """Jira wants yyyy-MM-dd'T'HH:mm:ss.SSS±hhmm (e.g. 2026-10-30T09:00:00.000+0100)."""
    local = moment if moment.tzinfo else moment.astimezone()
    return local.strftime("%Y-%m-%dT%H:%M:%S.000%z")
