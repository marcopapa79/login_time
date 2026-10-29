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

_HOURS_TOKEN = re.compile(r"(\d+(?:[.,]\d+)?)\s*([wdhm])", re.IGNORECASE)
# The portal shows totals in weeks too ("1 w", "2 w 1 d 4 h"): 1 w = 5 working days = 40 h.
_UNIT_HOURS = {"w": 40.0, "d": 8.0, "h": 1.0, "m": 1 / 60}


def portal_hours(value: object) -> float | None:
    """Hours from portal strings like "1 w", "2 w 1 d 4 h", "1 d 1 h", "8h", "30 m", "0.5h" or a number.
    Returns None when the text contains something that is not a known unit."""
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value or "").strip().lower()
    if not text:
        return None
    if re.fullmatch(r"\d+(?:[.,]\d+)?", text):
        return float(text.replace(",", "."))
    tokens = _HOURS_TOKEN.findall(text)
    leftover = _HOURS_TOKEN.sub("", text).strip()
    if not tokens or leftover:
        return None
    return sum(float(number.replace(",", ".")) * _UNIT_HOURS[unit.lower()] for number, unit in tokens)


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
        self._details: dict[str, dict[str, Any]] = {}
        self._posts_company: dict[str, str | None] = {}

    # ---- lookups
    def company_guid(self, token: str) -> str:
        """uuid of the Quixant company itself (the page sends it as idCompany)."""
        if self._company_guid is not None:
            return self._company_guid
        guid = ""
        try:
            payload = self.client.request_query("/api/companies", token).payload
            items = [item for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []
            # Only Quixant itself: other "system" companies exist and hide the internal notes.
            matches = [item for item in items if str(item.get("identifier", "")).strip().upper() == "QUIX"]
            if not matches:
                matches = [item for item in items if str(item.get("nome", "")).strip().lower() == "quixant"]
            if matches:
                guid = str(matches[0].get("uuid", ""))
                api_log.event(f"    idCompany Quixant = {guid} ({matches[0].get('nome', '')})")
            else:
                api_log.event("    idCompany: Quixant non trovata in /api/companies")
        except Exception as exc:  # noqa: BLE001 - fall back to the ticket's company
            api_log.event(f"    idCompany non trovato (/api/companies): {exc}")
        self._company_guid = guid
        return guid

    def ticket_details(self, token: str, ticket_uuid: str, *, refresh: bool = False) -> dict[str, Any]:
        """Ticket card data from tickets/select/<uuid> (same call the portal page makes)."""
        key = ticket_uuid.lower()
        if key in self._details and not refresh:
            return self._details[key]
        payload = self.client.request_query(f"/api/tickets/select/{key}", token).payload
        form = payload.get("form") if isinstance(payload, dict) else None
        summary = payload.get("list") if isinstance(payload, dict) else None
        if not isinstance(form, dict):
            raise RuntimeError("Risposta inattesa da tickets/select.")
        summary = summary if isinstance(summary, dict) else {}

        def clean(value: Any) -> str:
            text = "" if value is None else str(value).strip()
            return "" if text in {"None", "null"} else text

        details = {
            "id_ticket": clean(form.get("id_ticket")),
            "internal_id": clean(form.get("internal_id")),
            "title": clean(form.get("title") or summary.get("title")),
            "status": clean(form.get("status_name")),
            "company": clean(summary.get("company")),
            "company_uuid": clean(form.get("uuid_company")),
            "requester": clean(form.get("requester")),
            "severity": clean(summary.get("severity")) or clean(form.get("severity")),
            "type": clean(form.get("ticket_type_name")),
            "category": clean(form.get("ticket_category_name")),
            "project": clean(form.get("internal_project_name")),
            "created": clean(form.get("creation_date")),
            "updated": clean(form.get("last_update")),
            "assignees": ", ".join(str(a) for a in form.get("assignees") or []),
            "versions": " · ".join(
                f"{label} {clean(form.get(key))}"
                for label, key in (("BIOS", "BIOS_version"), ("FPGA", "FPGA_version"), ("LP", "LP_version"), ("Rev.", "revision"), ("Item", "item_code"))
                if clean(form.get(key))
            ),
            "internal_ticket": clean(form.get("internal_ticket")).lower() == "true",
            "closed": clean(form.get("is_closed")).lower() == "true",
            "description": html_to_text(clean(form.get("description"))),
        }
        if details["id_ticket"]:
            self._numeric_ids[key] = int(details["id_ticket"])
        self._details[key] = details
        return details

    def numeric_ticket_id(self, token: str, ticket_uuid: str) -> int:
        key = ticket_uuid.lower()
        if key in self._numeric_ids:
            return self._numeric_ids[key]
        details = self.ticket_details(token, ticket_uuid)
        if not details.get("id_ticket"):
            raise RuntimeError("Il portale non ha restituito l'id numerico del ticket (tickets/select).")
        return self._numeric_ids[key]

    # ---- posts
    def _posts_request(self, token: str, ticket_uuid: str, page: int, company: str | None) -> list[dict[str, Any]]:
        query: dict[str, Any] = {"page": page, "uuid": ticket_uuid.lower()}
        if company:
            query["idCompany"] = company
        payload = self.client.request_query("/api/ticket_posts/list", token, query).payload
        if not isinstance(payload, list):
            raise RuntimeError(f"Risposta inattesa da ticket_posts/list: {str(payload)[:200]}")
        return [post for post in payload if isinstance(post, dict)]

    @staticmethod
    def _real_posts(posts: list[dict[str, Any]]) -> int:
        """Messages, not the working-hours entries the list also returns (id_ticket_post = -1)."""
        return sum(1 for post in posts if str(post.get("id_ticket_post", "")) != "-1")

    def list_posts(self, token: str, ticket_uuid: str, page: int = 1, *, ticket_company: str = "") -> list[dict[str, Any]]:
        """Messages of a ticket, newest first, 10 per page.

        The page sends idCompany = Quixant. If that returns only working-hours entries, the
        request is retried without idCompany and with the ticket's company; the variant that
        returns most messages is remembered for the ticket.
        """
        key = ticket_uuid.lower()
        if key in self._posts_company:
            return self._posts_request(token, key, page, self._posts_company[key])

        quixant = self.company_guid(token)
        best_company: str | None = quixant or None
        best = self._posts_request(token, key, page, best_company)
        if page == 1 and self._real_posts(best) == 0 and ticket_company and ticket_company != best_company:
            # Last resort: the customer's company shows the public messages (internal notes may be hidden).
            for alternative in (ticket_company,):
                try:
                    candidate = self._posts_request(token, key, page, alternative)
                except Exception as exc:  # noqa: BLE001 - keep the first answer
                    api_log.event(f"    variante idCompany={alternative or '(nessuno)'} non riuscita: {exc}")
                    continue
                if self._real_posts(candidate) > self._real_posts(best):
                    best, best_company = candidate, alternative
            api_log.event(
                f"    messaggi: uso idCompany={best_company or '(nessuno)'} · {self._real_posts(best)} messaggi + "
                f"{len(best) - self._real_posts(best)} voci di ore"
            )
        self._posts_company[key] = best_company
        return best

    def posts_from_ticket_company(self, ticket_uuid: str, ticket_company: str) -> bool:
        """True when the messages were read with the customer's company (internal notes may be missing)."""
        used = self._posts_company.get(ticket_uuid.lower())
        return bool(used) and used == ticket_company and used != self._company_guid

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
