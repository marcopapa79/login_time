"""Quixant Hub ticket operations used by the app (no Tk code here).

Endpoints and field names mirror what the portal's own ticket page sends
(captured from /ticket/Edit/<code> in October 2026):

- ticket_posts/list     GET  page, uuid (ticket), idCompany (Quixant company uuid)
- ticket_posts/create   POST form: uuid (new guid), id_ticket (numeric), text (HTML),
                              attachments, public ("true"/"false"), time_spent ("1h")
- tickets/select/<uuid> GET  -> form.id_ticket
- working_hours/list    GET  ticketGuid -> [{Id, Username, FullName, Month, WorkingTime, Reason, ...}]
- working_hours/form    POST same payload as a new entry + Id  -> updates that entry
- working_hours/delete  GET  uuid=<entry Id>
- tickets/get_times     GET  ticketGuid -> working_times / extra_times per month and person
"""

from __future__ import annotations

import html
import re
from html.parser import HTMLParser
from typing import Any

from . import api_log
from .api_client import QuixantHubClient

# ---------------------------------------------------------------- hours helpers

_HOURS_TOKEN = re.compile(r"(\d+(?:[.,]\d+)?)\s*([dhm])", re.IGNORECASE)


def portal_hours(value: object) -> float | None:
    """Hours from portal strings like "1 d 1 h", "1d", "8h", "30 m", "0.5h" or a number."""
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value or "").strip().lower()
    if not text:
        return None
    if re.fullmatch(r"\d+(?:[.,]\d+)?", text):
        return float(text.replace(",", "."))
    total = 0.0
    found = False
    for number, unit in _HOURS_TOKEN.findall(text):
        amount = float(number.replace(",", "."))
        found = True
        total += amount * 8 if unit == "d" else amount / 60 if unit == "m" else amount
    return total if found else None


# ---------------------------------------------------------------- text helpers

class _TextExtractor(HTMLParser):
    _BREAKS = {"br", "p", "div", "li", "tr", "h1", "h2", "h3", "h4", "pre", "blockquote"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "li":
            self.parts.append("\n• ")
        elif tag in self._BREAKS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._BREAKS and tag != "li":
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def html_to_text(value: str) -> str:
    parser = _TextExtractor()
    parser.feed(value or "")
    parser.close()
    text = "".join(parser.parts).replace("\xa0", " ")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def text_to_html(value: str) -> str:
    """Plain text from the app's editor -> the simple HTML the portal editor produces."""
    paragraphs = [p for p in re.split(r"\n\s*\n", value.strip()) if p.strip()]
    return "".join(f"<p>{html.escape(p).replace(chr(10), '<br />')}</p>" for p in paragraphs)


# ---------------------------------------------------------------- portal session

class PortalTickets:
    """Ticket-level helpers sharing small caches (company uuid, numeric ticket ids)."""

    def __init__(self, client: QuixantHubClient) -> None:
        self.client = client
        self._company_guid: str | None = None
        self._numeric_ids: dict[str, int] = {}

    # ---- lookups
    def company_guid(self, token: str) -> str:
        """uuid of the Quixant company itself (the page sends it as idCompany)."""
        if self._company_guid is not None:
            return self._company_guid
        guid = ""
        try:
            payload = self.client.request_query("/api/companies", token).payload
            items = payload if isinstance(payload, list) else []
            for item in items:
                if not isinstance(item, dict):
                    continue
                if str(item.get("identifier", "")).upper() == "QUIX" or str(item.get("system", "")).lower() == "true":
                    guid = str(item.get("uuid", ""))
                    break
        except Exception as exc:  # noqa: BLE001 - the posts list may still work without it
            api_log.event(f"    idCompany non trovato (/api/companies): {exc}")
        self._company_guid = guid
        return guid

    def numeric_ticket_id(self, token: str, ticket_uuid: str) -> int:
        key = ticket_uuid.lower()
        if key in self._numeric_ids:
            return self._numeric_ids[key]
        payload = self.client.request_query(f"/api/tickets/select/{key}", token).payload
        form = payload.get("form") if isinstance(payload, dict) else None
        value = form.get("id_ticket") if isinstance(form, dict) else None
        if value in (None, ""):
            raise RuntimeError("Il portale non ha restituito l'id numerico del ticket (tickets/select).")
        self._numeric_ids[key] = int(value)
        return int(value)

    # ---- posts
    def list_posts(self, token: str, ticket_uuid: str, page: int = 1) -> list[dict[str, Any]]:
        query: dict[str, Any] = {"page": page, "uuid": ticket_uuid.lower()}
        company = self.company_guid(token)
        if company:
            query["idCompany"] = company
        payload = self.client.request_query("/api/ticket_posts/list", token, query).payload
        if not isinstance(payload, list):
            raise RuntimeError(f"Risposta inattesa da ticket_posts/list: {str(payload)[:200]}")
        return [post for post in payload if isinstance(post, dict)]

    def create_post(self, token: str, ticket_uuid: str, text: str, *, public: bool, time_spent: str = "") -> dict[str, Any]:
        guid_payload = self.client.request_query("/api/tickets/newguid", token).payload
        post_uuid = str(guid_payload.get("guid", "")) if isinstance(guid_payload, dict) else ""
        if not post_uuid:
            raise RuntimeError("Il portale non ha restituito un GUID per il nuovo messaggio (tickets/newguid).")
        data = {
            "uuid": post_uuid,
            "id_ticket": str(self.numeric_ticket_id(token, ticket_uuid)),
            "text": text_to_html(text),
            "attachments": "",
            "public": "true" if public else "false",
        }
        if time_spent:
            data["time_spent"] = time_spent
        payload = self.client.request_form("POST", "/api/ticket_posts/create", token, data).payload
        if isinstance(payload, dict) and payload.get("mail_error"):
            api_log.event(f"    nota creata ma errore email: {payload.get('mail_error')}")
        result = dict(payload) if isinstance(payload, dict) else {}
        result.setdefault("post_uuid", post_uuid)
        return result

    # ---- working hours
    def list_working_hours(self, token: str, ticket_uuid: str) -> list[dict[str, Any]]:
        payload = self.client.request_query("/api/working_hours/list", token, {"ticketGuid": ticket_uuid.lower()}).payload
        return [item for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []

    def delete_working_hours(self, token: str, entry_id: str) -> None:
        self.client.request_query("/api/working_hours/delete", token, {"uuid": entry_id})

    def get_times(self, token: str, ticket_uuid: str) -> dict[str, Any]:
        payload = self.client.request_query("/api/tickets/get_times", token, {"ticketGuid": ticket_uuid.lower()}).payload
        return payload if isinstance(payload, dict) else {}


def find_entry_id(
    entries: list[dict[str, Any]],
    *,
    username: str,
    month_label: str,
    hours: float,
    reason: str,
    exclude_ids: set[str] | frozenset[str] = frozenset(),
) -> str:
    """Id of the portal working-hours entry matching a local row, or "" if none/ambiguous-free match.

    Duplicates on the portal (same month, hours and reason) are resolved by taking the first
    one not already linked to another local row.
    """
    wanted_reason = re.sub(r"\s+", " ", reason).strip().lower()
    for item in entries:
        entry_id = str(item.get("Id", "")).strip()
        if not entry_id or entry_id.upper() in exclude_ids:
            continue
        if str(item.get("Username", "")).strip().lower() != username.strip().lower():
            continue
        if str(item.get("Month", "")).strip().lower() != month_label.strip().lower():
            continue
        item_hours = portal_hours(item.get("WorkingTime"))
        if item_hours is None or abs(item_hours - hours) > 1e-6:
            continue
        if re.sub(r"\s+", " ", str(item.get("Reason", ""))).strip().lower() != wanted_reason:
            continue
        return entry_id
    return ""
