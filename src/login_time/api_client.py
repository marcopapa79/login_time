from __future__ import annotations

import json
from dataclasses import dataclass
import re
from typing import Any
from urllib import error, parse, request


DEFAULT_BASE_URL = "https://support.quixant.com"


@dataclass(slots=True)
class ApiResponse:
    status: int
    payload: Any
    raw_text: str


class QuixantHubClient:
    def __init__(self, base_url: str = DEFAULT_BASE_URL, timeout: int = 20) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def login(self, username: str, password: str) -> tuple[str, Any]:
        attempts = [
            ("/api/login", True),
            ("/api/login", False),
        ]

        last_error: Exception | None = None
        for path, use_json in attempts:
            try:
                body, content_type = self._build_login_body(username, password, use_json)
                response = self._send("POST", path, body=body, content_type=content_type)
                token = self._extract_token(response.payload)
                if token:
                    return token, response.payload
                raise RuntimeError("Login succeeded, but the response does not contain an access token.")
            except Exception as exc:  # noqa: BLE001 - retry across formats/endpoints
                last_error = exc

        raise RuntimeError(f"Unable to log in to Quixant Hub API: {last_error}")

    def request_json(
        self,
        method: str,
        path: str,
        token: str,
        payload: dict[str, Any] | None = None,
    ) -> ApiResponse:
        body = None
        content_type = None
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            content_type = "application/json"
        return self._send(method, path, token=token, body=body, content_type=content_type)

    def request_query(
        self,
        path: str,
        token: str,
        query: dict[str, Any] | None = None,
    ) -> ApiResponse:
        if query:
            encoded = parse.urlencode({key: str(value).lower() if isinstance(value, bool) else str(value) for key, value in query.items()})
            path = f"{path}?{encoded}"
        return self._send("GET", path, token=token)

    def resolve_ticket_uuid(self, token: str, ticket_reference: str) -> str:
        normalized_reference = ticket_reference.strip().upper()
        if self._looks_like_uuid(normalized_reference):
            return normalized_reference

        candidates = [
            ("/api/tickets/list2", {"closed": False, "archived": False}),
            ("/api/tickets/list2", {"closed": True, "archived": False}),
            ("/api/tickets/list", {"closed": False, "archived": False}),
            ("/api/tickets/list", {"closed": True, "archived": False}),
        ]

        for path, query in candidates:
            response = self.request_query(path, token, query)
            resolved = self._find_ticket_uuid(response.payload, normalized_reference)
            if resolved:
                return resolved

        raise RuntimeError(f"Unable to resolve ticket '{ticket_reference}' to a UUID via /api/tickets/list.")

    def request_raw(self, method: str, path: str, token: str, body_text: str) -> ApiResponse:
        body = body_text.encode("utf-8") if body_text.strip() else None
        content_type = "application/json" if body is not None else None
        return self._send(method, path, token=token, body=body, content_type=content_type)

    def _build_login_body(self, username: str, password: str, use_json: bool) -> tuple[bytes, str]:
        payload = {"username": username, "password": password}
        if use_json:
            return json.dumps(payload).encode("utf-8"), "application/json"
        return parse.urlencode(payload).encode("utf-8"), "application/x-www-form-urlencoded"

    def _send(
        self,
        method: str,
        path: str,
        token: str | None = None,
        body: bytes | None = None,
        content_type: str | None = None,
    ) -> ApiResponse:
        url = f"{self.base_url}{path}"
        headers = {
            "Accept": "application/json, text/plain, */*",
            "User-Agent": "login_time/1.0",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if content_type:
            headers["Content-Type"] = content_type

        request_obj = request.Request(url, data=body, headers=headers, method=method.upper())

        try:
            with request.urlopen(request_obj, timeout=self.timeout) as response:
                raw_text = response.read().decode("utf-8", errors="replace")
                return ApiResponse(response.status, self._decode_payload(raw_text), raw_text)
        except error.HTTPError as exc:
            raw_text = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {exc.code} calling {path}: {raw_text[:400]}") from exc

    def _decode_payload(self, raw_text: str) -> Any:
        if not raw_text.strip():
            return ""

        try:
            return json.loads(raw_text)
        except json.JSONDecodeError:
            return raw_text

    def _extract_token(self, payload: Any) -> str:
        if isinstance(payload, dict):
            for key in ("accessToken", "access_token", "token", "jwt", "bearerToken"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()

            for value in payload.values():
                nested = self._extract_token(value)
                if nested:
                    return nested

        if isinstance(payload, list):
            for item in payload:
                nested = self._extract_token(item)
                if nested:
                    return nested

        if isinstance(payload, str) and payload.count(".") == 2 and len(payload) > 20:
            return payload.strip()

        return ""

    def _find_ticket_uuid(self, payload: Any, ticket_reference: str) -> str:
        if isinstance(payload, dict):
            internal_id = payload.get("internal_id") or payload.get("InternalId") or payload.get("ticket") or payload.get("TicketId")
            uuid = payload.get("uuid") or payload.get("UUID")
            if uuid and internal_id and self._ticket_matches(str(internal_id), ticket_reference):
                return str(uuid).upper()

            for value in payload.values():
                resolved = self._find_ticket_uuid(value, ticket_reference)
                if resolved:
                    return resolved

        if isinstance(payload, list):
            for item in payload:
                resolved = self._find_ticket_uuid(item, ticket_reference)
                if resolved:
                    return resolved

        return ""

    def _ticket_matches(self, candidate: str, ticket_reference: str) -> bool:
        normalized_candidate = candidate.strip().upper()
        normalized_reference = ticket_reference.strip().upper()
        if normalized_candidate == normalized_reference:
            return True

        candidate_digits = re.sub(r"\D", "", normalized_candidate)
        reference_digits = re.sub(r"\D", "", normalized_reference)
        return bool(candidate_digits and reference_digits and candidate_digits == reference_digits)

    def _looks_like_uuid(self, value: str) -> bool:
        return bool(re.fullmatch(r"[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}", value.strip().upper()))