"""Atlassian OAuth 2.0 (3LO) login for the Jira page: browser login with Microsoft + Duo.

Flow (no Tk code here, it runs in a background job):
1. a tiny HTTP server listens on 127.0.0.1:53682 (only this PC);
2. the browser opens auth.atlassian.com → normal company login (Microsoft, password, Duo)
   → "Accept"; Atlassian redirects to http://localhost:53682/callback?code=…&state=…;
3. the code is exchanged for an access token (about 1 h, kept in memory) and a refresh
   token (stored in Windows Credential Manager by config.py);
4. later the refresh token gives new access tokens without asking Duo again. Atlassian
   rotates it at every use (the new one must be saved) and it expires after 90 days unused.

Atlassian's 3LO needs the app's client secret for the token exchange (no PKCE). The
secret identifies the "check_ticket" integration, not the user: without your login + Duo
it gives no access to Jira. It is kept in Credential Manager too.
"""

from __future__ import annotations

import html
import json
import secrets
import socket
import socketserver
import threading
import time
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Callable
from urllib import error, parse, request

from . import api_log

AUTHORIZE_URL = "https://auth.atlassian.com/authorize"
TOKEN_URL = "https://auth.atlassian.com/oauth/token"
RESOURCES_URL = "https://api.atlassian.com/oauth/token/accessible-resources"
CONSOLE_URL = "https://developer.atlassian.com/console/myapps/"
CONNECTED_APPS_URL = "https://id.atlassian.com/manage-profile/apps"
REDIRECT_PORT = 53682
REDIRECT_URI = f"http://localhost:{REDIRECT_PORT}/callback"
# Same scopes as the API token + offline_access (without it Atlassian gives no refresh token).
SCOPES = ["read:jira-work", "write:jira-work", "read:jira-user", "offline_access"]
LOGIN_TIMEOUT_S = 300
_REFRESH_MARGIN_S = 60


class OAuthError(RuntimeError):
    """Login failed or was cancelled (message is shown to the user)."""


class OAuthLoginRequired(OAuthError):
    """The refresh token is expired or revoked: a new browser login (with Duo) is needed."""


@dataclass
class Tokens:
    access_token: str
    expires_at: float
    refresh_token: str


def host_of(site: str) -> str:
    return site.replace("https://", "").replace("http://", "").strip("/").lower()


def authorize_url(client_id: str, state: str) -> str:
    query = {
        "audience": "api.atlassian.com",
        "client_id": client_id,
        "scope": " ".join(SCOPES),
        "redirect_uri": REDIRECT_URI,
        "state": state,
        "response_type": "code",
        "prompt": "consent",
    }
    return f"{AUTHORIZE_URL}?{parse.urlencode(query, quote_via=parse.quote)}"


# ---------------------------------------------------------------- HTTP helpers

def _post_json(url: str, payload: dict[str, Any], timeout: int, what: str) -> dict[str, Any]:
    """POST to the token endpoint. Body and response hold secrets: only the outcome is logged."""
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(url, data=body, method="POST", headers={
        "Content-Type": "application/json", "Accept": "application/json", "User-Agent": "login_time/1.0",
    })
    api_log.event(f"    → POST {url} ({what}; codice, secret e token non registrati)")
    try:
        with request.urlopen(req, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8") or "{}")
            api_log.event(f"    ← HTTP {response.status} ({what} riuscito)")
            return data if isinstance(data, dict) else {}
    except error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(raw)
        except json.JSONDecodeError:
            detail = {}
        code = str(detail.get("error", "")) if isinstance(detail, dict) else ""
        text = str(detail.get("error_description", "")) if isinstance(detail, dict) else ""
        api_log.event(f"    ✗ {what}: HTTP {exc.code} {code} {text}".rstrip())
        if code == "invalid_grant":
            raise OAuthLoginRequired(
                "Il collegamento con Atlassian è scaduto o è stato revocato: rifai il login (Microsoft + Duo)."
            ) from exc
        if code in ("invalid_client", "unauthorized_client", "access_denied"):
            raise OAuthError(f"Atlassian ha rifiutato l'app ({code}): controlla Client ID e Secret. {text}".strip()) from exc
        raise OAuthError(f"Atlassian HTTP {exc.code}: {code or raw[:200]} {text}".strip()) from exc
    except (error.URLError, TimeoutError, socket.timeout) as exc:
        reason = getattr(exc, "reason", exc)
        api_log.event(f"    ✗ {what}: rete: {reason}")
        raise OAuthError(f"Atlassian non raggiungibile: {reason}") from exc


def _tokens_from(data: dict[str, Any], previous_refresh: str = "") -> Tokens:
    access = str(data.get("access_token", ""))
    if not access:
        raise OAuthError("Atlassian non ha restituito un access token.")
    try:
        expires_in = int(data.get("expires_in", 3600))
    except (TypeError, ValueError):
        expires_in = 3600
    refresh = str(data.get("refresh_token", "")) or previous_refresh
    return Tokens(access, time.time() + max(expires_in, 60), refresh)


def exchange_code(client_id: str, client_secret: str, code: str, *, timeout: int = 30, token_url: str | None = None) -> Tokens:
    data = _post_json(token_url or TOKEN_URL, {
        "grant_type": "authorization_code",
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "redirect_uri": REDIRECT_URI,
    }, timeout, "scambio del codice")
    tokens = _tokens_from(data)
    if not tokens.refresh_token:
        raise OAuthError("Atlassian non ha restituito il token di rinnovo (scope offline_access mancante?).")
    return tokens


def refresh_tokens(client_id: str, client_secret: str, refresh_token: str, *, timeout: int = 30, token_url: str | None = None) -> Tokens:
    data = _post_json(token_url or TOKEN_URL, {
        "grant_type": "refresh_token",
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
    }, timeout, "rinnovo del token")
    return _tokens_from(data, refresh_token)


def accessible_resources(access_token: str, *, timeout: int = 30, url: str | None = None) -> list[dict[str, Any]]:
    url = url or RESOURCES_URL
    req = request.Request(url, headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json", "User-Agent": "login_time/1.0"})
    api_log.event(f"    → GET {url}")
    try:
        with request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            api_log.event(f"    ← HTTP {response.status}  {raw[:400]}")
            data = json.loads(raw or "[]")
    except error.HTTPError as exc:
        api_log.event(f"    ✗ accessible-resources: HTTP {exc.code}")
        raise OAuthError(f"Atlassian HTTP {exc.code} leggendo i siti autorizzati") from exc
    except (error.URLError, TimeoutError, socket.timeout) as exc:
        raise OAuthError(f"Atlassian non raggiungibile: {getattr(exc, 'reason', exc)}") from exc
    return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []


def pick_site(resources: list[dict[str, Any]], site: str) -> dict[str, Any]:
    """The authorized resource for our site (Resource-level apps list only the site chosen at consent)."""
    wanted = host_of(site)
    for item in resources:
        if host_of(str(item.get("url", ""))) == wanted:
            return item
    if not wanted and len(resources) == 1:
        return resources[0]
    names = ", ".join(host_of(str(item.get("url", ""))) for item in resources) or "nessuno"
    raise OAuthError(
        f"L'autorizzazione non comprende {wanted or 'il sito Jira'} (siti autorizzati: {names}). "
        "Rifai il login e, nella pagina di consenso, scegli quel sito."
    )


# ---------------------------------------------------------------- session (shared by page and issue windows)

class OAuthSession:
    """Gives a valid access token, refreshing it when needed. Thread-safe: the Jira page and the
    issue windows run their calls in different worker threads but must not refresh twice
    (Atlassian rotates the refresh token at every use)."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        cloud_id: str,
        *,
        on_rotate: Callable[[str], None] | None = None,
        tokens: Tokens | None = None,
        timeout: int = 30,
        token_url: str | None = None,
    ) -> None:
        self.client_id = client_id
        self._client_secret = client_secret
        self._refresh_token = refresh_token
        self.cloud_id = cloud_id
        self.on_rotate = on_rotate
        self.timeout = timeout
        self.token_url = token_url
        self._access = tokens.access_token if tokens else ""
        self._expires_at = tokens.expires_at if tokens else 0.0
        self._lock = threading.Lock()

    @property
    def refresh_token(self) -> str:
        return self._refresh_token

    def access_token(self) -> str:
        with self._lock:
            if not self._access or time.time() >= self._expires_at - _REFRESH_MARGIN_S:
                self._refresh()
            return self._access

    def invalidate(self, used_token: str) -> None:
        """The API refused used_token: refresh at the next call (unless another thread already did)."""
        with self._lock:
            if self._access == used_token:
                self._access = ""

    def forget(self) -> None:
        with self._lock:
            self._access = ""
            self._refresh_token = ""
            self._client_secret = ""

    def _refresh(self) -> None:
        if not self._refresh_token:
            raise OAuthLoginRequired("Jira non è collegato: fai il login con Atlassian (Microsoft + Duo).")
        tokens = refresh_tokens(self.client_id, self._client_secret, self._refresh_token, timeout=self.timeout, token_url=self.token_url)
        rotated = tokens.refresh_token != self._refresh_token
        self._access, self._expires_at, self._refresh_token = tokens.access_token, tokens.expires_at, tokens.refresh_token
        if rotated and self.on_rotate is not None:
            self.on_rotate(tokens.refresh_token)  # save it now: the old one stops working


# ---------------------------------------------------------------- browser login

_PAGE = """<!doctype html><html lang="it"><head><meta charset="utf-8"><title>login_time · Jira</title>
<style>body{{background:#17181c;color:#f4f4f6;font:16px "Segoe UI",sans-serif;display:flex;align-items:center;
justify-content:center;height:100vh;margin:0}}div{{background:#202227;border:1px solid #33363e;padding:32px 40px;max-width:520px}}
h1{{font-size:20px;margin:0 0 12px;color:{color}}}p{{color:#a9abb6;line-height:1.5;margin:0}}</style></head>
<body><div><h1>{title}</h1><p>{text}</p></div></body></html>"""


class _Shared:
    """What the IPv4 and IPv6 listeners share: the expected state and the answer."""

    def __init__(self, state: str) -> None:
        self.expected_state = state
        self.result: dict[str, str] | None = None
        self.done = threading.Event()
        self.lock = threading.Lock()


class _CallbackServer(HTTPServer):
    allow_reuse_address = False
    shared: _Shared

    def server_bind(self) -> None:
        # Windows: no other program may bind the same port while we wait for the code.
        exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
        if exclusive is not None:
            self.socket.setsockopt(socket.SOL_SOCKET, exclusive, 1)
        # TCPServer.server_bind, without HTTPServer's reverse-DNS lookup (slow on some company networks).
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = "localhost", self.server_address[1]


def _handler_class() -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server: _CallbackServer

        def log_message(self, *_args: object) -> None:  # never print codes to the console
            return

        def _page(self, status: int, title: str, text: str, ok: bool) -> None:
            body = _PAGE.format(title=html.escape(title), text=html.escape(text), color="#6fcf7a" if ok else "#ff8f80").encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802 - http.server API
            parsed = parse.urlparse(self.path)
            if parsed.path != "/callback":
                self._page(404, "Pagina non trovata", "Questa è la pagina di ritorno del login di login_time.", False)
                return
            query = {k: v[0] for k, v in parse.parse_qs(parsed.query).items()}
            shared = self.server.shared
            with shared.lock:
                if shared.result is not None:
                    self._page(200, "Già fatto", "Il login è già stato ricevuto: puoi chiudere questa scheda.", True)
                    return
                if query.get("state") != shared.expected_state:
                    # Not the answer to our request (old tab, or someone else's link): ignore it.
                    self._page(400, "Richiesta non valida", "Questo link non corrisponde al login avviato da login_time. Riprova dall'app.", False)
                    return
                if query.get("error"):
                    shared.result = {"error": query.get("error", ""), "error_description": query.get("error_description", "")}
                    self._page(200, "Accesso non autorizzato", "Hai annullato o Atlassian ha rifiutato l'accesso. Torna a login_time.", False)
                elif query.get("code"):
                    shared.result = {"code": query["code"]}
                    self._page(200, "Login ricevuto", "Puoi chiudere questa scheda e tornare a login_time: l'app completa il collegamento con Jira.", True)
                else:
                    self._page(400, "Risposta incompleta", "Manca il codice di autorizzazione. Riprova dall'app.", False)
                    return
                shared.done.set()

    return Handler


class _CallbackServer6(_CallbackServer):
    address_family = socket.AF_INET6


def _open_servers(port: int, shared: _Shared) -> list[_CallbackServer]:
    """Listen on 127.0.0.1 (required) and ::1 (if available): "localhost" in the browser may be
    either. Loopback only: nothing is reachable from the network."""
    try:
        servers: list[_CallbackServer] = [_CallbackServer(("127.0.0.1", port), _handler_class())]
    except OSError as exc:
        raise OAuthError(
            f"La porta {port} è occupata (forse un altro login è ancora aperto): chiudi l'altra finestra e riprova."
        ) from exc
    try:
        servers.append(_CallbackServer6(("::1", port), _handler_class()))
    except OSError:
        pass  # no IPv6 loopback: the browser falls back to 127.0.0.1
    for server in servers:
        server.shared = shared
    return servers


def wait_for_code(
    client_id: str,
    *,
    cancel: threading.Event,
    open_browser: Callable[[str], object] | None = None,
    port: int | None = None,
    timeout_s: float = LOGIN_TIMEOUT_S,
) -> str:
    """Open the Atlassian login in the browser and wait for the redirect with the code."""
    state = secrets.token_urlsafe(24)
    shared = _Shared(state)
    servers = _open_servers(port or REDIRECT_PORT, shared)
    for server in servers:
        threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.2}, daemon=True).start()
    try:
        api_log.event(f"    browser: login Atlassian (ritorno su {REDIRECT_URI})")
        (open_browser or webbrowser.open)(authorize_url(client_id, state))
        deadline = time.monotonic() + timeout_s
        while not shared.done.wait(0.25):
            if cancel.is_set():
                raise OAuthError("Login annullato.")
            if time.monotonic() > deadline:
                raise OAuthError("Tempo scaduto: il login nel browser non è stato completato entro 5 minuti.")
        result = shared.result or {}
    finally:
        for server in servers:
            server.shutdown()
            server.server_close()
    if result.get("error"):
        if result["error"] == "access_denied":
            raise OAuthError("Accesso non autorizzato: nella pagina Atlassian hai premuto “Annulla”, o gli admin non permettono questa app.")
        raise OAuthError(f"Atlassian ha risposto {result['error']}: {result.get('error_description', '')}".strip())
    return result["code"]


@dataclass
class LoginResult:
    session: OAuthSession
    site_url: str
    site_name: str


def login(
    site: str,
    client_id: str,
    client_secret: str,
    *,
    cancel: threading.Event,
    open_browser: Callable[[str], object] | None = None,
    port: int | None = None,
    token_url: str | None = None,
    resources_url: str | None = None,
    timeout: int = 30,
) -> LoginResult:
    """Full browser login: code → tokens → which cloud id belongs to our site."""
    code = wait_for_code(client_id, cancel=cancel, open_browser=open_browser, port=port)
    tokens = exchange_code(client_id, client_secret, code, timeout=timeout, token_url=token_url)
    resource = pick_site(accessible_resources(tokens.access_token, timeout=timeout, url=resources_url), site)
    scopes = set(resource.get("scopes") or [])
    missing = [s for s in SCOPES if s != "offline_access" and scopes and s not in scopes]
    if missing:
        raise OAuthError(f"All'app mancano gli scope {', '.join(missing)}: aggiungili nella developer console e rifai il login.")
    session = OAuthSession(client_id, client_secret, tokens.refresh_token, str(resource.get("id", "")), tokens=tokens, timeout=timeout, token_url=token_url)
    return LoginResult(session, str(resource.get("url", "")).rstrip("/"), str(resource.get("name", "")))
