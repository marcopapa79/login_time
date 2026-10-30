"""Jira page of login_time: connect with an API token, list my issues, open one to read it,
comment, change status and log work. All network calls run in background jobs."""

from __future__ import annotations

import tkinter as tk
import webbrowser
from datetime import date, datetime
from tkinter import ttk
from typing import TYPE_CHECKING, Any, Callable

from . import api_log
from .config import forget_jira_token, load_jira_settings, load_jira_token, save_jira_settings
from .jira_client import JiraAuthError, JiraClient, adf_to_text, clean_text
from .jobs import JobRunner
from .theme import C, F, Tooltip, button, divider, entry, icon_button, label, pill, text_area
from .widgets import DarkMenu, Segmented, field_label

if TYPE_CHECKING:  # pragma: no cover
    from .ui import LoginWindow

TOKEN_PAGE = "https://id.atlassian.com/manage-profile/security/api-tokens"
FILTERS: list[tuple[str, str, str]] = [
    ("open", "Da fare", "assignee = currentUser() AND statusCategory != Done ORDER BY updated DESC"),
    ("recent", "Completate (30 gg)", "assignee = currentUser() AND statusCategory = Done AND updated >= -30d ORDER BY updated DESC"),
    ("reported", "Segnalate da me", "reporter = currentUser() AND statusCategory != Done ORDER BY updated DESC"),
    ("watching", "Che seguo", "watcher = currentUser() AND statusCategory != Done ORDER BY updated DESC"),
]
STATUS_KIND = {"new": "neutral", "indeterminate": "off", "done": "synced"}


def jira_date(raw: object, *, with_time: bool = True) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    for pattern in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            moment = datetime.strptime(text, pattern).astimezone()
            return moment.strftime("%d/%m/%Y %H:%M" if with_time else "%d/%m/%Y")
        except ValueError:
            continue
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
    except ValueError:
        return text


def field_name(value: object, key: str = "name") -> str:
    return str(value.get(key, "")) if isinstance(value, dict) else ""


def status_of(fields: dict[str, Any]) -> tuple[str, str]:
    status = fields.get("status") or {}
    category = (status.get("statusCategory") or {}).get("key", "")
    return str(status.get("name", "")), STATUS_KIND.get(str(category), "neutral")


class JiraPage(tk.Frame):
    def __init__(self, parent: tk.Misc, app: "LoginWindow") -> None:
        super().__init__(parent, bg=C["bg_app"], padx=24, pady=16)
        self.app = app
        self.runner = JobRunner(self)
        self.client: JiraClient | None = None
        self.me: dict[str, Any] = {}
        self.filter_var = tk.StringVar(value="open")
        self.text_var = tk.StringVar(value="")
        self.issues: list[dict[str, Any]] = []
        self.next_token: str | None = None
        self.issue_windows: dict[str, tk.Toplevel] = {}
        self.reload_pending = False
        self.scroll_canvas: tk.Canvas | None = None
        self.filter_var.trace_add("write", lambda *_: self.reload())
        self.text_var.trace_add("write", lambda *_: self.render_list())
        self.site, self.email, has_token = load_jira_settings()
        if not self.email:
            self.email = str(app.credentials.get("username", ""))
        if has_token:
            self.client = JiraClient(self.site, self.email, load_jira_token(self.site))
            self.build_main()
            self.reload()
        else:
            self.build_setup()

    # ------------------------------------------------------------------ helpers
    def clear(self) -> None:
        for child in self.winfo_children():
            child.destroy()

    def run(self, label_text: str, worker: Callable[[], Any], on_done: Callable[[Any], None], on_error: Callable[[BaseException], None]) -> bool:
        def finish(result: Any, error: BaseException | None) -> None:
            try:
                if not self.winfo_exists():
                    return
            except tk.TclError:
                return
            if error is not None:
                on_error(error)
            else:
                on_done(result)
            if self.reload_pending:
                self.reload_pending = False
                self.reload()

        return self.runner.start(label_text, lambda _emit, _cancel: worker(), on_event=lambda *_: None, on_finish=finish)

    # ------------------------------------------------------------------ setup (token)
    def build_setup(self, error_text: str = "") -> None:
        self.clear()
        self.rows = None
        self.scroll_canvas = None
        surface = C["surface"]
        card = tk.Frame(self, bg=surface, highlightthickness=1, highlightbackground=C["border"], padx=28, pady=24)
        card.pack(anchor="n", pady=(20, 0))
        tk.Label(card, text="Collega Jira", font=F["title"], bg=surface, fg=C["text"]).pack(anchor="w")
        label(
            card,
            "login_time non usa il login Microsoft + Duo: lo fai una volta nel browser per creare un token "
            "personale, che l'app salva nel Gestore credenziali di Windows.",
            kind="muted", bg=surface, wraplength=660,
        ).pack(anchor="w", pady=(6, 14))

        steps = [
            "1.  Apri la pagina dei token (fai il login normale: Microsoft → password → Duo).",
            "2.  “Create API token with scopes” → app Jira → scope: read:jira-work, write:jira-work, read:jira-user.\n"
            "     (Va bene anche “Create API token” classico.) Scadenza: fino a 365 giorni.",
            "3.  Copia il token e incollalo qui sotto.",
        ]
        for step in steps:
            tk.Label(card, text=step, font=F["body"], bg=surface, fg=C["text"], justify="left", anchor="w").pack(anchor="w", pady=2)
        button(card, "Apri la pagina dei token ↗", lambda: webbrowser.open(TOKEN_PAGE)).pack(anchor="w", pady=(8, 16))

        site_var = tk.StringVar(value=self.site)
        email_var = tk.StringVar(value=self.email)
        token_var = tk.StringVar(value="")
        fields: list[tk.Entry] = []
        for text, var, secret in (("Sito Jira", site_var, False), ("Email Atlassian", email_var, False), ("API token", token_var, True)):
            field_label(card, text, bg=surface).pack(anchor="w", pady=(0, 4))
            widget = entry(card, width=58, textvariable=var, show="•" if secret else "")
            widget.pack(fill="x", pady=(0, 10))
            fields.append(widget)
        self.token_entry = fields[-1]
        self.after(30, lambda: self.token_entry.focus_set() if self.token_entry.winfo_exists() else None)
        error_label = tk.Label(card, text=error_text, font=F["body"], bg=surface, fg=C["danger"], wraplength=660, justify="left", anchor="w")
        error_label.pack(fill="x")
        label(card, "Il token non viene mai mostrato né scritto nei log. Il login Microsoft/Duo resta solo nel browser.",
              kind="subtle", bg=surface, wraplength=660).pack(anchor="w", pady=(4, 0))
        actions = tk.Frame(card, bg=surface)
        actions.pack(fill="x", pady=(12, 0))
        connect_btn = button(actions, "Collega", None, variant="primary")
        connect_btn.pack(side="right")
        previous = self.client
        if previous is not None:
            button(actions, "Annulla", lambda: (self.build_main(), self.reload()), variant="ghost", parent_bg=surface).pack(side="right", padx=(0, 8))

        def connect() -> None:
            if self.runner.running:
                return
            site, email, token = site_var.get().strip(), email_var.get().strip(), token_var.get().strip()
            if not site or not email or not token:
                error_label.configure(text="Compila sito, email e token.")
                return
            client = JiraClient(site, email, token)
            connect_btn.configure(state="disabled", text="Verifico…")
            error_label.configure(text="")

            def worker() -> dict[str, Any]:
                api_log.event(f"=== Jira: verifica token per {email} su {client.site} ===")
                return client.myself()

            def done(me: dict[str, Any]) -> None:
                token_var.set("")
                self.site, self.email, self.client, self.me = client.site, email, client, me
                try:
                    save_jira_settings(client.site, email, token)
                    self.app._toast(f"Jira collegato come {me.get('displayName', email)}")
                except (OSError, RuntimeError) as exc:
                    self.app._toast(f"Jira collegato, ma il token non è stato salvato ({exc}): vale solo per questa sessione", "info")
                self.build_main()
                self.reload()

            def failed(exc: BaseException) -> None:
                connect_btn.configure(state="normal", text="Collega")
                error_label.configure(text=str(exc))

            self.run("verifica Jira", worker, done, failed)

        connect_btn.configure(command=connect)
        for widget in fields:
            widget.bind("<Return>", lambda _e: connect())

    # ------------------------------------------------------------------ main view
    def build_main(self) -> None:
        self.clear()
        bg = C["bg_app"]
        top = tk.Frame(self, bg=bg)
        top.pack(fill="x", pady=(0, 12))
        tk.Label(top, text="Le mie issue Jira", font=F["title"], bg=bg, fg=C["text"]).pack(side="left")
        self.me_label = tk.Label(top, text=self.site.replace("https://", ""), font=F["small"], bg=bg, fg=C["subtle"])
        self.me_label.pack(side="left", padx=(12, 0))
        more = icon_button(top, "more", None, parent_bg=bg, tooltip="Impostazioni Jira")
        more.configure(command=lambda: self.settings_menu(more))
        more.pack(side="right")
        button(top, "Apri Jira ↗", lambda: webbrowser.open(f"{self.site}/jira/for-you"), parent_bg=bg).pack(side="right", padx=(0, 8))
        icon_button(top, "refresh", self.reload, parent_bg=bg, tooltip="Aggiorna").pack(side="right", padx=(0, 8))

        bar = tk.Frame(self, bg=bg)
        bar.pack(fill="x", pady=(0, 10))
        self.filter_buttons: dict[str, tk.Button] = {}
        for key, text, _jql in FILTERS:
            btn = tk.Button(bar, text=text, font=F["body"], relief="flat", bd=0, padx=12, pady=5, cursor="hand2", highlightthickness=1,
                            command=lambda k=key: self.filter_var.set(k))
            btn.pack(side="left", padx=(0, 8))
            self.filter_buttons[key] = btn
        search_box = tk.Frame(bar, bg=C["raised"], highlightthickness=1, highlightbackground=C["border"])
        search_box.pack(side="right")
        tk.Label(search_box, text="Filtra", font=F["small"], bg=C["raised"], fg=C["subtle"]).pack(side="left", padx=(8, 0))
        tk.Entry(search_box, textvariable=self.text_var, width=28, font=F["body"], bg=C["raised"], fg=C["text"],
                 insertbackground=C["text"], relief="flat", bd=6, highlightthickness=0).pack(side="left")
        self.refresh_filter_buttons()

        host = tk.Frame(self, bg=bg)
        host.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(host, bg=bg, highlightthickness=0, yscrollincrement=20)
        self.canvas.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(host, orient="vertical", command=self.canvas.yview)
        scrollbar.pack(side="right", fill="y", padx=(8, 0))
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.rows = tk.Frame(self.canvas, bg=bg)
        window_id = self.canvas.create_window((0, 0), window=self.rows, anchor="nw")
        self.rows.bind("<Configure>", lambda _e: self.app._fit_scrollregion(self.canvas))

        def on_configure(event: tk.Event) -> None:
            self.canvas.itemconfig(window_id, width=event.width)
            self.app._fit_scrollregion(self.canvas)

        self.canvas.bind("<Configure>", on_configure)
        self.scroll_canvas = self.canvas

    def refresh_filter_buttons(self) -> None:
        current = self.filter_var.get()
        for key, btn in getattr(self, "filter_buttons", {}).items():
            if not btn.winfo_exists():
                continue
            if key == current:
                btn.configure(bg=C["accent_bg"], fg="#ffb27a", highlightbackground=C["accent"], font=F["body_bold"], activebackground=C["accent_bg"])
            else:
                btn.configure(bg=C["surface"], fg=C["text"], highlightbackground=C["border"], font=F["body"], activebackground=C["hover"])

    def settings_menu(self, anchor: tk.Widget) -> None:
        menu = DarkMenu(self.app)
        menu.add_header(self.me.get("displayName") or self.email)
        menu.add_header(self.site.replace("https://", "") + (" · gateway (token con scope)" if self.client and self.client.uses_gateway else ""), muted=True)
        menu.add_separator()
        menu.add_command("Crea / rinnova token ↗", lambda: webbrowser.open(TOKEN_PAGE))
        menu.add_command("Cambia token…", self.build_setup)
        menu.add_command("Dimentica il token Jira su questo PC", self.forget_token, danger=True)
        menu.popup_below(anchor, align_right=True)

    def forget_session(self) -> None:
        """Logout: drop the client (and the token it holds) from memory."""
        self.client = None
        for window in list(self.issue_windows.values()):
            try:
                window.client = None
                window.destroy()
            except tk.TclError:
                pass
        self.issue_windows.clear()

    def forget_token(self) -> None:
        forget_jira_token(self.site)
        self.forget_session()
        self.me = {}
        self.app._toast("Token Jira cancellato da questo PC", "info")
        self.build_setup()

    # ------------------------------------------------------------------ data
    def jql(self) -> str:
        return next(jql for key, _text, jql in FILTERS if key == self.filter_var.get())

    def reload(self, *, more: bool = False) -> None:
        if self.client is None or not self.list_ready():
            return
        self.refresh_filter_buttons()
        if self.runner.running:
            self.reload_pending = not more  # filter changed while loading: reload when done
            return
        client = self.client
        jql = self.jql()
        token = self.next_token if more else None
        if not more:
            self.show_message("Carico le issue…")

        def worker() -> tuple[dict[str, Any], list[dict[str, Any]], str | None]:
            api_log.event(f"=== Jira: issue · {jql} ===")
            me = self.me or client.myself()
            issues, next_token = client.search(jql, next_page_token=token)
            return me, issues, next_token

        def done(result: tuple[dict[str, Any], list[dict[str, Any]], str | None]) -> None:
            me, issues, next_token = result
            self.me = me
            if hasattr(self, "me_label") and self.me_label.winfo_exists():
                self.me_label.configure(text=f"{me.get('displayName', self.email)} · {self.site.replace('https://', '')}")
            self.issues = self.issues + issues if more else issues
            self.next_token = next_token
            self.render_list()

        def failed(exc: BaseException) -> None:
            if isinstance(exc, JiraAuthError):
                self.client = None
                self.build_setup(str(exc))
            else:
                self.show_message(f"Errore Jira: {exc}", error=True)

        self.run("issue Jira", worker, done, failed)

    def list_ready(self) -> bool:
        rows = getattr(self, "rows", None)
        try:
            return rows is not None and bool(rows.winfo_exists())
        except tk.TclError:
            return False

    def show_message(self, text: str, *, error: bool = False) -> None:
        if not self.list_ready():
            return
        for child in self.rows.winfo_children():
            child.destroy()
        tk.Label(self.rows, text=text, font=F["body"], bg=C["bg_app"], fg=C["danger"] if error else C["muted"], wraplength=900, justify="left").pack(pady=30)

    def render_list(self) -> None:
        if not self.list_ready():
            return
        for child in self.rows.winfo_children():
            child.destroy()
        query = self.text_var.get().strip().lower()
        shown = [
            issue for issue in self.issues
            if not query or query in (issue.get("key", "") + " " + str((issue.get("fields") or {}).get("summary", ""))).lower()
        ]
        if not shown:
            self.show_message("Nessuna issue." if not self.issues else "Nessuna issue corrisponde al filtro.")
            return
        for issue in shown:
            self.render_issue_row(issue)
        footer = tk.Frame(self.rows, bg=C["bg_app"])
        footer.pack(fill="x", pady=(6, 12))
        label(footer, f"{len(shown)} issue" + (" · altre disponibili" if self.next_token else ""), kind="subtle", bg=C["bg_app"]).pack()
        if self.next_token:
            button(footer, "Carica altre", lambda: self.reload(more=True), size="sm").pack(pady=(6, 0))

    def render_issue_row(self, issue: dict[str, Any]) -> None:
        fields = issue.get("fields") or {}
        key = str(issue.get("key", ""))
        surface = C["surface"]
        row = tk.Frame(self.rows, bg=surface, highlightthickness=1, highlightbackground=C["border"], padx=12, pady=9, cursor="hand2")
        row.pack(fill="x", pady=(0, 6))
        row.columnconfigure(1, weight=1)
        widgets: list[tk.Widget] = [row]
        key_label = tk.Label(row, text=key, font=F["ticket"], bg=surface, fg=C["text"], width=12, anchor="w")
        key_label.grid(row=0, column=0, sticky="w")
        summary = str(fields.get("summary", ""))
        summary_label = tk.Label(row, text=summary, font=F["body"], bg=surface, fg=C["text"], anchor="w", width=1)
        summary_label.grid(row=0, column=1, sticky="ew", padx=(0, 12))
        if len(summary) > 70:
            Tooltip(summary_label, summary)
        meta = " · ".join(x for x in (field_name(fields.get("issuetype")), field_name(fields.get("priority")), field_name(fields.get("project"), "key")) if x)
        meta_label = tk.Label(row, text=meta, font=F["small"], bg=surface, fg=C["subtle"])
        meta_label.grid(row=0, column=2, padx=(0, 12))
        due = jira_date(fields.get("duedate"), with_time=False)
        due_label = tk.Label(row, text=f"scade {due}" if due else "", font=F["small"], bg=surface, fg=C["warn"] if due else C["subtle"], width=16, anchor="e")
        due_label.grid(row=0, column=3, padx=(0, 12))
        status_name, kind = status_of(fields)
        pill(row, status_name or "—", kind).grid(row=0, column=4, sticky="e")
        updated = tk.Label(row, text=jira_date(fields.get("updated")), font=F["small"], bg=surface, fg=C["subtle"], width=16, anchor="e")
        updated.grid(row=0, column=5, padx=(10, 0))
        widgets += [key_label, summary_label, meta_label, due_label, updated]

        def open_issue(_e: tk.Event | None = None) -> None:
            self.open_issue(key, summary)

        def set_bg(color: str) -> None:
            for widget in widgets:
                widget.configure(bg=color)

        for widget in widgets:
            widget.bind("<Button-1>", open_issue)
        row.bind("<Enter>", lambda _e: set_bg(C["hover"]))

        def on_leave(_e: tk.Event) -> None:
            try:
                under = row.winfo_containing(*row.winfo_pointerxy())
            except (tk.TclError, KeyError):
                under = None
            if under is None or not str(under).startswith(str(row)):
                set_bg(surface)

        row.bind("<Leave>", on_leave)

    # ------------------------------------------------------------------ issue window
    def open_issue(self, key: str, summary: str = "") -> None:
        existing = self.issue_windows.get(key)
        if existing is not None and existing.winfo_exists():
            existing.deiconify()
            existing.lift()
            return
        if self.client is None:
            return
        window = JiraIssueWindow(self, key, summary)
        self.issue_windows[key] = window


class JiraIssueWindow(tk.Toplevel):
    def __init__(self, page: JiraPage, key: str, summary: str) -> None:
        super().__init__(page.app)
        self.page = page
        self.app = page.app
        self.client = page.client
        self.key = key
        self.runner = JobRunner(self)
        self.issue: dict[str, Any] = {}
        self.comments: list[dict[str, Any]] = []
        self.transitions: list[dict[str, Any]] = []
        app = self.app
        self.title(f"{key} · Jira")
        self.configure(bg=C["bg_app"])
        self.geometry(f"820x{max(min(app.winfo_height() - 60, 900), 600)}+{app.winfo_rootx() + 80}+{app.winfo_rooty() + 30}")
        self.minsize(660, 520)
        surface = C["surface"]

        header = tk.Frame(self, bg=surface, padx=16, pady=12)
        header.pack(fill="x")
        tk.Label(header, text=key, font=F["title"], bg=surface, fg=C["text"]).pack(side="left")
        self.header_summary = tk.Label(header, text=summary, font=F["body"], bg=surface, fg=C["muted"], anchor="w", width=1)
        self.header_summary.pack(side="left", fill="x", expand=True, padx=12)
        icon_button(header, "open", lambda: webbrowser.open(self.client.browse_url(key)) if self.client else None, parent_bg=surface, tooltip="Apri in Jira").pack(side="right")
        icon_button(header, "refresh", self.load, parent_bg=surface, tooltip="Aggiorna").pack(side="right")
        divider(self).pack(fill="x")

        # composer at the bottom
        composer = tk.Frame(self, bg=surface, padx=16, pady=12)
        composer.pack(side="bottom", fill="x")
        divider(self).pack(side="bottom", fill="x")
        self.mode_var = tk.StringVar(value="worklog")
        Segmented(composer, self.mode_var, [("worklog", "Registra ore"), ("comment", "Commento"), ("status", "Cambia stato")], bg=surface).pack(fill="x", pady=(0, 10))
        self.mode_host = tk.Frame(composer, bg=surface)
        self.mode_host.pack(fill="x")
        self.hint = tk.Label(composer, text="", font=F["small"], bg=surface, fg=C["subtle"], anchor="w", justify="left")
        self.hint.pack(fill="x", pady=(8, 0))
        self.text = text_area(self.mode_host, height=3, width=80)
        self.date_var = tk.StringVar(value=date.today().strftime("%d/%m/%Y"))
        self.start_var = tk.StringVar(value="09:00")
        self.hours_var = tk.StringVar(value="")
        self.mode_var.trace_add("write", lambda *_: self.build_mode())

        # scrollable content
        host = tk.Frame(self, bg=C["bg_app"])
        host.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(host, bg=C["bg_app"], highlightthickness=0, yscrollincrement=20)
        self.canvas.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(host, orient="vertical", command=self.canvas.yview)
        scrollbar.pack(side="right", fill="y")
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.body = tk.Frame(self.canvas, bg=C["bg_app"], padx=16, pady=12)
        window_id = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.body.bind("<Configure>", lambda _e: app._fit_scrollregion(self.canvas))

        def on_configure(event: tk.Event) -> None:
            self.canvas.itemconfig(window_id, width=event.width)
            app._fit_scrollregion(self.canvas)

        self.canvas.bind("<Configure>", on_configure)
        self.scroll_canvas = self.canvas  # mouse wheel (LoginWindow._scroll_rotellina)

        self.bind("<Escape>", lambda _e: self.destroy())
        self.bind("<Control-Return>", lambda _e: self.submit())
        self.build_mode()
        self.after(50, self.load)

    # ---- background helper
    def run(self, label_text: str, worker: Callable[[], Any], on_done: Callable[[Any], None]) -> None:
        def finish(result: Any, error: BaseException | None) -> None:
            if not self.winfo_exists():
                return
            if error is not None:
                api_log.event(f"    jira {self.key}: ERRORE · {error}")
                self.hint.configure(text=f"Errore: {error}", fg=C["danger"])
                self.set_busy(False)
                return
            on_done(result)

        self.runner.start(label_text, lambda _e, _c: worker(), on_event=lambda *_: None, on_finish=finish)

    def set_busy(self, busy: bool) -> None:
        if hasattr(self, "send_btn") and self.send_btn.winfo_exists():
            self.send_btn.configure(state="disabled" if busy else "normal")

    # ---- loading
    def load(self) -> None:
        if self.runner.running or self.client is None:
            return
        client, key = self.client, self.key
        self.show_message("Carico l'issue…")

        def worker() -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
            api_log.event(f"=== Jira: apro {key} ===")
            return client.issue(key), client.comments(key), client.transitions(key)

        def done(result: tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]) -> None:
            self.issue, self.comments, self.transitions = result
            summary = str((self.issue.get("fields") or {}).get("summary", ""))
            if summary:
                self.header_summary.configure(text=summary)
            self.render()
            if self.mode_var.get() == "status":
                self.build_mode()

        self.run("issue", worker, done)

    def show_message(self, text: str) -> None:
        for child in self.body.winfo_children():
            child.destroy()
        tk.Label(self.body, text=text, font=F["body"], bg=C["bg_app"], fg=C["muted"]).pack(pady=20)

    def render(self) -> None:
        for child in self.body.winfo_children():
            child.destroy()
        fields = self.issue.get("fields") or {}
        surface = C["surface"]
        width = max(self.canvas.winfo_width() - 80, 460)

        card = tk.Frame(self.body, bg=surface, highlightthickness=1, highlightbackground=C["border_strong"], padx=14, pady=12)
        card.pack(fill="x", pady=(0, 12))
        top = tk.Frame(card, bg=surface)
        top.pack(fill="x")
        tk.Label(top, text="Dettagli issue", font=F["subtitle"], bg=surface, fg=C["text"]).pack(side="left")
        status_name, kind = status_of(fields)
        if status_name:
            pill(top, status_name, kind).pack(side="left", padx=(10, 0))
        grid = tk.Frame(card, bg=surface)
        grid.pack(fill="x", pady=(10, 0))
        parent = fields.get("parent") or {}
        rows = [
            ("Tipo", field_name(fields.get("issuetype"))),
            ("Priorità", field_name(fields.get("priority"))),
            ("Progetto", " · ".join(x for x in (field_name(fields.get("project"), "key"), field_name(fields.get("project"))) if x)),
            ("Assegnata a", field_name(fields.get("assignee"), "displayName")),
            ("Segnalata da", field_name(fields.get("reporter"), "displayName")),
            ("Padre", f"{parent.get('key', '')} {field_name(parent.get('fields'), 'summary')}".strip() if parent else ""),
            ("Creata", jira_date(fields.get("created"))),
            ("Aggiornata", jira_date(fields.get("updated"))),
            ("Scadenza", jira_date(fields.get("duedate"), with_time=False)),
            ("Etichette", ", ".join(fields.get("labels") or [])),
            ("Tempo registrato", field_name(fields.get("timetracking"), "timeSpent")),
            ("Stima residua", field_name(fields.get("timetracking"), "remainingEstimate")),
        ]
        rows = [(n, v) for n, v in rows if v]
        for position, (name, value) in enumerate(rows):
            r, c = divmod(position, 2)
            tk.Label(grid, text=name, font=F["small"], bg=surface, fg=C["subtle"]).grid(row=r, column=c * 2, sticky="nw", padx=(0, 8), pady=1)
            tk.Label(grid, text=value, font=F["body"], bg=surface, fg=C["text"], anchor="w", justify="left", wraplength=max(width // 2 - 130, 180)).grid(row=r, column=c * 2 + 1, sticky="nw", padx=(0, 18), pady=1)
        grid.columnconfigure(1, weight=1)
        grid.columnconfigure(3, weight=1)
        description = clean_text(adf_to_text(fields.get("description")))
        if description:
            tk.Label(card, text="Descrizione", font=F["small"], bg=surface, fg=C["subtle"]).pack(anchor="w", pady=(10, 2))
            tk.Label(card, text=description if len(description) <= 1500 else description[:1497] + "…", font=F["body"], bg=surface, fg=C["text"], anchor="w", justify="left", wraplength=width).pack(fill="x")
            icon_button(top, "copy", lambda: self.app._copy_with_toast(description, "Descrizione copiata"), parent_bg=surface, tooltip="Copia descrizione").pack(side="right")

        tk.Label(self.body, text=f"COMMENTI · {len(self.comments)} · più recenti in alto", font=F["caption"], bg=C["bg_app"], fg=C["subtle"]).pack(anchor="w", pady=(0, 6))
        if not self.comments:
            tk.Label(self.body, text="Nessun commento.", font=F["body"], bg=C["bg_app"], fg=C["muted"]).pack(anchor="w")
        for comment in self.comments:
            box = tk.Frame(self.body, bg=surface, highlightthickness=1, highlightbackground=C["border"], padx=12, pady=10)
            box.pack(fill="x", pady=(0, 8))
            line = tk.Frame(box, bg=surface)
            line.pack(fill="x")
            tk.Label(line, text=field_name(comment.get("author"), "displayName"), font=F["body_bold"], bg=surface, fg=C["text"]).pack(side="left")
            tk.Label(line, text=jira_date(comment.get("created")), font=F["small"], bg=surface, fg=C["subtle"]).pack(side="left", padx=(10, 0))
            body = clean_text(adf_to_text(comment.get("body")))
            icon_button(line, "copy", lambda t=body: self.app._copy_with_toast(t, "Commento copiato"), parent_bg=surface, tooltip="Copia").pack(side="right")
            tk.Label(box, text=body or "—", font=F["body"], bg=surface, fg=C["text"], anchor="w", justify="left", wraplength=width).pack(fill="x", pady=(6, 0))
        self.canvas.yview_moveto(0)

    # ---- composer
    def build_mode(self) -> None:
        for child in self.mode_host.winfo_children():
            if child is not self.text:
                child.destroy()
        self.text.pack_forget()
        surface = C["surface"]
        mode = self.mode_var.get()
        if mode == "status":
            if not self.transitions:
                tk.Label(self.mode_host, text="Carico gli stati disponibili…" if self.runner.running else "Nessun cambio di stato disponibile.", font=F["body"], bg=surface, fg=C["muted"]).pack(anchor="w")
            else:
                row = tk.Frame(self.mode_host, bg=surface)
                row.pack(fill="x")
                current = status_of(self.issue.get("fields") or {})[0]
                for transition in self.transitions:
                    target = field_name(transition.get("to")) or str(transition.get("name", ""))
                    text = str(transition.get("name", target))
                    caption = f"{text} → {target}" if target and target != text else text
                    btn = button(row, caption, lambda t=transition: self.do_transition(t), size="sm")
                    if current and target == current:
                        btn.configure(text=f"{caption} · attuale", state="disabled")
                    btn.pack(side="left", padx=(0, 6), pady=2)
            self.hint.configure(text="Sposta l'issue in un altro stato (come il pulsante di stato in Jira).", fg=C["subtle"])
            return

        self.text.pack(fill="x")
        controls = tk.Frame(self.mode_host, bg=surface)
        controls.pack(fill="x", pady=(10, 0))
        if mode == "worklog":
            for text, var, width in (("Data", self.date_var, 11), ("Inizio", self.start_var, 6), ("Ore", self.hours_var, 7)):
                tk.Label(controls, text=text, font=F["body"], bg=surface, fg=C["muted"]).pack(side="left")
                entry(controls, width=width, textvariable=var).pack(side="left", padx=(6, 12))
            for preset in ("0.5h", "1h", "2h", "4h", "1d"):
                button(controls, preset, lambda p=preset: self.hours_var.set(p), size="sm").pack(side="left", padx=(0, 4))
            self.send_btn = button(controls, "Registra su Jira", self.submit, variant="primary")
            self.hint.configure(text="Worklog sull'issue Jira (descrizione facoltativa). Non tocca il portale Quixant. Ctrl+Invio per inviare.", fg=C["subtle"])
        else:
            self.send_btn = button(controls, "Aggiungi commento", self.submit, variant="primary")
            self.hint.configure(text="Commento visibile a chi vede l'issue in Jira. Ctrl+Invio per inviare.", fg=C["subtle"])
        self.send_btn.pack(side="right")

    def submit(self) -> None:
        if self.runner.running or self.client is None:
            return
        mode = self.mode_var.get()
        text = self.text.get("1.0", "end").strip()
        client, key = self.client, self.key
        if mode == "comment":
            if not text:
                self.hint.configure(text="Scrivi il commento.", fg=C["danger"])
                return
            self.set_busy(True)
            self.run("commento", lambda: client.add_comment(key, text), lambda _r: self.after_change("Commento aggiunto"))
            return
        if mode == "worklog":
            parsed = self.app._parse_working_time(self.hours_var.get())
            day = self.app._parse_user_date(self.date_var.get())
            try:
                hour, minute = (int(x) for x in self.start_var.get().strip().split(":", 1))
            except ValueError:
                hour = minute = -1
            if parsed is None:
                self.hint.configure(text="Ore non valide (es. 0.5h, 1h, 1d 4h).", fg=C["danger"])
                return
            if day is None or not (0 <= hour < 24 and 0 <= minute < 60):
                self.hint.configure(text="Controlla data (gg/mm/aaaa) e ora di inizio (hh:mm).", fg=C["danger"])
                return
            started = datetime(day.year, day.month, day.day, hour, minute)
            seconds = int(round(parsed[1] * 3600))
            self.set_busy(True)
            self.run(
                "worklog",
                lambda: client.add_worklog(key, seconds, started, text),
                lambda _r: self.after_change(f"{parsed[0]} registrate su {key}"),
            )

    def do_transition(self, transition: dict[str, Any]) -> None:
        if self.runner.running or self.client is None:
            return
        client, key = self.client, self.key
        target = field_name(transition.get("to")) or str(transition.get("name", ""))
        self.run("stato", lambda: client.transition(key, str(transition.get("id"))), lambda _r: self.after_change(f"{key} → {target}"))

    def after_change(self, message: str) -> None:
        self.text.delete("1.0", "end")
        self.hours_var.set("")
        self.set_busy(False)
        self.app._toast(message)
        self.load()
        self.page.reload()
