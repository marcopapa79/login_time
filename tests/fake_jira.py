"""Tiny in-process Jira Cloud stand-in for the tests (no network, no real data).

Accepts the "classic" token on the site URLs and the "scoped" token only through the
gateway path /ex/jira/<cloudId>/..., like Atlassian does. It also plays auth.atlassian.com
for the OAuth login: /oauth/token (code exchange, rotating refresh tokens) and
/oauth/token/accessible-resources; OAuth access tokens work on the gateway only.
"""

from __future__ import annotations

import base64
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

EMAIL = "marco.papa@example.com"
CLASSIC_TOKEN = "classic-token-123"
SCOPED_TOKEN = "scoped-token-456"
CLOUD_ID = "cloud-0001"
CLIENT_ID = "client-id-abc"
CLIENT_SECRET = "client-secret-xyz"
AUTH_CODE = "auth-code-123"
SITE_URL = "https://quixantplc.atlassian.net"


def _adf(text: str) -> dict:
    return {"type": "doc", "version": 1, "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}]}


def _issue(key: str, summary: str, status: str, category: str, *, priority="Medium", kind="Task", due=None, updated="2026-10-29T16:20:00.000+0100") -> dict:
    return {
        "id": str(abs(hash(key)) % 100000),
        "key": key,
        "fields": {
            "summary": summary,
            "status": {"name": status, "statusCategory": {"key": category}},
            "priority": {"name": priority},
            "issuetype": {"name": kind},
            "project": {"key": key.split("-")[0], "name": "Platform Firmware" if key.startswith("PF") else "Customer Support"},
            "duedate": due,
            "updated": updated,
            "created": "2026-10-01T09:00:00.000+0200",
            "assignee": {"displayName": "Marco Papa"},
            "reporter": {"displayName": "Giulia Rossi"},
            "labels": ["bios", "qx-70"] if key == "PF-412" else [],
            "timetracking": {"timeSpent": "3h", "remainingEstimate": "5h"} if key == "PF-412" else {},
            "description": _adf("La scheda QX-70 non completa il boot dopo l'aggiornamento BIOS 2.14.\n\nPassi: aggiornare, riavviare due volte."),
        },
    }


class FakeJira:
    def __init__(self) -> None:
        self.issues = [
            _issue("PF-412", "QX-70: boot loop dopo aggiornamento BIOS 2.14", "In Progress", "indeterminate", priority="High", kind="Bug", due="2026-11-05"),
            _issue("PF-398", "Driver watchdog: timeout configurabile da registro", "To Do", "new", updated="2026-10-27T10:05:00.000+0100"),
            _issue("CS-77", "Documentare procedura RMA per clienti EMEA", "In Review", "indeterminate", kind="Story", updated="2026-10-22T08:40:00.000+0200"),
            _issue("PF-350", "Aggiornare toolchain build a GCC 13", "Done", "done", updated="2026-10-15T12:00:00.000+0200"),
        ]
        self.comments: dict[str, list[dict]] = {
            "PF-412": [
                {"id": "2", "author": {"displayName": "Giulia Rossi"}, "created": "2026-10-29T15:10:00.000+0100", "body": _adf("Riprodotto anche su una seconda unità.")},
                {"id": "1", "author": {"displayName": "Marco Papa"}, "created": "2026-10-28T11:02:00.000+0100", "body": _adf("Sto raccogliendo i log seriali.")},
            ]
        }
        self.worklogs: list[dict] = []
        self.transitions_done: list[tuple[str, str]] = []
        self.requests: list[tuple[str, str, dict | None]] = []
        self.auth_headers: list[str] = []
        # OAuth
        self.access_tokens: set[str] = set()
        self.refresh_tokens: set[str] = set()
        self.grants: list[str] = []
        self._counter = 0
        self._lock = threading.Lock()
        self.resource_scopes = ["read:jira-work", "write:jira-work", "read:jira-user"]
        self.resource_url = SITE_URL
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def start(self) -> "FakeJira":
        self.thread.start()
        return self

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def expire_access_tokens(self) -> None:
        self.access_tokens.clear()

    def _issue_tokens(self) -> dict:
        with self._lock:
            self._counter += 1
            n = self._counter
        access, refresh = f"at-{n}", f"rt-{n}-" + "r" * 1800  # long, like real JWT refresh tokens
        self.access_tokens.add(access)
        self.refresh_tokens.add(refresh)
        return {"access_token": access, "expires_in": 3600, "refresh_token": refresh, "token_type": "Bearer",
                "scope": "read:jira-work write:jira-work read:jira-user offline_access"}

    def _token_endpoint(self, body: dict) -> tuple[int, dict]:
        grant = str(body.get("grant_type", ""))
        self.grants.append(grant)
        if body.get("client_id") != CLIENT_ID or body.get("client_secret") != CLIENT_SECRET:
            return 401, {"error": "invalid_client", "error_description": "Unauthorized"}
        if grant == "authorization_code":
            if body.get("code") != AUTH_CODE or body.get("redirect_uri") != "http://localhost:53682/callback":
                return 403, {"error": "invalid_grant", "error_description": "Invalid authorization code"}
            return 200, self._issue_tokens()
        if grant == "refresh_token":
            with self._lock:
                token = str(body.get("refresh_token", ""))
                if token not in self.refresh_tokens:
                    return 403, {"error": "invalid_grant", "error_description": "Unknown or invalid refresh token."}
                self.refresh_tokens.discard(token)  # rotation: the used one stops working
            return 200, self._issue_tokens()
        return 400, {"error": "unsupported_grant_type"}

    # ------------------------------------------------------------------ handler
    def _handler(self):
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):  # keep test output clean
                return

            def _reply(self, status: int, payload=None) -> None:
                raw = b"" if payload is None else json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                if raw:
                    self.wfile.write(raw)

            def _token(self) -> str:
                header = self.headers.get("Authorization", "")
                if header:
                    fake.auth_headers.append(header)
                if header.startswith("Bearer "):
                    return "bearer:" + header[7:]
                if not header.startswith("Basic "):
                    return ""
                email, _, token = base64.b64decode(header[6:]).decode("utf-8").partition(":")
                return token if email == EMAIL else ""

            def _route(self, method: str) -> None:
                parsed = urlparse(self.path)
                path = parsed.path
                query = parse_qs(parsed.query)
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"null") if length else None
                fake.requests.append((method, self.path, body))

                if path == "/_edge/tenant_info":
                    return self._reply(200, {"cloudId": CLOUD_ID})
                if path == "/oauth/token" and method == "POST":
                    status, payload = fake._token_endpoint(body or {})
                    return self._reply(status, payload)
                token = self._token()
                bearer_ok = token.startswith("bearer:") and token[7:] in fake.access_tokens
                if path == "/oauth/token/accessible-resources":
                    if not bearer_ok:
                        return self._reply(401, {"code": 401, "message": "Unauthorized"})
                    return self._reply(200, [{"id": CLOUD_ID, "url": fake.resource_url, "name": "quixantplc",
                                              "scopes": fake.resource_scopes, "avatarUrl": ""}])
                gateway_prefix = f"/ex/jira/{CLOUD_ID}"
                if path.startswith(gateway_prefix):
                    path = path[len(gateway_prefix):]
                    allowed = token == SCOPED_TOKEN or bearer_ok
                else:
                    allowed = token == CLASSIC_TOKEN
                if not allowed:
                    return self._reply(401, {"errorMessages": ["Client must be authenticated to access this resource."]})
                if not path.startswith("/rest/api/3/"):
                    return self._reply(404, {"errorMessages": ["not found"]})
                return self._api(method, path[len("/rest/api/3/"):], query, body)

            def _api(self, method: str, path: str, query: dict, body):
                parts = path.split("/")
                if path == "myself":
                    return self._reply(200, {"accountId": "acc-1", "displayName": "Marco Papa", "emailAddress": EMAIL})
                if path == "search/jql" and method == "POST":
                    jql = str(body.get("jql", ""))
                    if "statusCategory = Done" in jql:
                        items = [i for i in fake.issues if i["fields"]["status"]["statusCategory"]["key"] == "done"]
                    else:
                        items = [i for i in fake.issues if i["fields"]["status"]["statusCategory"]["key"] != "done"]
                    limit = int(body.get("maxResults", 50))
                    start = int(body.get("nextPageToken") or 0)
                    page = items[start:start + limit]
                    more = start + limit < len(items)
                    payload = {"issues": page, "isLast": not more}
                    if more:
                        payload["nextPageToken"] = str(start + limit)
                    return self._reply(200, payload)
                if parts[0] == "issue" and len(parts) >= 2:
                    key = parts[1]
                    issue = next((i for i in fake.issues if i["key"] == key), None)
                    if issue is None:
                        return self._reply(404, {"errorMessages": ["Issue does not exist or you do not have permission to see it."]})
                    tail = parts[2] if len(parts) > 2 else ""
                    if not tail and method == "GET":
                        return self._reply(200, issue)
                    if tail == "comment" and method == "GET":
                        items = fake.comments.get(key, [])
                        return self._reply(200, {"comments": items, "total": len(items)})
                    if tail == "comment" and method == "POST":
                        comment = {"id": str(len(fake.comments.get(key, [])) + 10), "author": {"displayName": "Marco Papa"},
                                   "created": "2026-10-30T10:00:00.000+0100", "body": body["body"]}
                        fake.comments.setdefault(key, []).insert(0, comment)
                        return self._reply(201, comment)
                    if tail == "transitions" and method == "GET":
                        return self._reply(200, {"transitions": [
                            {"id": "11", "name": "To Do", "to": {"name": "To Do"}},
                            {"id": "21", "name": "In Progress", "to": {"name": "In Progress"}},
                            {"id": "31", "name": "Done", "to": {"name": "Done"}},
                        ]})
                    if tail == "transitions" and method == "POST":
                        target = {"11": ("To Do", "new"), "21": ("In Progress", "indeterminate"), "31": ("Done", "done")}[body["transition"]["id"]]
                        issue["fields"]["status"] = {"name": target[0], "statusCategory": {"key": target[1]}}
                        fake.transitions_done.append((key, body["transition"]["id"]))
                        return self._reply(204)
                    if tail == "worklog" and method == "POST":
                        fake.worklogs.append({"key": key, **body})
                        return self._reply(201, {"id": str(len(fake.worklogs)), **body})
                return self._reply(404, {"errorMessages": [f"unknown {method} {path}"]})

            def do_GET(self):
                self._route("GET")

            def do_POST(self):
                self._route("POST")

        return Handler
