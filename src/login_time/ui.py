from __future__ import annotations

import json
import calendar
import os
from datetime import date, datetime, timedelta
import re
import threading
import tkinter as tk
import webbrowser
from tkinter import messagebox, ttk
from typing import Callable

from . import api_log
from .api_client import QuixantHubClient
from .config import (
    credentials_storage_label,
    get_clockify_tasks,
    get_clockify_task_id,
    load_credentials,
    load_ticket_uuid_cache,
    load_work_logs,
    save_credentials,
    save_ticket_uuid_cache,
    save_work_logs,
)
from .jobs import JobRunner
from .portal import PortalTickets, find_entry_id, html_to_text, portal_hours
from .theme import (
    C,
    F,
    FAMILY,
    Tooltip,
    apply_ttk_style,
    bind_hover,
    button,
    checkbox,
    divider,
    entry,
    icon,
    icon_button,
    init_fonts,
    label,
    pill,
    text_area,
)
from .widgets import (
    MONTHS_IT,
    ChoiceChips,
    DarkMenu,
    Modal,
    MonthPickerPopup,
    SegmentedBar,
    Segmented,
    ToastHost,
    field_label,
)

# Velocità di scorrimento della lista worklog
SCROLL_PIXEL_PER_UNITA = 20  # pixel per unità di scroll
SCROLL_UNITA_PER_SCATTO = 3  # unità per ogni scatto della rotellina (3 x 20 = 60 px)

ENTRY_TYPES = [
    ("work", "Lavoro"),
    ("off", "Extra Off"),
    ("qxsupport_synced", "QxSupport ✓"),
    ("ticket_synced", "Ticket ✓"),
]
OFF_TYPES = [
    ("Annual Leave", "Ferie"),
    ("Sick Leave", "Malattia"),
    ("Permit", "Permesso"),
    ("Other", "Altro"),
]
OFF_TYPE_LABELS = dict(OFF_TYPES)
FILTERS = [
    ("all", "Tutte"),
    ("pending", "Da sincronizzare"),
    ("synced", "Sincronizzate"),
    ("off", "Extra Off"),
]
ALREADY_SYNCED_TYPES = {"qxsupport_synced", "ticket_synced"}


class LoginWindow(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Login Time")
        self.geometry("1366x768")
        self.minsize(1200, 700)
        self.after(50, self._maximize_window)
        self.configure(bg=C["bg_app"])
        init_fonts(self)
        apply_ttk_style(self)

        self.work_logs: list[dict[str, str]] = load_work_logs()
        self.worklog_rows: tk.Frame | None = None
        self.worklog_canvas: tk.Canvas | None = None
        self.worklog_canvas_window: int | None = None
        self.credentials = load_credentials()
        self.api_client = QuixantHubClient()
        self.api_token = ""
        self.api_token_user = ""
        self.clockify_user_uuid = ""
        self.ticket_uuid_cache: dict[str, str] = load_ticket_uuid_cache()
        self.summary_var = tk.StringVar(value="")
        self.month_view_var = tk.StringVar(value="")
        self.selected_month_offset = 0

        self.toast = ToastHost(self)
        self.jobs = JobRunner(self)
        self.rows_in_flight: set[int] = set()
        self.protocol("WM_DELETE_WINDOW", self._confirm_close)
        self.filter_var = tk.StringVar(value="all")
        self.search_var = tk.StringVar(value="")
        self.expanded_tickets: dict[str, bool] = {}
        self.kpi_labels: dict[str, tuple[tk.Label, tk.Label]] = {}
        self.filter_buttons: dict[str, tk.Button] = {}
        self._render_after_id: str | None = None
        self.filter_var.trace_add("write", lambda *_: self._render_worklogs())
        self.search_var.trace_add("write", lambda *_: self._schedule_render())

        self._bootstrap_ticket_uuid_cache()
        self._build_login_ui()

    def _maximize_window(self) -> None:
        try:
            self.state("zoomed")
        except tk.TclError:
            try:
                self.attributes("-zoomed", True)
            except tk.TclError:
                pass

    def _clear_window(self) -> None:
        self.toast.hide()
        for child in self.winfo_children():
            child.destroy()

    # ------------------------------------------------------------------ feedback
    def _toast(self, message: str, kind: str = "success", **kwargs: object) -> None:
        self.toast.show(message, kind, **kwargs)

    def _notify_error(self, title: str, detail: object) -> None:
        detail_text = str(detail)
        short = detail_text if len(detail_text) <= 110 else detail_text[:107] + "…"
        self._toast(
            f"{title}: {short}",
            "error",
            action_text="Dettagli",
            action=lambda: messagebox.showerror(title, detail_text),
        )

    def _copy_with_toast(self, value: str, message: str) -> None:
        self._copy_text_direct(value)
        self._toast(message)

    # ------------------------------------------------------------------ login
    def _build_login_ui(self) -> None:
        self._clear_window()
        self.worklog_rows = None
        self.worklog_canvas = None
        self.kpi_labels = {}
        self.filter_buttons = {}
        self.unbind("<Control-n>")
        self.configure(bg=C["bg_app"])

        surface = C["surface"]
        card = tk.Frame(self, bg=surface, highlightthickness=1, highlightbackground=C["border"], padx=32, pady=30)
        card.place(relx=0.5, rely=0.45, anchor="center")

        tk.Label(card, text="QUIXANT", font=(FAMILY, 20, "bold"), fg=C["accent"], bg=surface).pack(anchor="w")
        label(card, "login_time · registra e sincronizza le ore", kind="muted", bg=surface).pack(anchor="w", pady=(4, 14))
        tk.Frame(card, bg=C["accent"], height=2, width=48).pack(anchor="w", pady=(0, 18))

        field_label(card, "Email", bg=surface).pack(anchor="w", pady=(0, 6))
        self.user_entry = entry(card, width=36)
        self.user_entry.pack(fill="x")
        self.user_entry.insert(0, self.credentials["username"])

        field_label(card, "Password", bg=surface).pack(anchor="w", pady=(14, 6))
        pw_row = tk.Frame(card, bg=C["raised"], highlightthickness=1, highlightbackground=C["border"])
        pw_row.pack(fill="x")
        self.pass_entry = tk.Entry(
            pw_row,
            show="•",
            font=(FAMILY, 11),
            bg=C["raised"],
            fg=C["text"],
            insertbackground=C["text"],
            selectbackground=C["accent"],
            selectforeground=C["on_accent"],
            relief="flat",
            bd=6,
            highlightthickness=0,
        )
        self.pass_entry.pack(side="left", fill="x", expand=True)
        self.pass_entry.insert(0, self.credentials["password"])
        self.pass_entry.bind("<FocusIn>", lambda _e: pw_row.configure(highlightbackground=C["accent"]))
        self.pass_entry.bind("<FocusOut>", lambda _e: pw_row.configure(highlightbackground=C["border"]))

        def toggle_password() -> None:
            self.pass_entry.configure(show="" if self.pass_entry.cget("show") else "•")

        icon_button(pw_row, "eye", toggle_password, parent_bg=C["raised"], tooltip="Mostra / nascondi password").pack(side="right", padx=2)

        self.remember_var = tk.BooleanVar(value=not self.credentials.get("password"))
        checkbox(card, "Ricorda le credenziali su questo PC", self.remember_var, bg=surface).pack(anchor="w", pady=(14, 0))

        self.login_error = label(card, "", bg=surface, fg=C["danger"], wraplength=340)
        self.login_error.pack(anchor="w", pady=(8, 0))

        button(card, "ACCEDI", self._handle_login, variant="primary", size="lg").pack(fill="x", pady=(10, 0))
        label(
            card,
            f"Password salvata in: {credentials_storage_label()}.\nLa connessione al portale avviene al primo sync.",
            kind="subtle",
            bg=surface,
        ).pack(anchor="w", pady=(14, 0))

        for widget in (self.user_entry, self.pass_entry):
            widget.bind("<Return>", lambda _e: self._handle_login())
        (self.pass_entry if self.user_entry.get() else self.user_entry).focus_set()

    def _handle_login(self) -> None:
        username = self.user_entry.get().strip()
        password = self.pass_entry.get().strip()

        if not username or not password:
            self.login_error.configure(text="Inserisci email e password.")
            return

        has_saved_password = bool(self.credentials.get("password"))
        matches = username == self.credentials["username"] and password == self.credentials["password"]
        remember = bool(self.remember_var.get())
        if not has_saved_password:
            # Nothing stored yet (first run): use what was typed for this session.
            if remember:
                save_credentials(username, password)
            self.credentials = {"username": username, "password": password}
            self.api_token = ""
            self.api_token_user = ""
            self._show_dashboard(username)
            return
        if not matches and not remember:
            self.login_error.configure(
                text="Credenziali diverse da quelle salvate. Spunta “Ricorda le credenziali” per aggiornarle."
            )
            return

        if not matches and remember:
            save_credentials(username, password)
            self.credentials = {"username": username, "password": password}
            self.api_token = ""
            self.api_token_user = ""

        self._show_dashboard(username)

    # ------------------------------------------------------------------ dashboard
    def _show_dashboard(self, username: str) -> None:
        self._clear_window()
        self.configure(bg=C["bg_app"])
        self.kpi_labels = {}
        self.filter_buttons = {}

        shell = tk.Frame(self, bg=C["bg_app"])
        shell.pack(fill="both", expand=True)

        self._build_topbar(shell, username)

        main = tk.Frame(shell, bg=C["bg_app"], padx=24, pady=16)
        main.pack(fill="both", expand=True)
        self._build_month_bar(main)
        self._build_kpi_panel(main)
        self._build_filter_row(main)
        self._build_worklog_list(main)

        self.bind_all("<MouseWheel>", self._scroll_rotellina)
        self.bind("<Control-n>", lambda _e: self._open_worklog_window())
        self._render_worklogs()

    def _build_topbar(self, parent: tk.Misc, username: str) -> None:
        surface = C["surface"]
        bar = tk.Frame(parent, bg=surface, padx=24, pady=10)
        bar.pack(fill="x")
        divider(parent).pack(fill="x")

        brand = tk.Frame(bar, bg=surface)
        brand.pack(side="left")
        tk.Label(brand, text="QUIXANT", font=F["brand"], fg=C["accent"], bg=surface).pack(side="left")
        label(brand, "login_time", kind="muted", bg=surface).pack(side="left", padx=(10, 0))

        name_part = username.split("@")[0] if username else "marco.papa"
        pieces = [p for p in re.split(r"[._\-]", name_part) if p]
        initials = "".join(p[0] for p in pieces[:2]).upper() or "MP"
        avatar = tk.Button(
            bar,
            text=initials,
            font=F["small_bold"],
            bg=C["accent_bg"],
            fg=C["accent_text"],
            activebackground="#4a3422",
            activeforeground=C["accent_text"],
            relief="flat",
            bd=0,
            width=4,
            pady=6,
            highlightthickness=0,
            cursor="hand2",
        )
        avatar.configure(command=lambda: self._show_profile_menu(avatar))
        avatar.pack(side="right")
        Tooltip(avatar, "Profilo e strumenti")

        button(bar, "Monthly Report ↗", self._open_monthly_report, parent_bg=surface).pack(side="right", padx=(0, 12))

        search_box = tk.Frame(bar, bg=C["raised"], highlightthickness=1, highlightbackground=C["border"])
        search_box.pack(side="right", padx=(0, 12))
        glyph, glyph_font = icon("search")
        tk.Label(search_box, text=glyph, font=glyph_font, bg=C["raised"], fg=C["muted"]).pack(side="left", padx=(8, 0))
        search_entry = tk.Entry(
            search_box,
            textvariable=self.search_var,
            width=34,
            font=F["body"],
            bg=C["raised"],
            fg=C["text"],
            insertbackground=C["text"],
            relief="flat",
            bd=6,
            highlightthickness=0,
        )
        search_entry.pack(side="left")
        placeholder = tk.Label(search_box, text="Cerca ticket, descrizione, work log…", font=F["body"], bg=C["raised"], fg=C["subtle"])

        def refresh_placeholder(*_: object) -> None:
            if self.search_var.get() or self.focus_get() is search_entry:
                placeholder.place_forget()
            else:
                placeholder.place(in_=search_entry, x=6, rely=0.5, anchor="w")

        search_entry.bind("<FocusIn>", lambda _e: (search_box.configure(highlightbackground=C["accent"]), refresh_placeholder()))
        search_entry.bind("<FocusOut>", lambda _e: (search_box.configure(highlightbackground=C["border"]), refresh_placeholder()))
        search_entry.bind("<Escape>", lambda _e: self.search_var.set(""))
        placeholder.bind("<Button-1>", lambda _e: search_entry.focus_set())
        self.search_var.trace_add("write", refresh_placeholder)
        self.after(20, refresh_placeholder)

    def _build_month_bar(self, parent: tk.Misc) -> None:
        bg = C["bg_app"]
        row = tk.Frame(parent, bg=bg)
        row.pack(fill="x", pady=(0, 16))

        picker = tk.Frame(row, bg=C["surface"], highlightthickness=1, highlightbackground=C["border"])
        picker.pack(side="left")
        icon_button(picker, "chev_left", lambda: self._shift_month(-1), parent_bg=C["surface"], tooltip="Mese precedente").pack(side="left", padx=2)
        self.month_button = tk.Button(
            picker,
            text="",
            font=F["subtitle"],
            width=15,
            bg=C["surface"],
            fg=C["text"],
            activebackground=C["hover"],
            activeforeground=C["text"],
            relief="flat",
            bd=0,
            pady=6,
            highlightthickness=0,
            cursor="hand2",
            command=self._open_month_picker,
        )
        bind_hover(self.month_button, C["surface"], C["hover"])
        self.month_button.pack(side="left")
        self.next_month_btn = icon_button(picker, "chev_right", lambda: self._shift_month(1), parent_bg=C["surface"], tooltip="Mese successivo")
        self.next_month_btn.pack(side="left", padx=2)

        self.month_tag_slot = tk.Frame(row, bg=bg)
        self.month_tag_slot.pack(side="left", padx=(12, 0))

        button(row, "+  Nuova voce", self._open_worklog_window, variant="primary").pack(side="right")
        self.sync_month_btn = button(row, "Sincronizza mese", self._sync_current_month, parent_bg=bg, bold=True)
        self.sync_month_btn.pack(side="right", padx=(0, 12))
        self.compare_btn = button(row, "Confronta col portale", self._start_portal_compare, variant="ghost", parent_bg=bg)
        self.compare_btn.pack(side="right", padx=(0, 8))
        self.status_pill = tk.Label(row, text="", font=F["small_bold"], padx=10, pady=6)
        self.status_pill.pack(side="right", padx=(0, 12))

    def _build_kpi_panel(self, parent: tk.Misc) -> None:
        surface = C["surface"]
        panel = tk.Frame(parent, bg=surface, highlightthickness=1, highlightbackground=C["border"], padx=16, pady=14)
        panel.pack(fill="x", pady=(0, 16))

        grid = tk.Frame(panel, bg=surface)
        grid.pack(fill="x")
        specs = [
            ("target", "Target", C["text"]),
            ("work", "Lavoro", C["text"]),
            ("off", "Extra Off", C["off"]),
            ("synced", "Sincronizzate", C["ok"]),
            ("pending", "Da sincronizzare", C["warn"]),
            ("missing", "Mancanti", C["accent_text"]),
        ]
        for column, (key, title, color) in enumerate(specs):
            card = tk.Frame(grid, bg=C["bg_app"], highlightthickness=1, highlightbackground=C["border"], padx=14, pady=10)
            card.grid(row=0, column=column, sticky="nsew", padx=(0 if column == 0 else 12, 0))
            grid.columnconfigure(column, weight=1, uniform="kpi")
            tk.Label(card, text=title.upper(), font=F["caption"], fg=C["muted"], bg=C["bg_app"]).pack(anchor="w")
            value = tk.Label(card, text="–", font=F["kpi"], fg=color, bg=C["bg_app"])
            value.pack(anchor="w")
            sub = tk.Label(card, text="", font=F["small"], fg=C["subtle"], bg=C["bg_app"])
            sub.pack(anchor="w")
            self.kpi_labels[key] = (value, sub)

        self.progress_bar = SegmentedBar(panel, height=10, bg=surface)
        self.progress_bar.pack(fill="x", pady=(14, 8))

        legend = tk.Frame(panel, bg=surface)
        legend.pack(fill="x")
        self.legend_labels: dict[str, tk.Label] = {}
        for key, color in (("synced", C["ok"]), ("pending", C["warn"]), ("missing", C["raised"])):
            item = tk.Frame(legend, bg=surface)
            item.pack(side="left", padx=(0, 20))
            tk.Frame(item, bg=color, width=10, height=10, highlightthickness=1 if key == "missing" else 0, highlightbackground="#4a4e59").pack(side="left", padx=(0, 6))
            text = tk.Label(item, text="", font=F["small"], fg=C["muted"], bg=surface)
            text.pack(side="left")
            self.legend_labels[key] = text
        self.progress_total_label = tk.Label(legend, text="", font=F["small"], fg=C["muted"], bg=surface)
        self.progress_total_label.pack(side="right")

    def _build_filter_row(self, parent: tk.Misc) -> None:
        bg = C["bg_app"]
        row = tk.Frame(parent, bg=bg)
        row.pack(fill="x", pady=(0, 10))
        for value, _text in FILTERS:
            btn = tk.Button(
                row,
                text="",
                font=F["body"],
                relief="flat",
                bd=0,
                padx=12,
                pady=5,
                cursor="hand2",
                highlightthickness=1,
                command=lambda v=value: self.filter_var.set(v),
            )
            btn.pack(side="left", padx=(0, 8))
            self.filter_buttons[value] = btn
        label(row, "Ctrl+N nuova voce · più recenti in alto", kind="subtle", bg=bg).pack(side="right")

    def _build_worklog_list(self, parent: tk.Misc) -> None:
        bg = C["bg_app"]
        scroll_host = tk.Frame(parent, bg=bg)
        scroll_host.pack(fill="both", expand=True)

        self.worklog_canvas = tk.Canvas(scroll_host, bg=bg, highlightthickness=0, yscrollincrement=SCROLL_PIXEL_PER_UNITA)
        self.worklog_canvas.pack(side="left", fill="both", expand=True)

        scrollbar = ttk.Scrollbar(scroll_host, orient="vertical", command=self.worklog_canvas.yview)
        scrollbar.pack(side="right", fill="y", padx=(8, 0))
        self.worklog_canvas.configure(yscrollcommand=scrollbar.set)

        self.worklog_rows = tk.Frame(self.worklog_canvas, bg=bg)
        self.worklog_canvas_window = self.worklog_canvas.create_window((0, 0), window=self.worklog_rows, anchor="nw")

        self.worklog_rows.bind(
            "<Configure>",
            lambda _event: self.worklog_canvas.configure(scrollregion=self.worklog_canvas.bbox("all")),
        )
        self.worklog_canvas.bind(
            "<Configure>",
            lambda event: self.worklog_canvas.itemconfig(self.worklog_canvas_window, width=event.width),
        )

    def _scroll_rotellina(self, event: tk.Event) -> None:
        try:
            top = event.widget.winfo_toplevel()
            # Main window scrolls the worklog list; a secondary window may expose its own scroll_canvas.
            canvas = self.worklog_canvas if top is self else getattr(top, "scroll_canvas", None)
            if canvas is None or not canvas.winfo_exists():
                return
            # Su Windows ogni "scatto" della rotellina vale delta = 120
            passi = -event.delta / 120 * SCROLL_UNITA_PER_SCATTO
            passi = int(passi) if abs(passi) >= 1 else (1 if passi > 0 else -1)
            canvas.yview_scroll(passi, "units")
        except (tk.TclError, AttributeError):
            pass

    def _show_profile_menu(self, anchor: tk.Widget) -> None:
        profile_menu = DarkMenu(self)
        profile_menu.add_header(self.credentials["username"])
        status = "connesso" if self.api_token else "non ancora connesso"
        if self.jobs.running:
            status = f"{self.jobs.label} in corso"
        profile_menu.add_header(f"Portale: {status}", muted=True)
        profile_menu.add_separator()
        profile_menu.add_command("Apri ticket per codice…", self._open_ticket_window)
        profile_menu.add_command("Importa QxSupport del mese", self._import_qxsupport_current_month, disabled=self.jobs.running)
        profile_menu.add_command("Confronta il mese col portale", self._start_portal_compare, disabled=self.jobs.running)
        profile_menu.add_separator()
        profile_menu.add_command("Apri log API (debug sync)", self._open_api_log)
        profile_menu.add_command("Advanced · API tester", self._open_api_update_window)
        profile_menu.add_separator()
        profile_menu.add_command("Esci", self._logout)
        profile_menu.popup_below(anchor, align_right=True)

    def _open_api_log(self) -> None:
        log_file = api_log.LOG_FILE
        if not log_file.exists():
            api_log.event("log creato")
        try:
            if hasattr(os, "startfile"):
                os.startfile(str(log_file))  # type: ignore[attr-defined]  # Windows: opens in the default editor
            else:
                webbrowser.open(log_file.as_uri())
        except OSError as exc:
            self._notify_error("Impossibile aprire il log", f"{log_file}\n{exc}")

    def _logout(self) -> None:
        if self.jobs.running:
            self._toast(f"Attendi la fine di {self.jobs.label} prima di uscire", "info")
            return
        self._build_login_ui()
        self._toast("Disconnesso", "info")

    # ------------------------------------------------------------------ month navigation
    def _offset_to_ym(self, offset: int) -> tuple[int, int]:
        now = datetime.now()
        index = now.year * 12 + (now.month - 1) + offset
        return index // 12, index % 12 + 1

    def _ym_to_offset(self, year: int, month: int) -> int:
        now = datetime.now()
        return (year * 12 + month - 1) - (now.year * 12 + now.month - 1)

    def _month_label_it(self, offset: int) -> str:
        year, month = self._offset_to_ym(offset)
        return f"{MONTHS_IT[month - 1]} {year}"

    def _month_label_it_from_label(self, month_label: str) -> str:
        try:
            parsed = datetime.strptime(month_label, "%B %Y")
        except ValueError:
            return month_label
        return f"{MONTHS_IT[parsed.month - 1]} {parsed.year}"

    def _shift_month(self, delta: int) -> None:
        new_offset = self.selected_month_offset + delta
        if new_offset > 0:
            return
        self._set_dashboard_month(new_offset)

    def _pending_month_keys(self) -> set[tuple[int, int]]:
        keys: set[tuple[int, int]] = set()
        for row in self.work_logs:
            if self._is_worklog_synced(row):
                continue
            try:
                parsed = datetime.strptime(str(row.get("month", "")), "%B %Y")
            except ValueError:
                continue
            keys.add((parsed.year, parsed.month))
        return keys

    def _open_month_picker(self) -> None:
        now = datetime.now()
        MonthPickerPopup(
            self,
            self.month_button,
            selected=self._offset_to_ym(self.selected_month_offset),
            latest=(now.year, now.month),
            pending_months=self._pending_month_keys(),
            on_pick=lambda year, month: self._set_dashboard_month(self._ym_to_offset(year, month)),
        )

    # ------------------------------------------------------------------ open ticket window
    def _open_ticket_window(self) -> None:
        window = Modal(self, "Apri ticket", width=520)
        body = window.body

        field_label(body, "Codice ticket").pack(anchor="w", pady=(0, 6))
        ticket_entry = entry(body, width=40)
        ticket_entry.pack(fill="x")
        ticket_entry.insert(0, "QUIX-")
        ticket_entry.focus_set()
        ticket_entry.icursor("end")

        field_label(body, "Credenziali per il login nel browser").pack(anchor="w", pady=(16, 6))
        browser_user = entry(body, width=40)
        browser_user.pack(fill="x")
        browser_user.insert(0, self.credentials["username"])
        browser_pass = entry(body, width=40, show="•")
        browser_pass.pack(fill="x", pady=(8, 0))
        browser_pass.insert(0, self.credentials["password"])
        button(
            body,
            "Copia credenziali",
            lambda: self._copy_credentials(browser_user.get().strip(), browser_pass.get().strip()),
            size="sm",
        ).pack(anchor="w", pady=(10, 0))

        button(
            window.footer,
            "Advanced · API tester",
            lambda: self._open_api_update_window(ticket_entry.get()),
            variant="ghost",
            parent_bg=C["surface"],
        ).pack(side="left")
        button(window.footer, "Apri nel browser", lambda: self._open_ticket_link(ticket_entry.get(), window), variant="primary").pack(side="right")
        button(window.footer, "Annulla", window.destroy).pack(side="right", padx=(0, 10))
        ticket_entry.bind("<Return>", lambda _e: self._open_ticket_link(ticket_entry.get(), window))
        window.recenter()

    # ------------------------------------------------------------------ new entry modal
    def _open_worklog_window(self, default_entry_type: str = "work") -> None:
        valid_types = {value for value, _ in ENTRY_TYPES}
        default_type = default_entry_type if default_entry_type in valid_types else "work"

        window = Modal(self, "Nuova voce", width=640)
        body = window.body
        surface = C["surface"]

        entry_type_var = tk.StringVar(value=default_type)
        off_type_var = tk.StringVar(value="Annual Leave")
        if self.selected_month_offset == 0:
            default_day = datetime.now().date()
        else:
            year, month = self._offset_to_ym(self.selected_month_offset)
            default_day = date(year, month, 1)
        date_var = tk.StringVar(value=default_day.strftime("%d/%m/%Y"))
        end_var = tk.StringVar(value=default_day.strftime("%d/%m/%Y"))
        hours_var = tk.StringVar(value="1h")
        description_var = tk.StringVar(value="")
        locked_ticket_var = tk.StringVar(value="")
        off_summary_var = tk.StringVar(value="")
        sync_now_var = tk.BooleanVar(value=False)

        Segmented(body, entry_type_var, ENTRY_TYPES, bg=surface).pack(fill="x", pady=(0, 16))

        sections: list[tk.Frame] = []

        def section() -> tk.Frame:
            frame = tk.Frame(body, bg=surface)
            sections.append(frame)
            return frame

        # Ticket (editable)
        ticket_edit_section = section()
        field_label(ticket_edit_section, "Ticket", required=True).pack(anchor="w", pady=(0, 6))
        ticket_titles: dict[str, str] = {}
        for row in self.work_logs:
            ticket_code = self._normalize_ticket_code(str(row.get("ticket", "")).strip()).upper()
            if ticket_code in {"", "QUIX-", "OFF", "QXSUPPORT"}:
                continue
            title = str(row.get("description", "")).strip()
            if ticket_code not in ticket_titles or (title and not ticket_titles[ticket_code]):
                ticket_titles[ticket_code] = title
        ticket_choices = [f"{code} | {ticket_titles[code] or '(senza titolo)'}" for code in sorted(ticket_titles)]
        ticket_choice_codes = {choice: choice.split(" | ", 1)[0] for choice in ticket_choices}
        ticket_entry = ttk.Combobox(ticket_edit_section, font=(FAMILY, 11), values=ticket_choices)
        ticket_entry.pack(fill="x")
        ticket_entry.insert(0, "QUIX-")

        # Ticket (locked)
        ticket_locked_section = section()
        field_label(ticket_locked_section, "Ticket").pack(anchor="w", pady=(0, 6))
        locked_box = tk.Frame(ticket_locked_section, bg=C["bg_app"], highlightthickness=1, highlightbackground=C["border_strong"], padx=10, pady=8)
        locked_box.pack(fill="x")
        lock_glyph, lock_font = icon("lock")
        tk.Label(locked_box, text=lock_glyph, font=lock_font, bg=C["bg_app"], fg=C["muted"]).pack(side="left")
        tk.Label(locked_box, textvariable=locked_ticket_var, font=F["body_bold"], bg=C["bg_app"], fg=C["text"]).pack(side="left", padx=(8, 0))
        tk.Label(locked_box, text="· impostato automaticamente", font=F["body"], bg=C["bg_app"], fg=C["muted"]).pack(side="left", padx=(6, 0))

        # Off type
        off_type_section = section()
        field_label(off_type_section, "Tipo di assenza").pack(anchor="w", pady=(0, 6))
        ChoiceChips(off_type_section, off_type_var, OFF_TYPES, bg=surface).pack(anchor="w")

        # Dates + hours
        def labelled_entry(parent: tk.Misc, text: str, var: tk.StringVar, column: int) -> tk.Entry:
            cell = tk.Frame(parent, bg=surface)
            cell.grid(row=0, column=column, sticky="ew", padx=(0 if column == 0 else 12, 0))
            parent.columnconfigure(column, weight=1, uniform="dates")
            field_label(cell, text).pack(anchor="w", pady=(0, 6))
            widget = entry(cell, width=14, textvariable=var)
            widget.pack(fill="x")
            return widget

        single_date_section = section()
        labelled_entry(single_date_section, "Data", date_var, 0)
        labelled_entry(single_date_section, "Ore", hours_var, 1)

        range_date_section = section()
        labelled_entry(range_date_section, "Dal", date_var, 0)
        labelled_entry(range_date_section, "Al", end_var, 1)
        labelled_entry(range_date_section, "Ore al giorno", hours_var, 2)

        chips_section = section()
        for preset in ("1h", "2h", "4h", "1d"):
            button(chips_section, preset, lambda p=preset: hours_var.set(p), size="sm").pack(side="left", padx=(0, 6))
        label(chips_section, "Formati: 1h · 2.5h · 1d · 1d 4h", kind="subtle", bg=surface).pack(side="left", padx=(6, 0))

        # Description
        description_section = section()
        field_label(description_section, "Descrizione ticket").pack(anchor="w", pady=(0, 6))
        entry(description_section, width=60, textvariable=description_var).pack(fill="x")

        # Comment
        comment_section = section()
        comment_label_frame = tk.Frame(comment_section, bg=surface)
        comment_label_frame.pack(anchor="w", pady=(0, 6))
        comment_title = tk.Label(comment_label_frame, text="Work log", font=F["body"], bg=surface, fg=C["muted"])
        comment_title.pack(side="left")
        tk.Label(comment_label_frame, text=" *", font=F["body"], bg=surface, fg=C["accent_text"]).pack(side="left")
        comment_text = text_area(comment_section, height=4)
        comment_text.pack(fill="x")

        # Off summary
        off_summary_section = section()
        info_box = tk.Frame(off_summary_section, bg=C["off_bg"], padx=12, pady=8)
        info_box.pack(fill="x")
        info_glyph, info_font = icon("info")
        tk.Label(info_box, text=info_glyph, font=info_font, bg=C["off_bg"], fg="#c9daff").pack(side="left")
        tk.Label(info_box, textvariable=off_summary_var, font=F["body"], bg=C["off_bg"], fg="#c9daff").pack(side="left", padx=(8, 0))

        # Error
        error_section = section()
        error_label = tk.Label(error_section, text="", font=F["body"], bg=surface, fg=C["danger"], anchor="w", justify="left", wraplength=580)
        error_label.pack(anchor="w")

        # Footer
        sync_check = checkbox(window.footer, "Sincronizza subito", sync_now_var, bg=surface)
        sync_check.pack(side="left")
        save_btn = button(window.footer, "Salva", lambda: save(), variant="primary")
        save_btn.pack(side="right")
        button(window.footer, "Annulla", window.destroy).pack(side="right", padx=(0, 10))

        def show_error(message: str) -> None:
            error_label.configure(text=message)
            layout()

        def layout() -> None:
            selected = entry_type_var.get()
            is_off = selected == "off"
            is_qx = selected == "qxsupport_synced"
            visible = [
                ticket_locked_section if (is_off or is_qx) else ticket_edit_section,
            ]
            if is_off:
                visible.append(off_type_section)
                visible.append(range_date_section)
            else:
                visible.append(single_date_section)
            visible.append(chips_section)
            if not is_off:
                visible.append(description_section)
            visible.append(comment_section)
            if is_off:
                visible.append(off_summary_section)
            if error_label.cget("text"):
                visible.append(error_section)

            for frame in sections:
                frame.pack_forget()
            for index, frame in enumerate(visible):
                pady = (0, 6) if frame is chips_section else (0, 14)
                if frame is single_date_section or frame is range_date_section:
                    pady = (0, 8)
                frame.pack(fill="x", pady=pady)

            if selected in ALREADY_SYNCED_TYPES:
                sync_check.pack_forget()
            elif not sync_check.winfo_ismapped():
                sync_check.pack(side="left")
            window.recenter()

        def prefill_description(*_: object) -> None:
            ticket_code = self._normalize_ticket_code(ticket_entry.get().strip())
            if not ticket_code or description_var.get().strip():
                return
            existing_description = self._find_ticket_description(ticket_code)
            if existing_description:
                description_var.set(existing_description)

        def select_previous_ticket(*_: object) -> None:
            ticket_code = ticket_choice_codes.get(ticket_entry.get().strip())
            if not ticket_code:
                return
            ticket_entry.delete(0, "end")
            ticket_entry.insert(0, ticket_code)
            existing_description = self._find_ticket_description(ticket_code)
            if existing_description:
                description_var.set(existing_description)

        ticket_entry.bind("<<ComboboxSelected>>", select_previous_ticket)
        ticket_entry.bind("<FocusOut>", prefill_description)

        def off_days() -> list[date] | None:
            start = self._parse_user_date(date_var.get())
            end = self._parse_user_date(end_var.get())
            if start is None or end is None or end < start:
                return None
            return self._business_days_between(start, end)

        def refresh_summary(*_: object) -> None:
            if entry_type_var.get() != "off":
                save_btn.configure(text="Salva")
                return
            days = off_days()
            parsed = self._parse_working_time(hours_var.get())
            off_label = OFF_TYPE_LABELS.get(off_type_var.get(), off_type_var.get())
            if days is None:
                off_summary_var.set("Controlla le date (gg/mm/aaaa, “Al” non prima di “Dal”).")
                save_btn.configure(text="Salva")
                return
            if not days:
                off_summary_var.set("Nessun giorno lavorativo nell'intervallo.")
                save_btn.configure(text="Salva")
                return
            total = f"{parsed[1] * len(days):g}h" if parsed else "ore non valide"
            day_word = "giorno lavorativo" if len(days) == 1 else "giorni lavorativi"
            off_summary_var.set(f"{len(days)} {day_word} · {total} · inviata come {off_label} ({off_type_var.get()})")
            save_btn.configure(text="Salva" if len(days) == 1 else f"Salva {len(days)} voci")

        def refresh_form_for_type(*_: object) -> None:
            selected_type = entry_type_var.get()
            comment_current = comment_text.get("1.0", "end").strip()
            if selected_type == "off":
                locked_ticket_var.set("OFF")
                comment_title.configure(text="Commento")
                if hours_var.get().strip().lower() in {"", "1h"}:
                    hours_var.set("8h")
                if not comment_current:
                    comment_text.insert("1.0", OFF_TYPE_LABELS.get(off_type_var.get(), "Ferie"))
            elif selected_type == "qxsupport_synced":
                locked_ticket_var.set("QXSUPPORT")
                comment_title.configure(text="Commento")
                if not description_var.get().strip():
                    description_var.set("QxSupport monthly import")
                if not comment_current:
                    comment_text.insert("1.0", "Imported manually from QxSupport web")
            else:
                comment_title.configure(text="Work log")
                current_ticket = ticket_entry.get().strip().upper()
                if current_ticket in {"", "OFF", "QUIX-", "QXSUPPORT", "SFTC-"}:
                    ticket_entry.delete(0, "end")
                    ticket_entry.insert(0, "SFTC-" if selected_type == "ticket_synced" else "QUIX-")
            error_label.configure(text="")
            refresh_summary()
            layout()

        def refresh_off_defaults(*_: object) -> None:
            if entry_type_var.get() != "off":
                return
            current = comment_text.get("1.0", "end").strip()
            if current in set(OFF_TYPE_LABELS.values()) | {"", "annual leave", "sick leave", "permit", "other"}:
                comment_text.delete("1.0", "end")
                comment_text.insert("1.0", OFF_TYPE_LABELS.get(off_type_var.get(), off_type_var.get()))
            if off_type_var.get() in {"Annual Leave", "Sick Leave"} and hours_var.get().strip().lower() in {"", "1h"}:
                hours_var.set("8h")
            refresh_summary()

        def save() -> None:
            selected_type = entry_type_var.get()
            is_off = selected_type == "off"
            comment = comment_text.get("1.0", "end").strip()

            if selected_type in {"work", "ticket_synced"}:
                ticket_value = ticket_entry.get().strip()
                ticket_value = ticket_choice_codes.get(ticket_value, ticket_value)
                ticket_code = self._normalize_ticket_code(ticket_value)
                if not ticket_code or ticket_code in {"QUIX-", "SFTC-"} or ticket_code.endswith("-"):
                    show_error("Inserisci un codice ticket valido (es. QUIX-707).")
                    return
            else:
                ticket_value = locked_ticket_var.get()
                ticket_code = ticket_value

            parsed = self._parse_working_time(hours_var.get())
            if parsed is None:
                show_error("Ore non valide. Esempi: 1h, 2.5h, 1d, 1d 4h")
                return

            if not comment:
                show_error("Il commento è obbligatorio." if is_off or selected_type == "qxsupport_synced" else "Il work log è obbligatorio.")
                return

            start = self._parse_user_date(date_var.get())
            if start is None:
                show_error("Data non valida. Usa il formato gg/mm/aaaa.")
                return

            if is_off:
                days = off_days()
                if days is None:
                    show_error("Intervallo non valido: “Al” deve essere uguale o successivo a “Dal”.")
                    return
                if not days:
                    show_error("Nessun giorno lavorativo nell'intervallo scelto.")
                    return
                if len(days) > 31:
                    show_error("Massimo 31 giorni per volta.")
                    return
            else:
                if start > datetime.now().date():
                    show_error("La data è nel futuro.")
                    return
                days = [start]

            description = description_var.get().strip()
            if is_off:
                description = off_type_var.get().lower()

            for day in days:
                saved = self._append_worklog_entry_with_status(
                    ticket_value,
                    hours_var.get(),
                    description,
                    comment,
                    entry_type=selected_type,
                    off_type=off_type_var.get() if is_off else "",
                    log_date=day,
                    render=False,
                )
                if not saved:
                    self._render_worklogs()
                    return

            target_offset = self._ym_to_offset(days[0].year, days[0].month)
            if target_offset <= 0:
                self.selected_month_offset = target_offset
            self._render_worklogs()
            window.destroy()

            count = len(days)
            if sync_now_var.get() and selected_type not in ALREADY_SYNCED_TYPES:
                if count == 1:
                    self._sync_single_worklog(0)
                else:
                    self._sync_multiple_worklogs(list(range(count)), f"{count} voci {ticket_code}")
                return

            hours_label = parsed[0]
            if count == 1:
                self._toast(f"{ticket_code} · {hours_label} salvata in locale")
            else:
                self._toast(f"{count} voci {ticket_code} salvate in locale")

        entry_type_var.trace_add("write", refresh_form_for_type)
        off_type_var.trace_add("write", refresh_off_defaults)
        for var in (date_var, end_var, hours_var):
            var.trace_add("write", refresh_summary)

        window.bind("<Control-Return>", lambda _e: save())
        refresh_form_for_type()
        refresh_off_defaults()
        if default_type in {"work", "ticket_synced"}:
            ticket_entry.focus_set()
            ticket_entry.icursor("end")
        else:
            comment_text.focus_set()

    def _parse_user_date(self, raw: str) -> date | None:
        value = raw.strip()
        if not value:
            return None
        for pattern in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d", "%d-%m-%Y", "%d.%m.%Y"):
            try:
                return datetime.strptime(value, pattern).date()
            except ValueError:
                continue
        try:
            partial = datetime.strptime(value, "%d/%m")
            return date(datetime.now().year, partial.month, partial.day)
        except ValueError:
            return None

    def _business_days_between(self, start: date, end: date) -> list[date]:
        days: list[date] = []
        holidays: dict[int, set[date]] = {}
        current = start
        while current <= end:
            if current.year not in holidays:
                holidays[current.year] = self._italian_public_holidays(current.year)
            if current.weekday() < 5 and current not in holidays[current.year]:
                days.append(current)
            current += timedelta(days=1)
        return days

    def _copy_credentials(self, username: str, password: str) -> None:
        if not username or not password:
            messagebox.showerror("Errore", "Email e password sono obbligatorie.")
            return

        self.clipboard_clear()
        self.clipboard_append(f"{username}\n{password}")
        self._toast("Credenziali copiate (prima email, poi password)")

    def _open_ticket_link(self, ticket_value: str, window: tk.Toplevel) -> None:
        ticket = ticket_value.strip().upper()
        if not ticket:
            messagebox.showerror("Errore", "Inserisci un codice ticket.", parent=window)
            return

        ticket = self._normalize_ticket_code(ticket)

        if ticket == "QUIX-":
            messagebox.showerror("Errore", "Inserisci un codice ticket valido.", parent=window)
            return

        url = f"https://support.quixant.com/ticket/Edit/{ticket}"
        webbrowser.open(url)
        window.destroy()

    def _save_worklog(
        self,
        ticket: str,
        hours: str,
        description: str,
        comment: str,
        entry_type: str,
        off_type: str,
        window: tk.Toplevel,
    ) -> None:
        saved = self._append_worklog_entry(
            ticket,
            hours,
            description,
            comment,
            entry_type=entry_type,
            off_type=off_type,
        )
        if not saved:
            return

        window.destroy()
        self._toast("Voce salvata in locale")

    def _append_worklog_entry(
        self,
        ticket: str,
        hours: str,
        description: str,
        comment: str,
        *,
        entry_type: str = "work",
        off_type: str = "",
    ) -> bool:
        return self._append_worklog_entry_with_status(
            ticket,
            hours,
            description,
            comment,
            entry_type=entry_type,
            off_type=off_type,
        )

    def _append_worklog_entry_with_status(
        self,
        ticket: str,
        hours: str,
        description: str,
        comment: str,
        *,
        api_synced: bool = False,
        api_synced_at: str = "",
        api_ticket_uuid: str = "",
        api_month_displacement: str = "",
        entry_type: str = "work",
        off_type: str = "",
        log_date: date | None = None,
        render: bool = True,
        extra_fields: dict[str, str] | None = None,
    ) -> bool:
        normalized_type = "off" if str(entry_type).strip().lower() == "off" else "work"
        if str(entry_type).strip().lower() == "qxsupport_synced":
            normalized_type = "qxsupport_synced"
        elif str(entry_type).strip().lower() == "ticket_synced":
            normalized_type = "ticket_synced"
        if normalized_type == "off":
            ticket_code = "OFF"
        elif normalized_type == "qxsupport_synced":
            ticket_code = "QXSUPPORT"
        else:
            ticket_code = self._normalize_ticket_code(ticket)
            if not ticket_code:
                messagebox.showerror("Error", "Ticket is required.")
                return False
            if ticket_code == "QUIX-":
                messagebox.showerror("Error", "Insert a valid ticket code.")
                return False

        parsed = self._parse_working_time(hours)
        if parsed is None:
            messagebox.showerror(
                "Error",
                "Working time non valido. Esempi: 1h, 2.5h, 1d, 1d 4h",
            )
            return False
        working_time_label, _hours_value = parsed

        if not comment:
            messagebox.showerror("Error", "Comment is required.")
            return False

        if normalized_type == "off":
            ticket_description = description.strip() or "annual leave"
            normalized_off_type = off_type.strip() or "Annual Leave"
        elif normalized_type == "qxsupport_synced":
            ticket_description = description.strip() or "QxSupport monthly import"
            normalized_off_type = ""
        else:
            ticket_description = description.strip() or self._find_ticket_description(ticket_code)
            normalized_off_type = ""

        force_synced = normalized_type in {"qxsupport_synced", "ticket_synced"}
        synced_at_value = api_synced_at
        if force_synced and not synced_at_value:
            synced_at_value = datetime.now().astimezone().isoformat(timespec="seconds")

        entry_day = log_date or datetime.now().date()
        month_label = datetime(entry_day.year, entry_day.month, 1).strftime("%B %Y")

        item = {
            "working_time": working_time_label,
            "month": month_label,
            "work_log": comment,
            "ticket": ticket_code,
            "comment": comment,
            "description": ticket_description,
            "entry_type": normalized_type,
            "off_type": normalized_off_type,
            "log_date": entry_day.isoformat(),
            "api_synced": "true" if api_synced or force_synced else "",
            "api_synced_at": synced_at_value,
            "api_ticket_uuid": api_ticket_uuid,
            "api_month_displacement": api_month_displacement if api_month_displacement else self._month_displacement_for_label(month_label),
        }
        if extra_fields:
            item.update(extra_fields)
        self.work_logs.insert(0, item)
        save_work_logs(self.work_logs)
        if render:
            self._render_worklogs()
        return True

    def _parse_working_time(self, raw: str) -> tuple[str, float] | None:
        value = raw.strip().lower().replace(",", ".")
        if not value:
            return None

        # Allow simple numeric input, interpreted as hours.
        if re.fullmatch(r"\d+(?:\.\d+)?", value):
            hours = float(value)
            if hours <= 0:
                return None
            if hours.is_integer():
                return (f"{int(hours)}h", hours)
            return (f"{hours:g}h", hours)

        # Allow formats like: 1h, 2.5h, 1d, 1d 4h
        match = re.fullmatch(r"(?:\s*(\d+(?:\.\d+)?)d)?\s*(?:\s*(\d+(?:\.\d+)?)h)?", value)
        if not match:
            return None

        day_part = match.group(1)
        hour_part = match.group(2)
        if day_part is None and hour_part is None:
            return None

        days = float(day_part) if day_part is not None else 0.0
        hours_only = float(hour_part) if hour_part is not None else 0.0

        total_hours = (days * 8.0) + hours_only
        if total_hours <= 0:
            return None

        pieces: list[str] = []
        if days:
            pieces.append(f"{days:g}d")
        if hours_only:
            pieces.append(f"{hours_only:g}h")

        return (" ".join(pieces), total_hours)

    # ------------------------------------------------------------------ worklog list
    def _schedule_render(self) -> None:
        if self._render_after_id is not None:
            try:
                self.after_cancel(self._render_after_id)
            except tk.TclError:
                pass
        self._render_after_id = self.after(200, self._render_worklogs)

    def _row_matches_filter(self, row: dict[str, str]) -> bool:
        current = self.filter_var.get()
        if current == "pending":
            return not self._is_worklog_synced(row)
        if current == "synced":
            return self._is_worklog_synced(row)
        if current == "off":
            return self._is_off_entry(row)
        return True

    def _row_matches_search(self, row: dict[str, str]) -> bool:
        query = self.search_var.get().strip().casefold()
        if not query:
            return True
        haystack = " ".join(
            str(row.get(key, "")) for key in ("ticket", "description", "work_log", "comment", "off_type")
        ).casefold()
        return all(part in haystack for part in query.split())

    def _format_hours(self, hours_value: float) -> str:
        return f"{hours_value:g}h"

    def _format_row_date(self, row: dict[str, str]) -> str:
        raw = str(row.get("log_date", "")).strip()
        try:
            return datetime.strptime(raw, "%Y-%m-%d").strftime("%d/%m")
        except ValueError:
            return "—"

    def _short_sync_stamp(self, row: dict[str, str]) -> str:
        synced_at = str(row.get("api_synced_at", "")).strip()
        if not synced_at:
            return ""
        try:
            parsed = datetime.fromisoformat(synced_at)
            if parsed.tzinfo is not None:
                parsed = parsed.astimezone()
            return parsed.strftime("%d/%m %H:%M")
        except ValueError:
            return synced_at.replace("T", " ")[:16]

    def _update_filter_buttons(self, counts: dict[str, int]) -> None:
        current = self.filter_var.get()
        for value, text in FILTERS:
            btn = self.filter_buttons.get(value)
            if btn is None or not btn.winfo_exists():
                continue
            btn.configure(text=f"{text}   {counts.get(value, 0)}")
            if value == current:
                btn.configure(bg=C["accent_bg"], fg="#ffb27a", highlightbackground=C["accent"], activebackground=C["accent_bg"], activeforeground="#ffb27a", font=F["body_bold"])
            else:
                btn.configure(bg=C["surface"], fg=C["text"], highlightbackground=C["border"], activebackground=C["hover"], activeforeground=C["text"], font=F["body"])

    def _render_worklogs(self) -> None:
        self._render_after_id = None
        if self.worklog_rows is None or not self.worklog_rows.winfo_exists():
            return

        summary = self._refresh_summary()
        month_label_it = self._month_label_it(self.selected_month_offset)

        canvas = self.worklog_canvas
        scroll_position = canvas.yview()[0] if canvas is not None else 0.0

        for child in self.worklog_rows.winfo_children():
            child.destroy()

        month_rows: list[dict[str, str]] = summary["rows"]
        counts = {
            "all": len(month_rows),
            "pending": sum(1 for row in month_rows if not self._is_worklog_synced(row)),
            "synced": sum(1 for row in month_rows if self._is_worklog_synced(row)),
            "off": sum(1 for row in month_rows if self._is_off_entry(row)),
        }
        self._update_filter_buttons(counts)

        if not month_rows:
            empty = tk.Frame(self.worklog_rows, bg=C["bg_app"])
            empty.pack(fill="x", pady=48)
            tk.Label(empty, text=f"Nessuna voce per {month_label_it}", font=F["subtitle"], fg=C["text"], bg=C["bg_app"]).pack()
            label(empty, "Registra le ore lavorate, le ferie o importa quelle già presenti sul portale.", kind="muted", bg=C["bg_app"]).pack(pady=(6, 14))
            button(empty, "+  Nuova voce", self._open_worklog_window, variant="primary").pack()
            return

        filtered = [row for row in month_rows if self._row_matches_filter(row) and self._row_matches_search(row)]
        if not filtered:
            empty = tk.Frame(self.worklog_rows, bg=C["bg_app"])
            empty.pack(fill="x", pady=40)
            label(empty, "Nessuna voce corrisponde ai filtri attivi.", kind="muted", bg=C["bg_app"]).pack()

            def reset_filters() -> None:
                self.search_var.set("")
                self.filter_var.set("all")

            button(empty, "Azzera filtri", reset_filters, size="sm").pack(pady=(10, 0))
            return

        grouped = self._group_worklogs_by_ticket(filtered)

        def latest_date(item: tuple[str, dict[str, object]]) -> str:
            entries = item[1]["entries"]
            assert isinstance(entries, list)
            return max((str(e["row"].get("log_date", "")) for e in entries), default="")

        def has_pending(item: tuple[str, dict[str, object]]) -> bool:
            entries = item[1]["entries"]
            assert isinstance(entries, list)
            return any(not self._is_worklog_synced(e["row"]) for e in entries)

        # Tickets with pending rows first, then most recent activity first.
        ordered = sorted(grouped.items(), key=latest_date, reverse=True)
        ordered.sort(key=lambda item: 0 if has_pending(item) else 1)
        for ticket, bundle in ordered:
            self._render_ticket_card(ticket, bundle)

        if len(filtered) == len(month_rows):
            footer_text = f"{len(month_rows)} righe in {month_label_it} · tutte visibili"
        else:
            footer_text = f"{len(filtered)} di {len(month_rows)} righe in {month_label_it} · filtri attivi"
        label(self.worklog_rows, footer_text, kind="subtle", bg=C["bg_app"]).pack(pady=(4, 16))

        if canvas is not None:
            self.update_idletasks()
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.yview_moveto(scroll_position)

    def _toggle_ticket(self, ticket: str, expanded: bool) -> None:
        self.expanded_tickets[ticket] = expanded
        self._render_worklogs()

    def _configure_row_grid(self, frame: tk.Frame) -> None:
        # Every row is its own grid: minsizes larger than any content keep columns aligned.
        frame.columnconfigure(0, minsize=100)
        frame.columnconfigure(1, minsize=72)
        frame.columnconfigure(2, weight=1)
        frame.columnconfigure(3, minsize=230)
        frame.columnconfigure(4, minsize=250)

    def _render_ticket_card(self, ticket: str, bundle: dict[str, object]) -> None:
        surface = C["surface"]
        entries = bundle["entries"]
        assert isinstance(entries, list)
        entries = sorted(entries, key=lambda e: str(e["row"].get("log_date", "")), reverse=True)
        pending_count = sum(1 for e in entries if not self._is_worklog_synced(e["row"]))
        total_hours = sum(self._hours_from_worklog_row(e["row"]) for e in entries)
        is_off = ticket == "OFF"
        is_qx = ticket == "QXSUPPORT"
        searching = bool(self.search_var.get().strip())
        expanded = True if searching else self.expanded_tickets.get(ticket, pending_count > 0)

        card = tk.Frame(self.worklog_rows, bg=surface, highlightthickness=1, highlightbackground=C["border"])
        card.pack(fill="x", pady=(0, 10))

        head = tk.Frame(card, bg=surface, padx=8, pady=8)
        head.pack(fill="x")
        head.columnconfigure(2, weight=1)

        toggle = lambda t=ticket, e=expanded: self._toggle_ticket(t, not e)  # noqa: E731
        icon_button(
            head,
            "chev_down" if expanded else "chev_right",
            toggle,
            parent_bg=surface,
            tooltip="Comprimi" if expanded else "Espandi",
        ).grid(row=0, column=0)
        code_label = tk.Label(head, text=ticket, font=F["ticket"], fg=C["text"], bg=surface, cursor="hand2")
        code_label.grid(row=0, column=1, padx=(4, 12), sticky="w")
        code_label.bind("<Button-1>", lambda _e: toggle())

        description = str(bundle["description"] or "")
        if is_off:
            description = "Extra Off · Ferie / Malattia / Permessi"
        description = description or "Nessuna descrizione"
        desc_label = tk.Label(head, text=description, font=F["body"], fg=C["muted"], bg=surface, anchor="w", width=1)
        desc_label.grid(row=0, column=2, sticky="ew")
        if len(description) > 60:
            Tooltip(desc_label, description)

        row_word = "riga" if len(entries) == 1 else "righe"
        label(head, f"{len(entries)} {row_word}", kind="subtle", bg=surface).grid(row=0, column=3, padx=12)
        tk.Label(head, text=self._format_hours(total_hours), font=F["subtitle"], fg=C["text"], bg=surface).grid(row=0, column=4, padx=(0, 12))
        if pending_count:
            pill(head, f"{pending_count} da sincronizzare", "pending").grid(row=0, column=5)
            sync_btn = button(
                head,
                "Sincronizza",
                lambda t=ticket: self._sync_ticket_worklogs(t),
                variant="outline",
                size="sm",
                parent_bg=surface,
                bold=True,
            )
            if self.jobs.running:
                sync_btn.configure(state="disabled", highlightbackground=C["border"])
            sync_btn.grid(row=0, column=6, padx=(12, 0))
        else:
            pill(head, "Tutte sincronizzate", "synced").grid(row=0, column=5)
        if not is_off and not is_qx:
            icon_button(
                head, "chat", lambda t=ticket, d=description: self._open_ticket_conversation(t, d), parent_bg=surface, tooltip="Conversazione · nota interna con ore"
            ).grid(row=0, column=7, padx=(8, 0))
            icon_button(head, "open", lambda t=ticket: self._open_ticket_for_row(t), parent_bg=surface, tooltip="Apri ticket nel portale").grid(row=0, column=8, padx=(2, 0))
        more_btn = icon_button(head, "more", None, parent_bg=surface, tooltip="Altre azioni")
        more_btn.configure(command=lambda b=more_btn, t=ticket, d=description, p=pending_count, o=is_off or is_qx: self._show_ticket_menu(b, t, d, p, o))
        more_btn.grid(row=0, column=9, padx=(2, 0))

        if not expanded:
            return

        divider(card).pack(fill="x")
        header = tk.Frame(card, bg=surface, padx=12, pady=6)
        header.pack(fill="x")
        self._configure_row_grid(header)
        for column, text in enumerate(("DATA", "ORE", "WORK LOG", "STATO", "AZIONI")):
            tk.Label(header, text=text, font=F["caption"], fg=C["subtle"], bg=surface).grid(
                row=0, column=column, sticky="e" if column == 4 else "w", padx=(32 if column == 0 else 0, 0)
            )

        for entry_item in entries:
            self._render_worklog_row(card, entry_item)

    def _render_worklog_row(self, card: tk.Frame, entry_item: dict[str, object]) -> None:
        row = entry_item["row"]
        assert isinstance(row, dict)
        index = entry_item["index"]
        assert isinstance(index, int)
        synced = self._is_worklog_synced(row)
        normal_bg = C["surface"] if synced else C["pending_row"]

        tk.Frame(card, bg=C["raised"], height=1).pack(fill="x")
        line = tk.Frame(card, bg=normal_bg, padx=12, pady=4)
        line.pack(fill="x")
        self._configure_row_grid(line)
        current_bg = lambda: line.cget("bg")  # noqa: E731

        recolor: list[tk.Widget] = [line]
        date_label = label(line, self._format_row_date(row), kind="muted", bg=normal_bg)
        date_label.grid(row=0, column=0, sticky="w", padx=(32, 0))
        hours_label = tk.Label(line, text=str(row.get("working_time", "")), font=F["body_bold"], fg=C["text"], bg=normal_bg)
        hours_label.grid(row=0, column=1, sticky="w")

        work_log = str(entry_item["work_log"] or "")
        if self._is_off_entry(row):
            off_label = OFF_TYPE_LABELS.get(str(row.get("off_type", "")), str(row.get("off_type", "")) or "Extra Off")
            work_log = off_label if not work_log or work_log.lower() == off_label.lower() else f"{off_label} · {work_log}"
        shown = work_log if len(work_log) <= 200 else work_log[:197] + "…"
        log_label = tk.Label(line, text=shown or "—", font=F["body"], fg=C["text"], bg=normal_bg, anchor="w", width=1)
        log_label.grid(row=0, column=2, sticky="ew", padx=(0, 12))
        if len(work_log) > 70:
            Tooltip(log_label, work_log)

        status = tk.Frame(line, bg=normal_bg)
        status.grid(row=0, column=3, sticky="w")
        in_flight = id(row) in self.rows_in_flight
        pending_update = not synced and row.get("api_pending_action") == "update"
        if in_flight:
            pill(status, "Invio in corso…", "neutral").pack(side="left")
        elif pending_update:
            update_pill = pill(status, "Da aggiornare", "pending")
            update_pill.pack(side="left")
            Tooltip(update_pill, "Modificata dopo l'invio: al prossimo sync viene aggiornata la voce già presente sul portale.")
        else:
            pill(status, "Sincronizzata" if synced else "Da sincronizzare", "synced" if synced else "pending").pack(side="left")
        if not synced and str(row.get("api_resend_of", "")).strip() and not in_flight:
            resend_mark = label(status, "rimandata", kind="subtle", bg=normal_bg)
            resend_mark.pack(side="left", padx=(8, 0))
            Tooltip(resend_mark, "Era già sul portale ed è stata modificata: prima di inviarla cancella la voce vecchia dal web.")
            recolor.append(resend_mark)
        recolor += [date_label, hours_label, log_label, status]
        if synced:
            stamp = label(status, self._short_sync_stamp(row), kind="subtle", bg=normal_bg)
            stamp.pack(side="left", padx=(8, 0))
            recolor.append(stamp)

        actions = tk.Frame(line, bg=normal_bg)
        actions.grid(row=0, column=4, sticky="e")
        recolor.append(actions)
        if not synced:
            send_btn = button(actions, "Invia", lambda i=index: self._sync_single_worklog(i), variant="link", size="sm", parent_bg=normal_bg, bold=True)
            if self.jobs.running:
                send_btn.configure(state="disabled")
            send_btn.pack(side="left", padx=(0, 4))
            recolor.append(send_btn)
        copy_btn = icon_button(
            actions,
            "copy",
            lambda text=str(entry_item["work_log"]): self._copy_with_toast(text, "Work log copiato"),
            parent_bg=normal_bg,
            tooltip="Copia work log",
            base_bg=current_bg,
        )
        copy_btn.pack(side="left")
        edit_btn = icon_button(actions, "edit", lambda i=index: self._open_edit_log_window(i), parent_bg=normal_bg, tooltip="Modifica riga", base_bg=current_bg)
        edit_btn.pack(side="left")
        more_btn = icon_button(actions, "more", None, parent_bg=normal_bg, tooltip="Altre azioni", base_bg=current_bg)
        more_btn.configure(command=lambda b=more_btn, i=index, r=row, s=synced, w=str(entry_item["work_log"]): self._show_row_menu(b, i, r, s, w))
        more_btn.pack(side="left")
        recolor += [copy_btn, edit_btn, more_btn]

        def set_bg(color: str) -> None:
            for widget in recolor:
                try:
                    widget.configure(bg=color)
                    if isinstance(widget, tk.Button):
                        widget.configure(activebackground=C["border_strong"])
                except tk.TclError:
                    pass

        def on_enter(_e: tk.Event) -> None:
            set_bg(C["hover"])

        def on_leave(_e: tk.Event) -> None:
            try:
                under = line.winfo_containing(*line.winfo_pointerxy())
            except (tk.TclError, KeyError):
                under = None
            if under is not None and str(under).startswith(str(line)):
                return
            set_bg(normal_bg)

        line.bind("<Enter>", on_enter, add="+")
        line.bind("<Leave>", on_leave, add="+")

    def _show_ticket_menu(self, anchor: tk.Widget, ticket: str, description: str, pending_count: int, is_special: bool) -> None:
        ticket_menu = DarkMenu(self)
        if not is_special:
            ticket_menu.add_command("Apri ticket nel portale", lambda: self._open_ticket_for_row(ticket))
        if not is_special:
            ticket_menu.add_command("Conversazione e nota con ore…", lambda: self._open_ticket_conversation(ticket, description))
        ticket_menu.add_command("Copia codice ticket", lambda: self._copy_with_toast(ticket, f"{ticket} copiato"))
        ticket_menu.add_command("Copia descrizione", lambda: self._copy_with_toast(description, "Descrizione copiata"))
        ticket_menu.add_command("Modifica descrizione…", lambda: self._open_edit_description_window(ticket))
        if not is_special:
            ticket_menu.add_command(
                "Ricalcola UUID dal portale",
                lambda: self._forget_ticket_uuid(ticket),
                disabled=self.jobs.running,
            )
        if pending_count:
            ticket_menu.add_separator()
            ticket_menu.add_command(
                f"Sincronizza {pending_count} {'riga' if pending_count == 1 else 'righe'}",
                lambda: self._sync_ticket_worklogs(ticket),
                disabled=self.jobs.running,
            )
        ticket_menu.popup_below(anchor, align_right=True)

    def _show_row_menu(self, anchor: tk.Widget, index: int, row: dict[str, str], synced: bool, work_log: str) -> None:
        in_flight = id(row) in self.rows_in_flight
        row_menu = DarkMenu(self)
        row_menu.add_command("Copia ore", lambda: self._copy_with_toast(str(row.get("working_time", "")), "Ore copiate"))
        row_menu.add_command("Copia work log", lambda: self._copy_with_toast(work_log, "Work log copiato"))
        row_menu.add_command("Modifica riga…", lambda: self._open_edit_log_window(index), disabled=in_flight)
        if not synced:
            send_label = "Aggiorna sul portale" if row.get("api_pending_action") == "update" else "Invia al portale"
            row_menu.add_command(send_label, lambda: self._sync_single_worklog(index), disabled=self.jobs.running)
        if row.get("api_pending_action") == "update":
            row_menu.add_command("Invia come nuova voce (non aggiornare)", lambda: self._send_as_new_entry(row), disabled=in_flight)
        row_menu.add_separator()
        row_menu.add_command("Rimuovi riga…", lambda: self._remove_worklog(index), danger=True, disabled=in_flight)
        row_menu.popup_below(anchor, align_right=True)

    # ------------------------------------------------------------------ ticket conversation panel
    def _open_ticket_conversation(self, ticket: str, description: str = "") -> None:
        """Non-modal window: ticket posts (ticket_posts/list) + composer for an internal note or a reply with hours."""
        ticket_code = self._normalize_ticket_code(ticket)
        panels: dict[str, tk.Toplevel] = self.__dict__.get("_ticket_panels", {})
        self._ticket_panels = panels
        existing = panels.get(ticket_code)
        if existing is not None and existing.winfo_exists():
            existing.deiconify()
            existing.lift()
            existing.focus_force()
            return

        surface = C["surface"]
        window = tk.Toplevel(self)
        panels[ticket_code] = window
        window.title(f"{ticket_code} · conversazione")
        window.configure(bg=C["bg_app"])
        window.geometry(f"780x{max(min(self.winfo_height() - 60, 900), 600)}+{self.winfo_rootx() + 60}+{self.winfo_rooty() + 30}")
        window.minsize(640, 520)
        runner = JobRunner(window)
        state: dict[str, object] = {"page": 1, "posts": [], "ticket_uuid": "", "more": False}

        # header
        header = tk.Frame(window, bg=surface, padx=16, pady=12)
        header.pack(fill="x")
        tk.Label(header, text=ticket_code, font=F["title"], bg=surface, fg=C["text"]).pack(side="left")
        if description:
            desc = tk.Label(header, text=description, font=F["body"], bg=surface, fg=C["muted"], anchor="w", width=1)
            desc.pack(side="left", fill="x", expand=True, padx=(12, 12))
        else:
            tk.Frame(header, bg=surface).pack(side="left", fill="x", expand=True)
        icon_button(header, "open", lambda: self._open_ticket_for_row(ticket_code), parent_bg=surface, tooltip="Apri nel portale").pack(side="right")
        icon_button(header, "refresh", lambda: load(1), parent_bg=surface, tooltip="Aggiorna").pack(side="right")
        divider(window).pack(fill="x")

        # composer (packed at the bottom first so the list takes the remaining space)
        composer = tk.Frame(window, bg=surface, padx=16, pady=12)
        composer.pack(side="bottom", fill="x")
        divider(window).pack(side="bottom", fill="x")

        kind_var = tk.StringVar(value="internal")
        Segmented(composer, kind_var, [("internal", "Nota interna"), ("public", "Risposta al cliente")], bg=surface).pack(fill="x", pady=(0, 10))
        message_text = text_area(composer, height=5, width=80)
        message_text.pack(fill="x")
        controls = tk.Frame(composer, bg=surface)
        controls.pack(fill="x", pady=(10, 0))
        tk.Label(controls, text="Ore", font=F["body"], bg=surface, fg=C["muted"]).pack(side="left")
        hours_var = tk.StringVar(value="")
        entry(controls, width=8, textvariable=hours_var).pack(side="left", padx=(8, 6))
        for preset in ("0.5h", "1h", "2h", "4h"):
            button(controls, preset, lambda p=preset: hours_var.set(p), size="sm").pack(side="left", padx=(0, 4))
        register_var = tk.BooleanVar(value=True)
        checkbox(controls, "Registra le ore anche qui", register_var, bg=surface).pack(side="left", padx=(10, 0))
        send_btn = button(controls, "Invia nota interna", lambda: send(), variant="primary")
        send_btn.pack(side="right")
        composer_hint = tk.Label(composer, text="", font=F["small"], bg=surface, fg=C["subtle"], anchor="w", justify="left")
        composer_hint.pack(fill="x", pady=(8, 0))

        def refresh_kind(*_: object) -> None:
            if kind_var.get() == "public":
                send_btn.configure(text="Invia al cliente…")
                composer_hint.configure(text="La risposta viene inviata al cliente per email. Ti chiederò conferma prima dell'invio.", fg=C["warn"])
            else:
                send_btn.configure(text="Invia nota interna")
                composer_hint.configure(text="Nota visibile solo internamente (chi segue il ticket riceve la notifica). Ctrl+Invio per inviare.", fg=C["subtle"])

        kind_var.trace_add("write", refresh_kind)
        refresh_kind()

        # posts list
        list_host = tk.Frame(window, bg=C["bg_app"])
        list_host.pack(fill="both", expand=True)
        canvas = tk.Canvas(list_host, bg=C["bg_app"], highlightthickness=0, yscrollincrement=SCROLL_PIXEL_PER_UNITA)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(list_host, orient="vertical", command=canvas.yview)
        scrollbar.pack(side="right", fill="y")
        canvas.configure(yscrollcommand=scrollbar.set)
        posts_frame = tk.Frame(canvas, bg=C["bg_app"], padx=16, pady=12)
        posts_window = canvas.create_window((0, 0), window=posts_frame, anchor="nw")
        posts_frame.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(posts_window, width=e.width))
        window.scroll_canvas = canvas  # type: ignore[attr-defined]  # used by _scroll_rotellina

        local_entry_ids = {str(r.get("api_entry_id", "")).upper() for r in self.work_logs if r.get("api_entry_id")}
        local_post_ids = {str(r.get("api_post_uuid", "")).upper() for r in self.work_logs if r.get("api_post_uuid")}

        def format_date(raw: str) -> str:
            try:
                return datetime.fromisoformat(raw).strftime("%d/%m/%Y %H:%M")
            except ValueError:
                return raw.replace("T", " ")[:16]

        def render_posts() -> None:
            for child in posts_frame.winfo_children():
                child.destroy()
            posts = state["posts"]
            assert isinstance(posts, list)
            if not posts:
                tk.Label(posts_frame, text="Nessun messaggio sul ticket.", font=F["body"], bg=C["bg_app"], fg=C["muted"]).pack(pady=20)
            width = max(canvas.winfo_width() - 80, 420)
            for post in posts:
                is_log = int(post.get("id_ticket_post") or 0) == -1
                is_public = bool(post.get("public")) and not is_log
                card_bg = C["surface"] if is_public else "#1d1f24"
                card = tk.Frame(posts_frame, bg=card_bg, highlightthickness=1, highlightbackground=C["border"], padx=12, pady=10)
                card.pack(fill="x", pady=(0, 8))
                top = tk.Frame(card, bg=card_bg)
                top.pack(fill="x")
                tk.Label(top, text=str(post.get("fullname") or post.get("username") or ""), font=F["body_bold"], bg=card_bg, fg=C["text"]).pack(side="left")
                tk.Label(top, text=format_date(str(post.get("post_date", ""))), font=F["small"], bg=card_bg, fg=C["subtle"]).pack(side="left", padx=(10, 0))
                if is_log:
                    pill(top, "Ore registrate", "off").pack(side="left", padx=(10, 0))
                elif is_public:
                    pill(top, "Pubblico", "neutral").pack(side="left", padx=(10, 0))
                else:
                    pill(top, "Interno", "pending").pack(side="left", padx=(10, 0))
                spent = str(post.get("time_spent") or "").strip()
                if spent:
                    pill(top, spent, "synced").pack(side="left", padx=(6, 0))
                post_uuid = str(post.get("uuid", "")).upper()
                if post_uuid and (post_uuid in local_entry_ids or post_uuid in local_post_ids):
                    tk.Label(top, text="dall'app", font=F["small"], bg=card_bg, fg=C["subtle"]).pack(side="left", padx=(8, 0))
                attachments = post.get("appAttachments") or []
                if attachments:
                    tk.Label(top, text=f"{len(attachments)} allegati (apri dal portale)", font=F["small"], bg=card_bg, fg=C["subtle"]).pack(side="left", padx=(8, 0))
                text = html_to_text(str(post.get("text") or ""))
                icon_button(top, "copy", lambda t=text: self._copy_with_toast(t, "Testo copiato"), parent_bg=card_bg, tooltip="Copia testo").pack(side="right")
                tk.Label(card, text=text or "—", font=F["body"], bg=card_bg, fg=C["text"], anchor="w", justify="left", wraplength=width).pack(fill="x", pady=(6, 0))
            if state["more"]:
                button(posts_frame, "Carica messaggi più vecchi", lambda: load(int(state["page"]) + 1), size="sm").pack(pady=(4, 8))

        def show_status(message: str, *, error: bool = False) -> None:
            for child in posts_frame.winfo_children():
                child.destroy()
            tk.Label(posts_frame, text=message, font=F["body"], bg=C["bg_app"], fg=C["danger"] if error else C["muted"], wraplength=640, justify="left").pack(pady=20, anchor="w")

        def ensure_ticket_uuid(token: str) -> str:
            ticket_uuid = str(state["ticket_uuid"])
            if not ticket_uuid:
                ticket_uuid = self._resolve_ticket_uuid_cached(token, ticket_code)
                state["ticket_uuid"] = ticket_uuid
            return ticket_uuid

        def load(page: int) -> None:
            if runner.running:
                return
            if page == 1:
                cached = ticket_code in self.ticket_uuid_cache or state["ticket_uuid"]
                show_status("Carico i messaggi…" if cached else "Cerco il ticket sul portale (la prima volta può richiedere qualche secondo)…")

            def worker(_emit: object, _cancel: object) -> list[dict[str, object]]:
                api_log.event(f"=== Lettura messaggi {ticket_code} · pagina {page} ===")
                token = self._ensure_api_session()
                return self.portal.list_posts(token, ensure_ticket_uuid(token), page)

            def on_finish(result: object, error: BaseException | None) -> None:
                if not window.winfo_exists():
                    return
                if error is not None:
                    show_status(f"Impossibile leggere i messaggi: {error}", error=True)
                    return
                assert isinstance(result, list)
                posts = state["posts"]
                assert isinstance(posts, list)
                state["posts"] = result if page == 1 else posts + result
                state["page"] = page
                state["more"] = len(result) >= 10
                render_posts()
                if page == 1:
                    canvas.yview_moveto(0)

            runner.start("lettura messaggi", worker, on_event=lambda *_: None, on_finish=on_finish)

        def send() -> None:
            if runner.running:
                return
            text = message_text.get("1.0", "end").strip()
            if not text:
                composer_hint.configure(text="Scrivi il testo del messaggio.", fg=C["danger"])
                return
            hours_raw = hours_var.get().strip()
            parsed = self._parse_working_time(hours_raw) if hours_raw else None
            if hours_raw and parsed is None:
                composer_hint.configure(text="Ore non valide. Esempi: 0.5h, 1h, 1d 4h", fg=C["danger"])
                return
            public = kind_var.get() == "public"
            if public:
                preview = text if len(text) <= 400 else text[:397] + "…"
                hours_line = f"\nOre registrate: {parsed[0]}" if parsed else ""
                if not messagebox.askyesno(
                    "Risposta al cliente",
                    f"Il messaggio verrà inviato al cliente di {ticket_code} per email:\n\n{preview}{hours_line}\n\nInviare?",
                    icon="warning",
                    parent=window,
                ):
                    return
            send_btn.configure(state="disabled")
            composer_hint.configure(text="Invio in corso…", fg=C["muted"])
            time_spent = parsed[0] if parsed else ""

            def worker(_emit: object, _cancel: object) -> tuple[dict[str, object], str]:
                kind = "risposta al cliente" if public else "nota interna"
                api_log.event(f"=== {kind.capitalize()} su {ticket_code}" + (f" · {time_spent}" if time_spent else "") + " ===")
                token = self._ensure_api_session()
                ticket_uuid = ensure_ticket_uuid(token)
                result = self.portal.create_post(token, ticket_uuid, text, public=public, time_spent=time_spent)
                api_log.event(f"    ESITO: OK · messaggio {result.get('new_post_uuid') or result.get('post_uuid')}")
                return result, ticket_uuid

            def on_finish(result: object, error: BaseException | None) -> None:
                if not window.winfo_exists():
                    return
                send_btn.configure(state="normal")
                if error is not None:
                    api_log.event(f"    ESITO: ERRORE · {error}")
                    composer_hint.configure(text=f"Invio non riuscito: {error}", fg=C["danger"])
                    return
                assert isinstance(result, tuple)
                created, ticket_uuid = result
                post_uuid = str(created.get("post_uuid") or created.get("new_post_uuid") or "").upper()
                message_text.delete("1.0", "end")
                hours_var.set("")
                refresh_kind()
                if parsed and register_var.get():
                    local_post_ids.add(post_uuid)
                    self._append_worklog_entry_with_status(
                        ticket_code,
                        parsed[0],
                        description or self._find_ticket_description(ticket_code),
                        text[:1000],
                        api_synced=True,
                        api_synced_at=datetime.now().astimezone().isoformat(timespec="seconds"),
                        api_ticket_uuid=ticket_uuid,
                        extra_fields={"api_post_uuid": post_uuid},
                    )
                kind = "Risposta inviata al cliente" if public else "Nota interna inviata"
                self._toast(f"{kind} su {ticket_code}" + (f" · {parsed[0]} registrate" if parsed else ""))
                load(1)

            runner.start("invio messaggio", worker, on_event=lambda *_: None, on_finish=on_finish)

        window.bind("<Control-Return>", lambda _e: send())
        window.bind("<Escape>", lambda _e: window.destroy())
        window.after(50, lambda: load(1))
        message_text.focus_set()

    # ------------------------------------------------------------------ compare month with the portal
    def _start_portal_compare(self) -> None:
        if self.jobs.running:
            self._toast(f"Attendi: {self.jobs.label} in corso", "info")
            return
        month_label = self._get_summary_month()
        month_it = self._month_label_it(self.selected_month_offset)
        month_rows = [row for row in self.work_logs if str(row.get("month", "")) == month_label]
        tickets = sorted({str(row.get("ticket", "")) for row in month_rows if str(row.get("ticket", "")) not in {"OFF", "QXSUPPORT", ""}})
        if not tickets:
            self._toast(f"Nessun ticket da confrontare in {month_it}", "info")
            return
        username = self.credentials["username"].strip().lower()
        total = len(tickets)

        def worker(emit: Callable[[str, object], None], cancel: threading.Event) -> dict[str, object]:
            api_log.event(f"=== Confronto con il portale · {month_label} · {total} ticket ===")
            token = self._ensure_api_session()
            results: list[dict[str, object]] = []
            links: list[tuple[dict[str, str], str]] = []
            claimed = self._claimed_entry_ids()
            fullname = ""
            extra_times_hours: float | None = None
            for position, ticket in enumerate(tickets):
                if cancel.is_set():
                    break
                emit("current", (position, ticket))
                local_rows = [row for row in month_rows if row.get("ticket") == ticket]
                local_total = sum(self._hours_from_worklog_row(row) for row in local_rows)
                local_synced = sum(self._hours_from_worklog_row(row) for row in local_rows if self._is_worklog_synced(row))
                item: dict[str, object] = {"ticket": ticket, "local_total": local_total, "local_synced": local_synced}
                try:
                    ticket_uuid = self._resolve_ticket_uuid_cached(token, ticket)
                    entries = self.portal.list_working_hours(token, ticket_uuid)
                    mine = [
                        e for e in entries
                        if str(e.get("Username", "")).lower() == username and str(e.get("Month", "")).lower() == month_label.lower()
                    ]
                    if mine and not fullname:
                        fullname = str(mine[0].get("FullName", ""))
                    entry_hours = sum(portal_hours(e.get("WorkingTime")) or 0.0 for e in mine)

                    # Link local synced rows to their portal entry (Id) when it is missing.
                    for row in local_rows:
                        if row.get("api_entry_id") or self._portal_entry_kind(row) != "entry" or not self._is_worklog_synced(row):
                            continue
                        hours, reason = self._portal_values_of(row)
                        entry_id = find_entry_id(mine, username=username, month_label=month_label, hours=hours, reason=reason, exclude_ids=claimed)
                        if entry_id:
                            claimed.add(entry_id.upper())
                            links.append((row, entry_id.upper()))
                    linked_ids = claimed | {eid for _r, eid in links}
                    unlinked = [e for e in mine if str(e.get("Id", "")).upper() not in linked_ids]

                    times = self.portal.get_times(token, ticket_uuid)
                    total_hours: float | None = None
                    for wt in times.get("working_times") or []:
                        if str(wt.get("Month", "")).lower() == month_label.lower() and (not fullname or str(wt.get("FullName", "")) == fullname):
                            total_hours = (total_hours or 0.0) + (portal_hours(wt.get("WorkingTime")) or 0.0)
                    if extra_times_hours is None and fullname:
                        for et in times.get("extra_times") or []:
                            if str(et.get("Month", "")).lower() == month_label.lower() and str(et.get("FullName", "")) == fullname:
                                extra_times_hours = (extra_times_hours or 0.0) + (portal_hours(et.get("WorkingTime")) or 0.0)
                    portal_total = total_hours if total_hours is not None else entry_hours
                    item.update(
                        portal_total=portal_total,
                        entry_hours=entry_hours,
                        posts_hours=max(portal_total - entry_hours, 0.0),
                        unlinked=[
                            f"{e.get('WorkingTime', '')} · {str(e.get('Reason', ''))[:60]}" for e in unlinked
                        ],
                    )
                    api_log.event(
                        f"    {ticket}: qui {local_synced:g}h sincronizzate su {local_total:g}h · portale {portal_total:g}h "
                        f"({len(mine)} voci, {len(unlinked)} non collegate)"
                    )
                except Exception as exc:  # noqa: BLE001 - one failing ticket must not stop the comparison
                    item["error"] = str(exc)
                    api_log.event(f"    {ticket}: ERRORE · {exc}")
                results.append(item)
            return {"results": results, "links": links, "extra_times": extra_times_hours, "cancelled": cancel.is_set()}

        def on_cancel() -> None:
            self.jobs.cancel()
            self.toast.progress_cancel_requested()

        def on_event(kind: str, payload: object) -> None:
            if kind == "current":
                position, ticket = payload  # type: ignore[misc]
                self.toast.progress(f"Confronto {ticket} · {position + 1} di {total}…", position, total, on_cancel=on_cancel)

        def on_finish(result: object, error: BaseException | None) -> None:
            self.toast.hide_progress()
            if error is not None:
                self._notify_error("Confronto non riuscito", error)
                return
            assert isinstance(result, dict)
            links = result["links"]
            assert isinstance(links, list)
            for row, entry_id in links:
                if any(item is row for item in self.work_logs) and not row.get("api_entry_id"):
                    row["api_entry_id"] = entry_id
            if links:
                save_work_logs(self.work_logs)
            self._render_worklogs()
            self._show_compare_results(month_it, result)

        self.jobs.start(f"confronto {month_it}", worker, on_event=on_event, on_finish=on_finish)
        self.toast.progress(f"Confronto {month_it} con il portale…", 0, total, on_cancel=on_cancel)

    def _show_compare_results(self, month_it: str, result: dict[str, object]) -> None:
        results = result["results"]
        assert isinstance(results, list)
        links = result["links"]
        assert isinstance(links, list)
        window = Modal(self, f"Confronto con il portale · {month_it}", width=760)
        body = window.body
        surface = C["surface"]

        grid = tk.Frame(body, bg=surface)
        grid.pack(fill="x")
        for column, (text, width) in enumerate((("TICKET", 14), ("QUI (SINCR.)", 12), ("PORTALE", 10), ("STATO", 46))):
            tk.Label(grid, text=text, font=F["caption"], bg=surface, fg=C["subtle"], width=width, anchor="w").grid(row=0, column=column, sticky="w", pady=(0, 6))

        problems = 0
        for row_index, item in enumerate(results, start=1):
            ticket = str(item["ticket"])
            local_total = float(item["local_total"])  # type: ignore[arg-type]
            local_synced = float(item["local_synced"])  # type: ignore[arg-type]
            if "error" in item:
                status, kind = f"Errore: {str(item['error'])[:80]}", "danger"
                portal_text = "—"
            else:
                portal_total = float(item["portal_total"])  # type: ignore[arg-type]
                portal_text = f"{portal_total:g}h"
                unlinked = item.get("unlinked") or []
                if abs(portal_total - local_synced) < 1e-6:
                    if local_total > local_synced:
                        status, kind = f"Allineato · {local_total - local_synced:g}h ancora da inviare", "pending"
                    else:
                        status, kind = "Allineato", "synced"
                elif portal_total > local_synced:
                    status, kind = f"Sul portale {portal_total - local_synced:g}h in più (duplicati o voci dal web?)", "danger"
                else:
                    status, kind = f"Sul portale mancano {local_synced - portal_total:g}h", "danger"
                posts_hours = float(item.get("posts_hours") or 0.0)  # type: ignore[arg-type]
                if posts_hours and kind != "synced":
                    status += f" · {posts_hours:g}h da messaggi"
                if unlinked and kind == "danger":
                    status += f" · voci non collegate: {'; '.join(str(u) for u in unlinked[:3])}"
            if kind == "danger":
                problems += 1
            tk.Label(grid, text=ticket, font=F["body_bold"], bg=surface, fg=C["text"], anchor="w").grid(row=row_index, column=0, sticky="w", pady=3)
            tk.Label(grid, text=f"{local_synced:g}h", font=F["body"], bg=surface, fg=C["text"], anchor="w").grid(row=row_index, column=1, sticky="w")
            tk.Label(grid, text=portal_text, font=F["body"], bg=surface, fg=C["text"], anchor="w").grid(row=row_index, column=2, sticky="w")
            status_label = pill(grid, status if len(status) <= 70 else status[:67] + "…", kind)
            status_label.grid(row=row_index, column=3, sticky="w")
            if len(status) > 70:
                Tooltip(status_label, status)

        extra = result.get("extra_times")
        off_local = sum(
            self._hours_from_worklog_row(row)
            for row in self.work_logs
            if self._is_off_entry(row) and str(row.get("month", "")) == self._get_summary_month()
        )
        summary = [
            f"{len(results) - problems} ticket allineati, {problems} con differenze."
            if problems
            else f"Tutti i {len(results)} ticket sono allineati col portale."
        ]
        if links:
            summary.append(f"Collegate {len(links)} righe alla loro voce sul portale: ora si possono aggiornare o cancellare da qui.")
        if isinstance(extra, float):
            summary.append(f"Extra Off: qui {off_local:g}h · sul portale {extra:g}h (dato get_times, da verificare nel Monthly Report).")
        if result.get("cancelled"):
            summary.append("Confronto interrotto: alcuni ticket non sono stati controllati.")
        tk.Label(body, text="\n".join(summary), font=F["body"], bg=surface, fg=C["muted"], justify="left", anchor="w", wraplength=700).pack(fill="x", pady=(14, 0))

        button(window.footer, "Apri log API", self._open_api_log, variant="ghost", parent_bg=surface).pack(side="left")
        button(window.footer, "Chiudi", window.destroy, variant="primary").pack(side="right")
        window.recenter()

    def _open_ticket_for_row(self, ticket: str) -> None:
        ticket_code = self._normalize_ticket_code(ticket)
        webbrowser.open(f"https://support.quixant.com/ticket/Edit/{ticket_code}")

    def _open_monthly_report(self) -> None:
        webbrowser.open("https://support.quixant.com/admin/MonthlyReport")

    def _open_api_update_window(self, ticket_value: str = "") -> None:
        window = tk.Toplevel(self)
        window.title("Quixant API - Ticket Update")
        window.geometry("840x680")
        window.configure(bg="#2b2b30")
        window.transient(self)
        window.grab_set()

        tk.Label(
            window,
            text="Prova API Quixant Hub",
            font=("Segoe UI", 16, "bold"),
            fg="#f4f4f6",
            bg="#2b2b30",
        ).pack(anchor="w", padx=20, pady=(16, 8))

        tk.Label(
            window,
            text="La finestra prova a fare il login API in automatico con le credenziali salvate. Se fallisce, clicca Login API o controlla username/password.",
            font=("Segoe UI", 9),
            fg="#bcbcc7",
            bg="#2b2b30",
            wraplength=780,
            justify="left",
        ).pack(anchor="w", padx=20, pady=(0, 10))

        tk.Label(
            window,
            text="Login API: invia solo username e password a /api/login. Le richieste successive usano l'access token come Bearer.",
            font=("Segoe UI", 9, "bold"),
            fg="#f4f4f6",
            bg="#2b2b30",
            wraplength=780,
            justify="left",
        ).pack(anchor="w", padx=20, pady=(0, 8))

        status_var = tk.StringVar(value="API not connected")
        tk.Label(
            window,
            textvariable=status_var,
            font=("Segoe UI", 10),
            fg="#bcbcc7",
            bg="#2b2b30",
        ).pack(anchor="w", padx=20)

        resolved_ticket_var = tk.StringVar(value="Resolved Ticket UUID: not resolved yet")
        tk.Label(
            window,
            textvariable=resolved_ticket_var,
            font=("Segoe UI", 9),
            fg="#bcbcc7",
            bg="#2b2b30",
        ).pack(anchor="w", padx=20, pady=(4, 0))

        form = tk.Frame(window, bg="#2b2b30")
        form.pack(fill="x", padx=20, pady=(16, 0))

        tk.Label(form, text="Username", font=("Segoe UI", 11), fg="#f4f4f6", bg="#2b2b30").grid(row=0, column=0, sticky="w")
        username_entry = tk.Entry(form, width=34, font=("Segoe UI", 11))
        username_entry.grid(row=1, column=0, sticky="w", padx=(0, 12), pady=(6, 12))
        username_entry.insert(0, self.credentials["username"])

        tk.Label(form, text="Password", font=("Segoe UI", 11), fg="#f4f4f6", bg="#2b2b30").grid(row=0, column=1, sticky="w")
        password_entry = tk.Entry(form, width=34, font=("Segoe UI", 11), show="*")
        password_entry.grid(row=1, column=1, sticky="w", padx=(0, 12), pady=(6, 12))
        password_entry.insert(0, self.credentials["password"])

        tk.Label(form, text="Ticket", font=("Segoe UI", 11), fg="#f4f4f6", bg="#2b2b30").grid(row=2, column=0, sticky="w")
        ticket_entry = tk.Entry(form, width=34, font=("Segoe UI", 11))
        ticket_entry.grid(row=3, column=0, sticky="w", padx=(0, 12), pady=(6, 12))
        ticket_entry.insert(0, ticket_value or "QUIX-")

        tk.Label(form, text="Endpoint", font=("Segoe UI", 11), fg="#f4f4f6", bg="#2b2b30").grid(row=2, column=1, sticky="w")
        endpoint_var = tk.StringVar(value="/api/working_hours/form")
        endpoint_choices = {
            "Log working hours": "/api/working_hours/form",
            "Add extra off / leave": "/api/extrahours/add",
            "Clockify tasks": "/api/extrahours/clockify_tasks",
            "Clockify users": "/api/extrahours/clockify_users",
            "Remove extra hours": "/api/extrahours/remove",
            "Update ticket fields": "/api/tickets/update",
            "Save ticket status comments": "/api/tickets/status_comments",
            "Custom endpoint": "/api/tickets/update",
        }
        endpoint_combo = ttk.Combobox(
            form,
            state="readonly",
            values=list(endpoint_choices.keys()),
            font=("Segoe UI", 10),
            width=31,
        )
        endpoint_combo.set("Log working hours")
        endpoint_combo.grid(row=3, column=1, sticky="w", padx=(0, 12), pady=(6, 12))

        tk.Label(form, text="Working time", font=("Segoe UI", 11), fg="#f4f4f6", bg="#2b2b30").grid(row=4, column=0, sticky="w")
        working_time_entry = tk.Entry(form, width=34, font=("Segoe UI", 11))
        working_time_entry.grid(row=5, column=0, sticky="w", padx=(0, 12), pady=(6, 12))
        working_time_entry.insert(0, "1h")

        tk.Label(form, text="Local comment", font=("Segoe UI", 11), fg="#f4f4f6", bg="#2b2b30").grid(row=4, column=1, sticky="w")
        local_comment_entry = tk.Entry(form, width=34, font=("Segoe UI", 11))
        local_comment_entry.grid(row=5, column=1, sticky="w", padx=(0, 12), pady=(6, 12))
        local_comment_entry.insert(0, "API test comment")

        tk.Label(form, text="Month displacement", font=("Segoe UI", 11), fg="#f4f4f6", bg="#2b2b30").grid(row=7, column=0, sticky="w")
        month_displacement_entry = tk.Entry(form, width=34, font=("Segoe UI", 11))
        month_displacement_entry.grid(row=8, column=0, sticky="w", padx=(0, 12), pady=(6, 12))
        month_displacement_entry.insert(0, "0")

        save_local_var = tk.BooleanVar(value=True)
        tk.Checkbutton(
            form,
            text="Save in local worklog too",
            variable=save_local_var,
            font=("Segoe UI", 10),
            fg="#f4f4f6",
            bg="#2b2b30",
            activebackground="#2b2b30",
            activeforeground="#f4f4f6",
            selectcolor="#2b2b30",
        ).grid(row=6, column=0, columnspan=2, sticky="w", pady=(0, 8))

        payload_label = tk.Label(window, text="Payload JSON", font=("Segoe UI", 11), fg="#f4f4f6", bg="#2b2b30")
        payload_label.pack(anchor="w", padx=20, pady=(8, 6))
        payload_text = tk.Text(window, width=92, height=12, font=("Consolas", 10), wrap="none")
        payload_text.pack(fill="x", padx=20)

        response_label = tk.Label(window, text="Response", font=("Segoe UI", 11), fg="#f4f4f6", bg="#2b2b30")
        response_label.pack(anchor="w", padx=20, pady=(14, 6))
        response_text = tk.Text(window, width=92, height=12, font=("Consolas", 10), wrap="word")
        response_text.pack(fill="both", expand=True, padx=20, pady=(0, 8))

        def set_payload_template(*_: object) -> None:
            endpoint_path = endpoint_choices.get(endpoint_combo.get(), "/api/working_hours/form")
            endpoint_var.set(endpoint_path)
            ticket_code = self._normalize_ticket_code(ticket_entry.get().strip()) or "QUIX-XXXX"
            working_time_value = working_time_entry.get().strip() or "1h"
            comment_value = local_comment_entry.get().strip() or "API test comment"
            if endpoint_path == "/api/tickets/status_comments":
                template = {
                    "ticketGuid": ticket_code,
                    "comment": "API test comment",
                }
            elif endpoint_path == "/api/working_hours/form":
                template = {
                    "TicketId": ticket_code,
                    "Username": username_entry.get().strip(),
                    "MonthDisplacement": month_displacement_entry.get().strip() or "0",
                    "Reason": comment_value,
                    "WorkingTime": working_time_value,
                }
            elif endpoint_path == "/api/extrahours/add":
                parsed_hours = self._parse_working_time(working_time_value)
                hours_value = parsed_hours[1] if parsed_hours is not None else 8
                decimal_hours = self._format_decimal_hours(hours_value)
                payload_hours: int | float = int(decimal_hours) if float(decimal_hours).is_integer() else decimal_hours
                task_id = get_clockify_task_id("Annual Leave")
                today = datetime.now().date().isoformat()
                date_variants = self._extra_hours_date_variants(today)
                # Same verified shape used by the dashboard sync (see docs/extra-off-api.md).
                # An empty uuid is replaced with a fresh GUID from /api/tickets/newguid on send.
                template = {
                    "uuid": "",
                    "id_clockify_task": task_id,
                    "hours": payload_hours,
                    "log_date_start": date_variants["it_date"],
                    "log_date_end": date_variants["it_date"],
                    "description": comment_value,
                }
            elif endpoint_path in {"/api/extrahours/clockify_tasks", "/api/extrahours/clockify_users"}:
                template = {}
            elif endpoint_path == "/api/extrahours/remove":
                template = {
                    "Id": "",
                }
            else:
                template = {
                    "ticket": ticket_code,
                    "ticketGuid": ticket_code,
                    "ticketCode": ticket_code,
                    "description": "API test update",
                }
            payload_text.delete("1.0", "end")
            payload_text.insert("1.0", json.dumps(template, indent=2, ensure_ascii=False))

        def write_response(value: object) -> None:
            response_text.delete("1.0", "end")
            if isinstance(value, str):
                response_text.insert("1.0", value)
                return
            response_text.insert("1.0", json.dumps(value, indent=2, ensure_ascii=False))

        def login_api() -> None:
            username = username_entry.get().strip()
            password = password_entry.get().strip()
            if not username or not password:
                messagebox.showerror("Error", "Username and password are required.")
                return

            response_text.delete("1.0", "end")
            response_text.insert(
                "1.0",
                json.dumps({"username": username, "password": "***"}, indent=2, ensure_ascii=False),
            )

            try:
                token, payload = self.api_client.login(username, password)
            except Exception as exc:  # noqa: BLE001 - show the exact API/login failure to the user
                status_var.set("API login failed")
                messagebox.showerror("API login failed", str(exc))
                return

            self.api_token = token
            self.api_token_user = username
            status_var.set(f"API connected as {username}")
            write_response(payload)
            return True

        def auto_connect() -> None:
            if self.api_token and self.api_token_user == username_entry.get().strip():
                return
            login_api()

        def send_request() -> None:
            if not self.api_token:
                login_api()
                if not self.api_token:
                    return

            endpoint_path = endpoint_var.get().strip()
            if not endpoint_path.startswith("/"):
                messagebox.showerror("Error", "Select a valid endpoint.")
                return

            raw_payload = payload_text.get("1.0", "end").strip()
            payload: dict[str, object] | None = None
            if raw_payload:
                try:
                    parsed_payload = json.loads(raw_payload)
                except json.JSONDecodeError as exc:
                    messagebox.showerror("Error", f"Payload JSON non valido: {exc}")
                    return
                if not isinstance(parsed_payload, dict):
                    messagebox.showerror("Error", "Payload JSON must be an object.")
                    return
                payload = parsed_payload

            resolved_uuid = ""
            month_displacement = ""
            if endpoint_path == "/api/working_hours/form" and payload is not None:
                ticket_reference = str(payload.get("TicketId", "")).strip() or ticket_entry.get().strip()
                try:
                    resolved_uuid = self._resolve_ticket_uuid_cached(self.api_token, ticket_reference)
                except Exception as exc:  # noqa: BLE001 - expose ticket resolution issues directly
                    status_var.set("Ticket UUID resolution failed")
                    messagebox.showerror("Ticket resolution failed", str(exc))
                    return

                payload["TicketId"] = resolved_uuid
                month_displacement = str(payload.get("MonthDisplacement", month_displacement_entry.get().strip() or "0"))
                resolved_ticket_var.set(f"Resolved Ticket UUID: {resolved_uuid}")
                payload_text.delete("1.0", "end")
                payload_text.insert("1.0", json.dumps(payload, indent=2, ensure_ascii=False))

            if endpoint_path == "/api/extrahours/add" and payload is not None and not str(payload.get("uuid", "")).strip():
                try:
                    payload["uuid"] = self._request_extra_hours_guid(self.api_token)
                except Exception as exc:  # noqa: BLE001 - without a GUID the entry would not show in Monthly Report
                    status_var.set("GUID request failed")
                    messagebox.showerror("GUID request failed", str(exc))
                    return
                payload_text.delete("1.0", "end")
                payload_text.insert("1.0", json.dumps(payload, indent=2, ensure_ascii=False))

            method = "POST"
            if endpoint_path in {"/api/extrahours/clockify_tasks", "/api/extrahours/clockify_users"}:
                method = "GET"

            try:
                if method == "GET":
                    response = self.api_client.request_query(endpoint_path, self.api_token, payload)
                else:
                    response = self.api_client.request_json("POST", endpoint_path, self.api_token, payload)
            except Exception as exc:  # noqa: BLE001 - surface the API error returned by the service
                status_var.set("API request failed")
                messagebox.showerror("API request failed", str(exc))
                return

            status_var.set(f"Request sent to {endpoint_path}")
            write_response(response.payload)
            if save_local_var.get():
                if endpoint_path in {"/api/extrahours/clockify_tasks", "/api/extrahours/clockify_users"}:
                    messagebox.showinfo("Success", "API request completed.")
                    return
                if endpoint_path == "/api/working_hours/form":
                    saved = self._append_worklog_entry_with_status(
                        ticket_entry.get().strip(),
                        working_time_entry.get().strip(),
                        local_comment_entry.get().strip() or self._find_ticket_description(ticket_entry.get().strip()),
                        local_comment_entry.get().strip(),
                        api_synced=True,
                        api_synced_at=datetime.now().isoformat(timespec="seconds"),
                        api_ticket_uuid=resolved_uuid,
                        api_month_displacement=month_displacement,
                    )
                elif endpoint_path == "/api/extrahours/add":
                    off_type = "Annual Leave"
                    if payload is not None:
                        task_names = {task_id: name for name, task_id in get_clockify_tasks().items()}
                        off_type = str(
                            payload.get("Type")
                            or payload.get("type")
                            or task_names.get(str(payload.get("id_clockify_task", "")))
                            or off_type
                        )
                    saved = self._append_worklog_entry_with_status(
                        "OFF",
                        working_time_entry.get().strip(),
                        local_comment_entry.get().strip() or "annual leave",
                        local_comment_entry.get().strip() or "annual leave",
                        api_synced=True,
                        api_synced_at=datetime.now().isoformat(timespec="seconds"),
                        entry_type="off",
                        off_type=off_type,
                    )
                else:
                    saved = self._append_worklog_entry(
                        ticket_entry.get().strip(),
                        working_time_entry.get().strip(),
                        local_comment_entry.get().strip() or self._find_ticket_description(ticket_entry.get().strip()),
                        local_comment_entry.get().strip(),
                    )
                if saved:
                    messagebox.showinfo("Success", "API request completed and local worklog saved.")
                else:
                    return
            else:
                messagebox.showinfo("Success", "API request completed.")

        def refresh_template(*_: object) -> None:
            set_payload_template()

        endpoint_combo.bind("<<ComboboxSelected>>", refresh_template)

        button_row = tk.Frame(window, bg="#2b2b30")
        button_row.pack(fill="x", padx=20, pady=(14, 0))

        tk.Button(
            button_row,
            text="Login API",
            font=("Segoe UI", 10, "bold"),
            bg="#3a3a40",
            fg="#f4f4f6",
            activebackground="#4a4a50",
            activeforeground="#ffffff",
            relief="flat",
            padx=14,
            pady=8,
            command=login_api,
        ).pack(side="left")

        tk.Button(
            button_row,
            text="Send request",
            font=("Segoe UI", 10, "bold"),
            bg="#ff6a00",
            fg="#ffffff",
            activebackground="#e65f00",
            activeforeground="#ffffff",
            relief="flat",
            padx=14,
            pady=8,
            command=send_request,
        ).pack(side="right")

        set_payload_template()
        window.after(150, auto_connect)

    def _copy_text_direct(self, value: str) -> None:
        self.clipboard_clear()
        self.clipboard_append(value)

    def _normalize_ticket_code(self, ticket: str) -> str:
        ticket_code = ticket.upper().strip()
        if not ticket_code:
            return ""
        if "-" not in ticket_code:
            ticket_code = f"QUIX-{ticket_code}"
        return ticket_code

    def _is_uuid(self, value: str) -> bool:
        return bool(re.fullmatch(r"[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}", value.strip().upper()))

    def _bootstrap_ticket_uuid_cache(self) -> None:
        changed = False
        for row in self.work_logs:
            ticket_code = self._normalize_ticket_code(str(row.get("ticket", "")))
            ticket_uuid = str(row.get("api_ticket_uuid", "")).strip().upper()
            if not ticket_code or not ticket_uuid:
                continue
            if ticket_code not in self.ticket_uuid_cache:
                self.ticket_uuid_cache[ticket_code] = ticket_uuid
                changed = True

        if changed:
            save_ticket_uuid_cache(self.ticket_uuid_cache)

    def _cache_ticket_uuid(self, ticket_reference: str, resolved_uuid: str) -> None:
        ticket_code = self._normalize_ticket_code(ticket_reference)
        uuid_value = resolved_uuid.strip().upper()
        if not ticket_code or not uuid_value:
            return

        previous = self.ticket_uuid_cache.get(ticket_code)
        if previous == uuid_value:
            return

        self.ticket_uuid_cache[ticket_code] = uuid_value
        save_ticket_uuid_cache(self.ticket_uuid_cache)

    def _resolve_ticket_uuid_cached(self, token: str, ticket_reference: str) -> str:
        normalized_ref = ticket_reference.strip().upper()
        if self._is_uuid(normalized_ref):
            api_log.event(f"    ticket UUID {normalized_ref} (già salvato sulla riga)")
            return normalized_ref

        ticket_code = self._normalize_ticket_code(normalized_ref)
        cached = self.ticket_uuid_cache.get(ticket_code)
        if cached:
            api_log.event(f"    ticket {ticket_code} → UUID {cached} (dalla cache ticket_uuid_cache.json)")
            return cached

        api_log.event(f"    ticket {ticket_code}: UUID non in cache, lo cerco nelle liste ticket del portale…")
        resolved_uuid, matched_code, source = self.api_client.resolve_ticket(token, ticket_code)
        api_log.event(f"    ticket {ticket_code} → UUID {resolved_uuid} (trovato come {matched_code} in {source})")
        if re.search(r"[A-Z]", matched_code) and matched_code != ticket_code:
            # Safety net: never send hours to a ticket with a different code.
            raise RuntimeError(
                f"Il portale ha restituito {matched_code} cercando {ticket_code}: invio bloccato per non registrare le ore sul ticket sbagliato."
            )
        self._cache_ticket_uuid(ticket_code, resolved_uuid)
        return resolved_uuid

    def _forget_ticket_uuid(self, ticket: str) -> None:
        ticket_code = self._normalize_ticket_code(ticket)
        removed = self.ticket_uuid_cache.pop(ticket_code, None)
        if removed is None:
            self._toast(f"{ticket_code} non era in cache: verrà cercato al prossimo invio", "info")
            return
        save_ticket_uuid_cache(self.ticket_uuid_cache)
        api_log.event(f"cache: rimosso {ticket_code} → {removed} (Ricalcola UUID)")
        self._toast(f"UUID di {ticket_code} dimenticato: al prossimo invio verrà cercato sul portale (vedi log API)", "info")

    def _set_dashboard_month(self, offset: int) -> None:
        self.selected_month_offset = offset
        self._render_worklogs()

    def _month_label_from_offset(self, offset: int) -> str:
        current = datetime.now()
        month_index = current.month + offset
        year = current.year
        while month_index <= 0:
            month_index += 12
            year -= 1
        while month_index > 12:
            month_index -= 12
            year += 1
        return datetime(year, month_index, 1).strftime("%B %Y")

    def _get_dashboard_month(self) -> str:
        return self._month_label_from_offset(self.selected_month_offset)

    def _get_summary_month(self) -> str:
        return self._get_dashboard_month()

    def _compute_month_summary(self, target_month: str) -> dict[str, object]:
        """Totals for one month label ("October 2026"). Same rules as the old summary bar."""
        month_rows = [row for row in self.work_logs if str(row.get("month", "")) == target_month]
        local_total = sum(self._hours_from_worklog_row(row) for row in month_rows)
        synced_rows = [row for row in month_rows if self._is_api_syncable(row) and self._is_worklog_synced(row)]
        pending_rows = [row for row in month_rows if self._is_api_syncable(row) and not self._is_worklog_synced(row)]
        off_rows = [row for row in month_rows if self._is_off_entry(row)]
        work_rows = [row for row in month_rows if not self._is_off_entry(row)]
        synced_total = sum(self._hours_from_worklog_row(row) for row in synced_rows)
        pending_total = sum(self._hours_from_worklog_row(row) for row in pending_rows)
        off_total = sum(self._hours_from_worklog_row(row) for row in off_rows)
        target_total = self._expected_month_hours(target_month)
        missing_total = max(target_total - local_total, 0.0)
        return {
            "rows": month_rows,
            "local_total": local_total,
            "work_total": local_total - off_total,
            "off_total": off_total,
            "synced_total": synced_total,
            "pending_total": pending_total,
            "target_total": target_total,
            "missing_total": missing_total,
            "over_total": max(local_total - target_total, 0.0),
            "verification": "OK" if abs(local_total - target_total) < 1e-9 else "CHECK",
            "business_days": int(round(target_total / 8)) if target_total else 0,
            "work_rows": len(work_rows),
            "work_tickets": len({str(row.get("ticket", "")) for row in work_rows}),
            "synced_rows": len(synced_rows),
            "pending_rows": len(pending_rows),
            "pending_tickets": len({str(row.get("ticket", "")) for row in pending_rows}),
        }

    def _refresh_summary(self) -> dict[str, object]:
        target_month = self._get_summary_month()
        s = self._compute_month_summary(target_month)
        local_total = float(s["local_total"])
        target_total = float(s["target_total"])
        synced_total = float(s["synced_total"])
        pending_total = float(s["pending_total"])
        off_total = float(s["off_total"])
        missing_total = float(s["missing_total"])
        over_total = float(s["over_total"])
        verification = str(s["verification"])

        self.month_view_var.set(self._month_label_it(self.selected_month_offset))
        self.summary_var.set(
            f"{target_month}  Total: {target_total:g}h ({verification})  Local: {local_total:g}h  Extra Off: {off_total:g}h  API synced: {synced_total:g}h  Pending: {pending_total:g}h  Missing: {missing_total:g}h"
        )

        if not self.kpi_labels:
            return s

        def set_kpi(key: str, value: str, sub: str) -> None:
            value_label, sub_label = self.kpi_labels[key]
            value_label.configure(text=value)
            sub_label.configure(text=sub)

        def rows_word(count: int) -> str:
            return "riga" if count == 1 else "righe"

        set_kpi("target", f"{target_total:g}h", f"{s['business_days']} giorni lavorativi × 8h")
        set_kpi("work", f"{float(s['work_total']):g}h", f"{s['work_rows']} {rows_word(int(s['work_rows']))} su {s['work_tickets']} ticket")
        off_days = off_total / 8
        set_kpi("off", f"{off_total:g}h", f"{off_days:g} {'giorno' if off_days == 1 else 'giorni'}" if off_total else "nessuna assenza")
        set_kpi("synced", f"{synced_total:g}h", f"{s['synced_rows']} {rows_word(int(s['synced_rows']))}")
        if pending_total:
            set_kpi("pending", f"{pending_total:g}h", f"{s['pending_rows']} {rows_word(int(s['pending_rows']))} su {s['pending_tickets']} ticket")
        else:
            set_kpi("pending", "0h", "tutto inviato")
        if missing_total:
            days, hours = divmod(missing_total, 8)
            sub = f"≈ {days:g} giorni e {hours:g}h" if days and hours else (f"{days:g} giorni" if days else f"{hours:g}h")
            set_kpi("missing", f"{missing_total:g}h", sub)
        elif over_total:
            set_kpi("missing", "0h", f"+{over_total:g}h oltre il target")
        else:
            set_kpi("missing", "0h", "mese completo")

        if verification == "OK":
            self.status_pill.configure(text="OK · mese completo", bg=C["ok_bg"], fg=C["ok"])
        elif over_total:
            self.status_pill.configure(text=f"CHECK · +{over_total:g}h oltre il target", bg=C["warn_bg"], fg=C["warn"])
        else:
            self.status_pill.configure(text=f"CHECK · mancano {missing_total:g}h", bg=C["warn_bg"], fg=C["warn"])

        scale = max(target_total, local_total, 1.0)
        self.progress_bar.set_segments([(synced_total / scale, C["ok"]), (pending_total / scale, C["warn"])])
        self.legend_labels["synced"].configure(text=f"Sincronizzate {synced_total:g}h")
        self.legend_labels["pending"].configure(text=f"Da sincronizzare {pending_total:g}h")
        self.legend_labels["missing"].configure(text=f"Mancanti {missing_total:g}h")
        percent = int(round(local_total / target_total * 100)) if target_total else 0
        self.progress_total_label.configure(text=f"{local_total:g}h di {target_total:g}h · {percent}%")

        self.month_button.configure(text=self._month_label_it(self.selected_month_offset))
        self.next_month_btn.configure(state="disabled" if self.selected_month_offset >= 0 else "normal")
        for child in self.month_tag_slot.winfo_children():
            child.destroy()
        if self.selected_month_offset == 0:
            tk.Label(self.month_tag_slot, text="Mese corrente", font=F["small"], bg=C["surface"], fg=C["muted"], padx=8, pady=3).pack()
        else:
            button(self.month_tag_slot, "Torna al mese corrente", lambda: self._set_dashboard_month(0), variant="ghost", size="sm", parent_bg=C["bg_app"]).pack()

        pending_rows = int(s["pending_rows"])
        self.compare_btn.configure(state="disabled" if self.jobs.running else "normal")
        if self.jobs.running:
            self.sync_month_btn.configure(text=f"{self.jobs.label.capitalize()}…" if self.jobs.label else "Sincronizzazione…", state="disabled")
        else:
            self.sync_month_btn.configure(
                text=f"Sincronizza mese ({pending_rows})" if pending_rows else "Sincronizza mese",
                state="normal" if pending_rows else "disabled",
            )
        return s

    def _expected_month_hours(self, month_label: str) -> float:
        try:
            target = datetime.strptime(month_label, "%B %Y")
        except ValueError:
            return 0.0

        year = target.year
        month = target.month
        _, days_in_month = calendar.monthrange(year, month)
        italian_holidays = self._italian_public_holidays(year)

        business_days = 0
        for day in range(1, days_in_month + 1):
            current_day = date(year, month, day)
            if current_day.weekday() < 5 and current_day not in italian_holidays:
                business_days += 1

        return float(business_days * 8)

    def _italian_public_holidays(self, year: int) -> set[date]:
        easter_sunday = self._easter_sunday(year)
        easter_monday = easter_sunday + timedelta(days=1)
        return {
            date(year, 1, 1),
            date(year, 1, 6),
            date(year, 4, 25),
            date(year, 5, 1),
            date(year, 6, 2),
            date(year, 8, 15),
            date(year, 11, 1),
            date(year, 12, 8),
            date(year, 12, 25),
            date(year, 12, 26),
            easter_monday,
        }

    def _easter_sunday(self, year: int) -> date:
        # Anonymous Gregorian algorithm.
        a = year % 19
        b = year // 100
        c = year % 100
        d = b // 4
        e = b % 4
        f = (b + 8) // 25
        g = (b - f + 1) // 3
        h = (19 * a + b - d - g + 15) % 30
        i = c // 4
        k = c % 4
        l = (32 + 2 * e + 2 * i - h - k) % 7
        m = (a + 11 * h + 22 * l) // 451
        month = (h + l - 7 * m + 114) // 31
        day = ((h + l - 7 * m + 114) % 31) + 1
        return date(year, month, day)

    def _hours_from_worklog_row(self, row: dict[str, str]) -> float:
        parsed = self._parse_working_time(str(row.get("working_time", "")))
        return parsed[1] if parsed is not None else 0.0

    def _is_worklog_synced(self, row: dict[str, str]) -> bool:
        return str(row.get("api_synced", "")).lower() == "true"

    def _is_off_entry(self, row: dict[str, str]) -> bool:
        return str(row.get("entry_type", "work")).strip().lower() == "off"

    @staticmethod
    def _is_api_lock_error(exc: Exception | str) -> bool:
        text = str(exc).lower()
        return "this entry is locked" in text or "entry is locked" in text or "message':'this entry is locked'" in text

    def _is_api_syncable(self, row: dict[str, str]) -> bool:
        return True

    def _extra_hours_type_from_row(self, row: dict[str, str]) -> str:
        raw = str(row.get("off_type", "")).strip()
        if raw:
            return raw
        description = str(row.get("description", "")).strip()
        if description:
            return description
        return "Annual Leave"

    def _extra_hours_date_from_row(self, row: dict[str, str]) -> str:
        raw = str(row.get("log_date", "")).strip()
        if raw:
            return raw
        return datetime.now().date().isoformat()

    def _extra_hours_aggregate_row(self, row: dict[str, str]) -> dict[str, str]:
        month_label = str(row.get("month", "")).strip()
        off_rows = [
            candidate
            for candidate in self.work_logs
            if self._is_off_entry(candidate) and str(candidate.get("month", "")).strip() == month_label
        ]
        if not off_rows:
            off_rows = [row]

        source_row = max(off_rows, key=self._hours_from_worklog_row)
        total_hours = sum(self._hours_from_worklog_row(candidate) for candidate in off_rows)
        aggregated = dict(source_row)
        aggregated["working_time"] = f"{total_hours:g}h"
        return aggregated

    def _format_decimal_hours(self, hours_value: float) -> float:
        """Return hours as decimal float for /api/extrahours/add payloads."""
        return round(float(hours_value), 2)

    def _extra_hours_date_variants(self, iso_date: str) -> dict[str, str]:
        """Build common date variants accepted by different extra-hours API deployments."""
        try:
            parsed = datetime.strptime(iso_date, "%Y-%m-%d")
        except ValueError:
            parsed = datetime.now()

        normalized_iso = parsed.strftime("%Y-%m-%d")
        return {
            "iso_date": normalized_iso,
            "iso_datetime": f"{normalized_iso}T00:00:00",
            "iso_datetime_z": f"{normalized_iso}T00:00:00.000Z",
            "iso_datetime_end_z": f"{normalized_iso}T23:59:59.999Z",
            "iso_datetime_space": f"{normalized_iso} 00:00:00",
            "ymd_slash": parsed.strftime("%Y/%m/%d"),
            "it_date": parsed.strftime("%d/%m/%Y"),
            "dmy_dash": parsed.strftime("%d-%m-%Y"),
            "it_datetime": parsed.strftime("%d/%m/%Y 00:00:00"),
        }

    def _request_extra_hours_guid(self, token: str) -> str:
        response = self.api_client.request_query("/api/tickets/newguid", token)
        payload = response.payload
        if not isinstance(payload, dict):
            raise RuntimeError("The API did not return a GUID for the extra off entry.")

        guid = str(payload.get("guid", "")).strip()
        if not self._is_uuid(guid):
            raise RuntimeError("The API returned an invalid GUID for the extra off entry.")
        return guid

    def _build_extra_hours_payload_for_row(self, row: dict[str, str], token: str) -> dict[str, object]:
        hours_value = self._hours_from_worklog_row(row)
        if hours_value <= 0:
            raise RuntimeError("Extra off entry has invalid hours (must be > 0).")

        decimal_hours = self._format_decimal_hours(hours_value)
        date_value = self._extra_hours_date_from_row(row)
        date_variants = self._extra_hours_date_variants(date_value)
        type_value = self._extra_hours_type_from_row(row)
        task_id = get_clockify_task_id(type_value)
        entry_guid = self._request_extra_hours_guid(token)
        description_value = str(row.get("comment", "")).strip() or str(row.get("description", "")).strip() or "extra off"
        payload_hours: int | float = int(decimal_hours) if float(decimal_hours).is_integer() else decimal_hours
        # Prefill with the currently requested shape; user can still edit before send.
        return {
            "uuid": entry_guid,
            "id_clockify_task": task_id,
            "hours": payload_hours,
            "log_date_start": date_variants["it_date"],
            "log_date_end": date_variants["it_date"],
            "description": description_value,
        }

    def _format_sync_status(self, row: dict[str, str]) -> str:
        if not self._is_worklog_synced(row):
            return "Off pending API" if self._is_off_entry(row) else "Pending API"

        synced_at = str(row.get("api_synced_at", "")).strip()
        if not synced_at:
            return "API synced"
        try:
            parsed = datetime.fromisoformat(synced_at)
            if parsed.tzinfo is not None:
                parsed = parsed.astimezone()
            short_stamp = parsed.strftime("%Y-%m-%d %H:%M")
        except ValueError:
            short_stamp = synced_at.replace("T", " ")[:16]
        prefix = "Off synced" if self._is_off_entry(row) else "Synced"
        return f"{prefix} {short_stamp}"

    def _month_displacement_for_label(self, month_label: str) -> str:
        try:
            target = datetime.strptime(month_label, "%B %Y")
        except ValueError:
            return "0"

        current = datetime.now()
        displacement = (target.year - current.year) * 12 + (target.month - current.month)
        return str(displacement)

    def _ensure_api_session(self) -> str:
        username = self.credentials["username"]
        if self.api_token and self.api_token_user == username:
            return self.api_token

        api_log.event(f"login portale come {username}")
        token, _payload = self.api_client.login(username, self.credentials["password"])
        self.api_token = token
        self.api_token_user = username
        return token

    def _extract_clockify_user_uuid(self, payload: object, username: str) -> str:
        target = username.strip().lower()
        target_short = target.split("@")[0]
        fallback = ""

        def walk(node: object) -> None:
            nonlocal fallback
            if isinstance(node, dict):
                values = {str(k).lower(): v for k, v in node.items()}
                uuid_candidate = (
                    values.get("uuid")
                    or values.get("id")
                    or values.get("userid")
                    or values.get("user_uuid")
                    or values.get("clockify_user_uuid")
                    or values.get("clockifyuserid")
                )
                uuid_value = str(uuid_candidate).strip() if uuid_candidate is not None else ""
                if uuid_value and not fallback:
                    fallback = uuid_value

                user_fields = [
                    values.get("email"),
                    values.get("username"),
                    values.get("user"),
                    values.get("name"),
                    values.get("fullname"),
                ]
                for field in user_fields:
                    if not isinstance(field, str):
                        continue
                    normalized_field = field.strip().lower()
                    if uuid_value and (
                        normalized_field == target
                        or normalized_field == target_short
                        or target_short in normalized_field
                    ):
                        fallback = uuid_value
                        return

                for child in node.values():
                    walk(child)

            elif isinstance(node, list):
                for item in node:
                    walk(item)

        walk(payload)
        return fallback

    def _resolve_clockify_user_uuid(self, token: str) -> str:
        if self.clockify_user_uuid:
            return self.clockify_user_uuid

        try:
            response = self.api_client.request_query("/api/extrahours/clockify_users", token, None)
        except Exception as exc:  # noqa: BLE001 - keep sync flow alive without uuid
            print(f"Clockify users lookup failed: {exc}")
            return ""

        print("Clockify users response payload (first 2000 chars):")
        try:
            serialized = json.dumps(response.payload, ensure_ascii=False)
        except TypeError:
            serialized = str(response.payload)
        print(serialized[:2000])

        resolved = self._extract_clockify_user_uuid(response.payload, self.credentials["username"])
        if not resolved:
            print("Clockify user uuid not found in /api/extrahours/clockify_users response; proceeding without uuid.")
            return ""

        self.clockify_user_uuid = resolved
        return resolved

    def _build_api_payload_for_row(self, row: dict[str, str], token: str) -> tuple[str, dict[str, str]]:
        ticket_reference = str(row.get("api_ticket_uuid", "")).strip() or str(row.get("ticket", "")).strip()
        resolved_uuid = self._resolve_ticket_uuid_cached(token, ticket_reference)
        payload = {
            "TicketId": resolved_uuid,
            "Username": self.credentials["username"],
            "MonthDisplacement": self._month_displacement_for_label(str(row.get("month", ""))),
            "Reason": str(row.get("comment", "")).strip() or self._normalize_work_log(row),
            "WorkingTime": str(row.get("working_time", "")).strip(),
        }
        return resolved_uuid, payload

    def _mark_row_as_synced(self, row: dict[str, str], resolved_uuid: str, month_displacement: str) -> None:
        self._cache_ticket_uuid(str(row.get("ticket", "")), resolved_uuid)
        row["api_synced"] = "true"
        row["api_synced_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        row["api_ticket_uuid"] = resolved_uuid
        row["api_month_displacement"] = month_displacement

    def _mark_row_as_extra_hours_synced(self, row: dict[str, str]) -> None:
        row["api_synced"] = "true"
        row["api_synced_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        row["api_ticket_uuid"] = ""
        row["api_month_displacement"] = ""

    def _debug_log_extra_hours_payload(self, payload: dict[str, object], attempt_index: int) -> None:
        timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
        print(f"[{timestamp}] ExtraHours sync attempt {attempt_index} -> POST /api/extrahours/add")
        print(json.dumps(payload, indent=2, ensure_ascii=False))

    def _edit_extra_hours_payload(self, payload: dict[str, object]) -> dict[str, object] | None:
        window = tk.Toplevel(self)
        window.title("Edit Extra Hours Payload")
        window.geometry("760x520")
        window.configure(bg="#2b2b30")
        window.transient(self)
        window.grab_set()

        tk.Label(
            window,
            text="Edit JSON payload before sending to /api/extrahours/add",
            font=("Segoe UI", 10, "bold"),
            fg="#f4f4f6",
            bg="#2b2b30",
        ).pack(anchor="w", padx=16, pady=(14, 8))

        editor = tk.Text(window, width=90, height=23, font=("Consolas", 10), wrap="none")
        editor.pack(fill="both", expand=True, padx=16)
        editor.insert("1.0", json.dumps(payload, indent=2, ensure_ascii=False))

        result: dict[str, object] | None = None

        def send_payload() -> None:
            nonlocal result
            raw = editor.get("1.0", "end").strip()
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError as exc:
                messagebox.showerror("Invalid JSON", f"Payload JSON non valido: {exc}")
                return
            if not isinstance(parsed, dict):
                messagebox.showerror("Invalid payload", "Payload must be a JSON object.")
                return
            result = parsed
            window.destroy()

        def cancel_payload() -> None:
            window.destroy()

        row = tk.Frame(window, bg="#2b2b30")
        row.pack(fill="x", padx=16, pady=(10, 14))

        tk.Button(
            row,
            text="Cancel",
            font=("Segoe UI", 10),
            bg="#3a3a40",
            fg="#f4f4f6",
            activebackground="#4a4a50",
            activeforeground="#ffffff",
            relief="flat",
            padx=12,
            pady=6,
            command=cancel_payload,
        ).pack(side="left")

        tk.Button(
            row,
            text="Send",
            font=("Segoe UI", 10, "bold"),
            bg="#ff6a00",
            fg="#ffffff",
            activebackground="#e65f00",
            activeforeground="#ffffff",
            relief="flat",
            padx=12,
            pady=6,
            command=send_payload,
        ).pack(side="right")

        self.wait_window(window)
        return result

    def _sync_extra_hours_row(self, token: str, row: dict[str, str]) -> bool:
        try:
            payload = self._build_extra_hours_payload_for_row(row, token)
            self.api_client.request_json("POST", "/api/extrahours/add", token, payload)
            self._mark_row_as_extra_hours_synced(row)
            row["api_entry_id"] = str(payload.get("uuid", ""))
            return True
        except Exception as exc:  # noqa: BLE001 - expose payload and server error
            if self._is_api_lock_error(exc):
                self._mark_row_as_extra_hours_synced(row)
                return True
            payload_preview = json.dumps(payload, ensure_ascii=False) if "payload" in locals() else "{}"
            raise RuntimeError(
                "Failed to sync extra off entry with /api/extrahours/add: "
                f"{exc} | Payload: {payload_preview}"
            ) from exc

    def _sync_single_worklog(self, index: int) -> None:
        if index < 0 or index >= len(self.work_logs):
            return
        row = self.work_logs[index]
        if self._is_worklog_synced(row):
            self._toast("Questa riga è già sincronizzata", "info")
            return
        self._start_sync_job([row], str(row.get("ticket", "")))

    def _sync_ticket_worklogs(self, ticket_code: str) -> None:
        normalized_ticket = self._normalize_ticket_code(ticket_code)
        indexes = [
            index
            for index, row in enumerate(self.work_logs)
            if str(row.get("ticket", "")) == normalized_ticket and self._is_api_syncable(row) and not self._is_worklog_synced(row)
        ]
        self._sync_multiple_worklogs(indexes, normalized_ticket)

    def _sync_current_month(self) -> None:
        target_month = self._get_summary_month()
        indexes = [
            index
            for index, row in enumerate(self.work_logs)
            if str(row.get("month", "")) == target_month and self._is_api_syncable(row) and not self._is_worklog_synced(row)
        ]
        self._sync_multiple_worklogs(indexes, self._month_label_it(self.selected_month_offset))

    def _import_qxsupport_current_month(self) -> None:
        if self.jobs.running:
            self._toast(f"Attendi: {self.jobs.label} in corso", "info")
            return
        target_month = self._get_summary_month()
        month_it = self._month_label_it(self.selected_month_offset)

        def worker(emit: object, _cancel: object) -> tuple[list[dict[str, str]], float]:
            token = self._ensure_api_session()
            return self._fetch_qxsupport_remote_data(token, target_month)

        def on_finish(result: object, error: BaseException | None) -> None:
            self.toast.hide_progress()
            self._render_worklogs()
            if error is not None:
                self._notify_error("Import QxSupport non riuscito", error)
                return
            assert isinstance(result, tuple)
            detailed_rows, aggregate_hours = result
            self._apply_qxsupport_import(target_month, month_it, detailed_rows, aggregate_hours)

        self.jobs.start("import QxSupport", worker, on_event=lambda *_: None, on_finish=on_finish)
        self.toast.progress(f"Import QxSupport di {month_it}…", 0, 1)
        self._render_worklogs()

    def _apply_qxsupport_import(
        self,
        target_month: str,
        month_it: str,
        detailed_rows: list[dict[str, str]],
        aggregate_hours: float,
    ) -> None:
        added = 0
        skipped = 0
        now_stamp = datetime.now().astimezone().isoformat(timespec="seconds")
        existing_signatures = {
            self._import_signature(
                str(row.get("month", "")),
                str(row.get("ticket", "")),
                str(row.get("working_time", "")),
                str(row.get("comment", "")),
            )
            for row in self.work_logs
        }

        if detailed_rows:
            for remote_entry in detailed_rows:
                signature = self._import_signature(target_month, remote_entry["ticket"], remote_entry["working_time"], remote_entry["comment"])
                if signature in existing_signatures:
                    skipped += 1
                    continue

                self.work_logs.insert(
                    0,
                    {
                        "working_time": remote_entry["working_time"],
                        "month": target_month,
                        "work_log": remote_entry["comment"],
                        "ticket": remote_entry["ticket"],
                        "comment": remote_entry["comment"],
                        "description": remote_entry["description"],
                        "entry_type": "work",
                        "off_type": "",
                        "log_date": remote_entry["log_date"],
                        "api_synced": "true",
                        "api_synced_at": now_stamp,
                        "api_ticket_uuid": str(remote_entry.get("api_ticket_uuid", "")),
                        "api_month_displacement": self._month_displacement_for_label(target_month),
                    },
                )
                existing_signatures.add(signature)
                added += 1
        elif aggregate_hours > 0:
            working_time_label = f"{aggregate_hours:g}h"
            ticket_code = "QXSUPPORT"
            comment = f"Imported from QxSupport monthly report ({target_month})"
            signature = self._import_signature(target_month, ticket_code, working_time_label, comment)
            if signature in existing_signatures:
                skipped += 1
            else:
                self.work_logs.insert(
                    0,
                    {
                        "working_time": working_time_label,
                        "month": target_month,
                        "work_log": comment,
                        "ticket": ticket_code,
                        "comment": comment,
                        "description": "QxSupport monthly import",
                        "entry_type": "work",
                        "off_type": "",
                        "log_date": datetime.now().date().isoformat(),
                        "api_synced": "true",
                        "api_synced_at": now_stamp,
                        "api_ticket_uuid": "",
                        "api_month_displacement": self._month_displacement_for_label(target_month),
                    },
                )
                added += 1
        else:
            self._toast(f"Nessuna ora QxSupport trovata per {month_it}", "warning")
            return

        save_work_logs(self.work_logs)
        self._render_worklogs()
        skipped_text = f" · {skipped} duplicati ignorati" if skipped else ""
        self._toast(f"QxSupport: importate {added} righe per {month_it}{skipped_text}")

    def _fetch_qxsupport_remote_data(self, token: str, month_label: str) -> tuple[list[dict[str, str]], float]:
        displacement = self._month_displacement_for_label(month_label)
        endpoint_candidates = [
            ("/api/working_hours/list", {"MonthDisplacement": displacement}),
            ("/api/working_hours/list", {"monthDisplacement": displacement}),
            ("/api/working_hours/report", {"MonthDisplacement": displacement}),
            ("/api/monthlyreport", {"MonthDisplacement": displacement}),
            ("/api/admin/monthlyreport", {"MonthDisplacement": displacement}),
            ("/api/reports/monthly", {"MonthDisplacement": displacement}),
        ]

        best_aggregate = 0.0
        for path, query in endpoint_candidates:
            try:
                response = self.api_client.request_query(path, token, query)
            except Exception:
                continue

            detailed_rows = self._extract_qxsupport_detailed_rows(response.payload)
            if detailed_rows:
                return detailed_rows, 0.0

            aggregate = self._extract_qxsupport_aggregate_hours(response.payload)
            if aggregate > best_aggregate:
                best_aggregate = aggregate

        return [], best_aggregate

    def _extract_qxsupport_detailed_rows(self, payload: object) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []

        def visit(node: object) -> None:
            if isinstance(node, dict):
                lowered = {str(key).lower(): value for key, value in node.items()}
                project_value = lowered.get("project") or lowered.get("projectname") or lowered.get("project_name")
                has_qxsupport = isinstance(project_value, str) and "qxsupport" in project_value.lower().replace(" ", "")

                if has_qxsupport:
                    hours_candidate = (
                        lowered.get("workingtime")
                        or lowered.get("working_time")
                        or lowered.get("hours")
                        or lowered.get("total")
                    )
                    parsed_hours = self._hours_value_from_remote(hours_candidate)
                    if parsed_hours is not None and parsed_hours > 0:
                        ticket_value = (
                            lowered.get("ticket")
                            or lowered.get("ticketid")
                            or lowered.get("internal_id")
                            or lowered.get("ticketcode")
                            or "QXSUPPORT"
                        )
                        ticket_code = "QXSUPPORT"
                        comment_value = (
                            lowered.get("reason")
                            or lowered.get("comment")
                            or lowered.get("work_log")
                            or lowered.get("description")
                            or "Imported from QxSupport"
                        )
                        comment_text = str(comment_value).strip() or "Imported from QxSupport"
                        description_value = lowered.get("description") or lowered.get("ticketdescription") or "QxSupport import"
                        log_date_value = lowered.get("log_date") or lowered.get("date") or datetime.now().date().isoformat()
                        api_ticket_uuid = str(lowered.get("uuid") or lowered.get("ticketuuid") or "").strip().upper()
                        rows.append(
                            {
                                "ticket": ticket_code,
                                "working_time": f"{parsed_hours:g}h",
                                "comment": comment_text,
                                "description": str(description_value).strip() or "QxSupport import",
                                "log_date": str(log_date_value).strip() or datetime.now().date().isoformat(),
                                "api_ticket_uuid": api_ticket_uuid,
                            }
                        )

                for value in node.values():
                    visit(value)
            elif isinstance(node, list):
                for item in node:
                    visit(item)

        visit(payload)

        unique: list[dict[str, str]] = []
        seen: set[tuple[str, str, str]] = set()
        for row in rows:
            key = (row["ticket"], row["working_time"], row["comment"])
            if key in seen:
                continue
            seen.add(key)
            unique.append(row)
        return unique

    def _extract_qxsupport_aggregate_hours(self, payload: object) -> float:
        values: list[float] = []

        def visit(node: object) -> None:
            if isinstance(node, dict):
                lowered = {str(key).lower(): value for key, value in node.items()}

                direct = lowered.get("qxsupport")
                parsed_direct = self._hours_value_from_remote(direct)
                if parsed_direct is not None and parsed_direct > 0:
                    values.append(parsed_direct)

                project_name = (
                    lowered.get("project")
                    or lowered.get("projectname")
                    or lowered.get("name")
                    or lowered.get("label")
                )
                if isinstance(project_name, str) and "qxsupport" in project_name.lower().replace(" ", ""):
                    for metric_key in ("total", "hours", "totalproject", "value"):
                        parsed_metric = self._hours_value_from_remote(lowered.get(metric_key))
                        if parsed_metric is not None and parsed_metric > 0:
                            values.append(parsed_metric)

                for value in node.values():
                    visit(value)
            elif isinstance(node, list):
                for item in node:
                    visit(item)

        visit(payload)
        if not values:
            return 0.0
        return max(values)

    def _hours_value_from_remote(self, raw: object) -> float | None:
        if isinstance(raw, (int, float)):
            value = float(raw)
            return value if value > 0 else None

        if isinstance(raw, str):
            normalized = raw.strip().lower().replace(",", ".")
            if not normalized:
                return None

            parsed = self._parse_working_time(normalized)
            if parsed is not None:
                return parsed[1]

            match = re.search(r"\d+(?:\.\d+)?", normalized)
            if not match:
                return None
            value = float(match.group(0))
            return value if value > 0 else None

        return None

    def _import_signature(self, month_label: str, ticket: str, working_time: str, comment: str) -> str:
        return "|".join(
            [
                month_label.strip().lower(),
                ticket.strip().upper(),
                working_time.strip().lower(),
                comment.strip().lower(),
            ]
        )

    def _sync_multiple_worklogs(self, indexes: list[int], scope_label: str) -> None:
        rows = [self.work_logs[index] for index in indexes if 0 <= index < len(self.work_logs)]
        self._start_sync_job(rows, scope_label)

    # ------------------------------------------------------------------ background sync
    _SYNC_FIELDS = (
        "api_synced",
        "api_synced_at",
        "api_ticket_uuid",
        "api_month_displacement",
        "api_entry_id",
        "api_pending_action",
        "api_prev_values",
    )

    # ------------------------------------------------------------------ portal entries (update / delete)
    @property
    def portal(self) -> PortalTickets:
        # self.__dict__ instead of getattr: tk.Tk.__getattr__ recurses when the window is not initialised (tests).
        portal = self.__dict__.get("_portal_tickets")
        if portal is None or portal.client is not self.api_client:
            portal = PortalTickets(self.api_client)
            self._portal_tickets = portal
        return portal

    def _claimed_entry_ids(self, except_row: dict[str, str] | None = None) -> set[str]:
        return {
            str(row.get("api_entry_id", "")).upper()
            for row in self.work_logs
            if row is not except_row and str(row.get("api_entry_id", "")).strip()
        }

    def _portal_values_of(self, row: dict[str, str]) -> tuple[float, str]:
        """Hours and reason as they are on the portal (before a local edit, if any)."""
        prev: dict[str, str] = {}
        raw_prev = str(row.get("api_prev_values", "")).strip()
        if raw_prev:
            try:
                prev = json.loads(raw_prev)
            except json.JSONDecodeError:
                prev = {}
        working_time = str(prev.get("working_time") or row.get("working_time", ""))
        reason = str(prev.get("comment") or row.get("comment", "")).strip() or self._normalize_work_log(row)
        parsed = self._parse_working_time(working_time)
        return (parsed[1] if parsed else 0.0), reason

    def _lookup_entry_id(self, token: str, ticket_uuid: str, row: dict[str, str]) -> str:
        """Find the portal Id of a row synced before Ids were stored (working_hours/list)."""
        hours, reason = self._portal_values_of(row)
        entries = self.portal.list_working_hours(token, ticket_uuid)
        entry_id = find_entry_id(
            entries,
            username=self.credentials["username"],
            month_label=str(row.get("month", "")),
            hours=hours,
            reason=reason,
            exclude_ids=self._claimed_entry_ids(except_row=row),
        )
        api_log.event(
            f"    cerco la voce sul portale ({len(entries)} voci sul ticket, {hours:g}h, \"{reason[:60]}\") → "
            + (f"Id {entry_id}" if entry_id else "non trovata")
        )
        return entry_id

    def _portal_entry_kind(self, row: dict[str, str]) -> str:
        """How a synced row exists on the portal: "entry" (working_hours, updatable), "off", "web" or ""."""
        if not (self._is_worklog_synced(row) or row.get("api_pending_action") == "update"):
            return ""
        if self._is_off_entry(row):
            return "off"
        if str(row.get("api_post_uuid", "")).strip():
            return "web"
        if str(row.get("entry_type", "work")) in ALREADY_SYNCED_TYPES:
            return "web"
        return "entry"

    def _sync_row_with_portal(self, token: str, row: dict[str, str]) -> None:
        """Send one row to the portal and mark *that dict* as synced. Runs on the worker thread:
        it must not touch Tk; it works on a copy of the row."""
        kind = "Extra Off" if self._is_off_entry(row) else "lavoro"
        api_log.event(
            f"SYNC {row.get('ticket', '')} · {row.get('log_date', '')} · {row.get('working_time', '')} · {kind} · "
            f"mese {row.get('month', '')}"
        )
        try:
            if self._is_off_entry(row):
                self._sync_extra_hours_row(token, row)
            else:
                resolved_uuid, payload = self._build_api_payload_for_row(row, token)
                entry_id = ""
                if row.get("api_pending_action") == "update":
                    entry_id = str(row.get("api_entry_id", "")).strip() or self._lookup_entry_id(token, resolved_uuid, row)
                    if not entry_id:
                        raise RuntimeError(
                            "voce da aggiornare non trovata sul portale. Controlla il ticket dal web oppure usa "
                            "“Invia come nuova voce” dal menu ⋯ della riga."
                        )
                    payload["Id"] = entry_id
                    api_log.event(f"    aggiorno la voce esistente Id {entry_id} (nessun duplicato)")
                response = self.api_client.request_json("POST", "/api/working_hours/form", token, payload)
                self._mark_row_as_synced(row, resolved_uuid, payload["MonthDisplacement"])
                returned_payload = getattr(response, "payload", None)
                returned = returned_payload if isinstance(returned_payload, str) else ""
                row["api_entry_id"] = returned.strip().upper() if self._is_uuid(returned) else entry_id.upper()
                row["api_pending_action"] = ""
                row["api_prev_values"] = ""
        except Exception as exc:
            api_log.event(f"    ESITO: ERRORE · {exc}")
            raise
        api_log.event(f"    ESITO: OK · ticket UUID {row.get('api_ticket_uuid', '') or '-'}")

    def _confirm_resend_rows(self, rows: list[dict[str, str]]) -> list[dict[str, str]] | None:
        """Rows edited after a previous sync could create duplicates on the portal: ask first.
        Returns the rows to send, or None to abort."""
        resend = [row for row in rows if str(row.get("api_resend_of", "")).strip()]
        if not resend:
            return rows
        lines = []
        for row in resend[:6]:
            previous = str(row.get("api_resend_of", ""))
            try:
                previous = datetime.fromisoformat(previous).astimezone().strftime("%d/%m %H:%M")
            except ValueError:
                pass
            lines.append(f"• {row.get('ticket', '')} {self._format_row_date(row)} · {row.get('working_time', '')} (inviata il {previous})")
        if len(resend) > 6:
            lines.append(f"• … e altre {len(resend) - 6}")
        answer = messagebox.askyesnocancel(
            "Possibili duplicati sul portale",
            "Queste righe erano già state inviate e poi modificate:\n\n"
            + "\n".join(lines)
            + "\n\nIl portale non permette di aggiornarle: un nuovo invio crea una seconda voce.\n"
            "Hai già cancellato le voci vecchie dal web?\n\n"
            "Sì = invia anche queste · No = salta queste righe · Annulla = non inviare nulla",
            icon="warning",
        )
        if answer is None:
            return None
        if answer:
            return rows
        resend_ids = {id(row) for row in resend}
        return [row for row in rows if id(row) not in resend_ids]

    def _start_sync_job(self, rows: list[dict[str, str]], scope_label: str) -> None:
        if self.jobs.running:
            self._toast(f"Attendi: {self.jobs.label} in corso", "info")
            return

        pending = [row for row in rows if self._is_api_syncable(row) and not self._is_worklog_synced(row)]
        if not pending:
            self._toast(f"Niente da sincronizzare per {scope_label}", "info")
            return

        confirmed = self._confirm_resend_rows(pending)
        if confirmed is None:
            return
        if not confirmed:
            self._toast("Nessuna riga inviata", "info")
            return

        jobs = [(row, dict(row)) for row in confirmed]
        total = len(jobs)
        stats = {"ok": 0, "done": 0, "cancelled": False}
        failures: list[str] = []
        self.rows_in_flight = {id(row) for row in confirmed}

        def worker(emit: Callable[[str, object], None], cancel: threading.Event) -> None:
            api_log.event(f"=== Sync {scope_label}: {total} {'riga' if total == 1 else 'righe'} ===")
            token = self._ensure_api_session()
            for position, (original, copy) in enumerate(jobs):
                if cancel.is_set():
                    api_log.event(f"=== Annullato dall'utente dopo {position} di {total} ===")
                    emit("cancelled", position)
                    return
                emit("current", (position, str(copy.get("ticket", ""))))
                try:
                    self._sync_row_with_portal(token, copy)
                    emit("row_ok", (original, copy))
                except Exception as exc:  # noqa: BLE001 - keep going, report at the end
                    emit("row_error", (original, f"{copy.get('ticket', '')} {self._format_row_date(copy)}: {exc}"))

        def on_cancel() -> None:
            self.jobs.cancel()
            self.toast.progress_cancel_requested()

        def on_event(kind: str, payload: object) -> None:
            if kind == "current":
                position, ticket = payload  # type: ignore[misc]
                self.toast.progress(f"Invio {ticket} · {position + 1} di {total}…", position, total, on_cancel=on_cancel)
            elif kind == "row_ok":
                original, copy = payload  # type: ignore[misc]
                for key in self._SYNC_FIELDS:
                    original[key] = copy.get(key, "")
                original["api_resend_of"] = ""
                self.rows_in_flight.discard(id(original))
                stats["ok"] += 1
                stats["done"] += 1
                if any(item is original for item in self.work_logs):
                    save_work_logs(self.work_logs)
                self._schedule_render()
            elif kind == "row_error":
                original, message = payload  # type: ignore[misc]
                self.rows_in_flight.discard(id(original))
                failures.append(str(message))
                stats["done"] += 1
                self._schedule_render()
            elif kind == "cancelled":
                stats["cancelled"] = True
            if self.toast.progress_visible and kind in {"row_ok", "row_error"}:
                self.toast.progress(f"Sincronizzate {stats['done']} di {total}…", int(stats["done"]), total, on_cancel=on_cancel)

        def on_finish(_result: object, error: BaseException | None) -> None:
            self.rows_in_flight = set()
            self.toast.hide_progress()
            self._render_worklogs()
            if error is not None:
                self._notify_error("Login al portale non riuscito", error)
                return
            ok = int(stats["ok"])
            if failures:
                detail = f"Sincronizzate {ok} righe per {scope_label}. Errori: {len(failures)}\n\n" + "\n".join(failures[:8])
                if len(failures) == 1 and total == 1:
                    self._notify_error(f"Sync {scope_label} non riuscito", failures[0])
                    return
                self._toast(
                    f"Sincronizzate {ok} righe, {len(failures)} con errore",
                    "error",
                    action_text="Dettagli",
                    action=lambda: messagebox.showwarning("Sync completato con errori", detail),
                )
                return
            if stats["cancelled"]:
                self._toast(f"Sync annullato · inviate {ok} di {total} righe", "warning")
                return
            if total == 1:
                row = jobs[0][0]
                message = f"{row.get('ticket', '')} sincronizzato · {row.get('working_time', '')} inviate"
            else:
                message = f"Sincronizzate {ok} righe ({scope_label})"
            self._toast(message, action_text="Apri report", action=self._open_monthly_report)

        self.jobs.start(f"sync {scope_label}", worker, on_event=on_event, on_finish=on_finish)
        self.toast.progress(f"Connessione al portale · {total} {'riga' if total == 1 else 'righe'} da inviare…", 0, total, on_cancel=on_cancel)
        self._render_worklogs()

    def _confirm_close(self) -> None:
        if self.jobs.running and not messagebox.askyesno(
            "Sincronizzazione in corso",
            f"C'è {self.jobs.label} in corso. Chiudere comunque?\n"
            "Le righe già confermate restano salvate, quella in invio potrebbe arrivare al portale senza essere segnata qui.",
            icon="warning",
        ):
            return
        self.destroy()

    def _find_ticket_description(self, ticket: str) -> str:
        ticket_code = self._normalize_ticket_code(ticket)
        for row in self.work_logs:
            if row.get("ticket", "") == ticket_code:
                return row.get("description", "")
        return ""

    def _normalize_work_log(self, row: dict[str, str]) -> str:
        ticket = row.get("ticket", "").strip()
        work_log = row.get("work_log", "")
        prefix = f"{ticket} - "
        if ticket and work_log.startswith(prefix):
            return work_log[len(prefix):]
        return work_log

    def _group_worklogs_by_ticket(self, rows: list[dict[str, str]]) -> dict[str, dict[str, object]]:
        grouped: dict[str, dict[str, object]] = {}
        # Index by identity: two rows with identical content must keep distinct indexes.
        index_by_id = {id(item): position for position, item in enumerate(self.work_logs)}
        for row in rows:
            index = index_by_id.get(id(row))
            if index is None:
                continue
            ticket = row.get("ticket", "") or "NO-TICKET"
            bucket = grouped.setdefault(
                ticket,
                {
                    "description": row.get("description", ""),
                    "entries": [],
                },
            )
            if not bucket["description"] and row.get("description", ""):
                bucket["description"] = row.get("description", "")

            entries = bucket["entries"]
            assert isinstance(entries, list)
            entries.append(
                {
                    "index": index,
                    "row": row,
                    "work_log": self._normalize_work_log(row),
                }
            )
        return grouped

    def _open_edit_description_window(self, ticket: str) -> None:
        ticket_code = self._normalize_ticket_code(ticket)
        if not ticket_code:
            return

        window = Modal(self, f"Modifica descrizione · {ticket_code}", width=620)
        field_label(window.body, "Descrizione del ticket").pack(anchor="w", pady=(0, 6))
        text = text_area(window.body, height=6, width=70)
        text.pack(fill="x")
        text.insert("1.0", self._find_ticket_description(ticket_code))
        text.focus_set()
        label(window.body, "Vale per tutte le righe di questo ticket.", kind="subtle", bg=C["surface"]).pack(anchor="w", pady=(8, 0))

        def save() -> None:
            self._save_ticket_description(ticket_code, text.get("1.0", "end").strip(), window)

        button(window.footer, "Salva", save, variant="primary").pack(side="right")
        button(window.footer, "Annulla", window.destroy).pack(side="right", padx=(0, 10))
        window.bind("<Control-Return>", lambda _e: save())
        window.recenter()

    def _save_ticket_description(self, ticket_code: str, description: str, window: tk.Toplevel) -> None:
        for row in self.work_logs:
            if row.get("ticket", "") == ticket_code:
                row["description"] = description

        save_work_logs(self.work_logs)
        self._render_worklogs()
        window.destroy()
        self._toast(f"Descrizione di {ticket_code} aggiornata")

    def _open_edit_log_window(self, index: int) -> None:
        if index < 0 or index >= len(self.work_logs):
            return

        row = self.work_logs[index]
        if id(row) in self.rows_in_flight:
            self._toast("Riga in invio al portale: modificala a sync finito", "info")
            return
        kind = self._portal_entry_kind(row)

        window = Modal(self, f"Modifica riga · {row.get('ticket', '')}", width=620)
        body = window.body
        meta = f"{self._format_row_date(row)} · {self._month_label_it_from_label(str(row.get('month', '')))}"
        label(body, meta, kind="muted", bg=C["surface"]).pack(anchor="w", pady=(0, 12))

        field_label(body, "Ore", required=True).pack(anchor="w", pady=(0, 6))
        hours_entry = entry(body, width=14)
        hours_entry.pack(anchor="w")
        hours_entry.insert(0, row.get("working_time", ""))

        field_label(body, "Work log", required=True).pack(anchor="w", pady=(14, 6))
        worklog_text = text_area(body, height=6, width=70)
        worklog_text.pack(fill="x")
        worklog_text.insert("1.0", self._normalize_work_log(row))

        mode_var = tk.StringVar(value="local")
        options_spec: list[tuple[str, str]] = []
        note = ""
        if kind == "entry":
            mode_var.set("update")
            options_spec = [
                ("update", "Aggiorna anche sul portale: la voce esistente viene modificata (nessun duplicato)"),
                ("local", "Correggi solo qui: il portale resta com'è"),
            ]
        elif kind == "off":
            options_spec = [
                ("local", "Correggi solo qui: il portale resta com'è"),
                ("resend", "Rimanda al portale: crea una seconda voce Extra Off (cancella prima quella vecchia dal web)"),
            ]
        elif kind == "web":
            note = (
                "Queste ore sono state registrate dal web o con un messaggio sul ticket: "
                "qui cambia solo la copia locale, sul portale vanno modificate dalla pagina del ticket."
            )

        if options_spec:
            field_label(body, "Questa riga è già sul portale").pack(anchor="w", pady=(16, 6))
            options = tk.Frame(body, bg=C["surface"])
            options.pack(fill="x")
            for value, text in options_spec:
                tk.Radiobutton(
                    options,
                    text=text,
                    value=value,
                    variable=mode_var,
                    font=F["body"],
                    fg=C["text"],
                    bg=C["surface"],
                    activebackground=C["surface"],
                    activeforeground=C["text"],
                    selectcolor=C["raised"],
                    highlightthickness=0,
                    anchor="w",
                    wraplength=560,
                    justify="left",
                ).pack(fill="x", pady=1)
        if note:
            info = tk.Frame(body, bg=C["off_bg"], padx=12, pady=8)
            info.pack(fill="x", pady=(14, 0))
            tk.Label(info, text=note, font=F["body"], bg=C["off_bg"], fg="#c9daff", wraplength=540, justify="left").pack(anchor="w")

        error_label = tk.Label(body, text="", font=F["body"], bg=C["surface"], fg=C["danger"])
        error_label.pack(anchor="w", pady=(8, 0))

        def save() -> None:
            hours_value = hours_entry.get().strip()
            work_log = worklog_text.get("1.0", "end").strip()
            if self._parse_working_time(hours_value) is None:
                error_label.configure(text="Ore non valide. Esempi: 1h, 2.5h, 1d, 1d 4h")
                return
            if not work_log:
                error_label.configure(text="Il work log è obbligatorio.")
                return
            mode = mode_var.get() if kind else "pending"
            self._save_log_edit(index, hours_value, work_log, window, mode=mode)

        button(window.footer, "Salva", save, variant="primary").pack(side="right")
        button(window.footer, "Annulla", window.destroy).pack(side="right", padx=(0, 10))
        window.bind("<Control-Return>", lambda _e: save())
        hours_entry.focus_set()
        window.recenter()

    def _save_log_edit(
        self,
        index: int,
        hours: str,
        work_log: str,
        window: tk.Toplevel,
        *,
        resend: bool = True,
        mode: str | None = None,
    ) -> None:
        """mode: "local" (portal untouched), "update" (next sync updates the portal entry),
        "resend" (next sync creates a new entry, duplicate warning) or "pending" (row not synced yet).
        Without mode, resend=True/False maps to "resend"/"local" (older callers)."""
        if index < 0 or index >= len(self.work_logs):
            return

        parsed = self._parse_working_time(hours)
        if parsed is None:
            messagebox.showerror("Errore", "Ore non valide. Esempi: 1h, 2.5h, 1d, 1d 4h", parent=window)
            return

        if not work_log:
            messagebox.showerror("Errore", "Il work log è obbligatorio.", parent=window)
            return

        row = self.work_logs[index]
        was_synced = self._is_worklog_synced(row)
        if mode is None:
            mode = ("resend" if resend else "local") if was_synced else "pending"

        if mode == "update" and not str(row.get("api_prev_values", "")).strip():
            # Keep the values that are on the portal, to find the entry if its Id is unknown.
            row["api_prev_values"] = json.dumps(
                {"working_time": row.get("working_time", ""), "comment": row.get("comment", "")},
                ensure_ascii=False,
            )

        working_time_label, _hours = parsed
        row["working_time"] = working_time_label
        row["work_log"] = work_log
        row["comment"] = work_log

        if mode == "update":
            row["api_pending_action"] = "update"
            row["api_synced"] = ""
            row["api_synced_at"] = ""
        elif mode == "resend":
            if was_synced:
                # Remember the previous sync so the next send asks about duplicates.
                row["api_resend_of"] = str(row.get("api_synced_at", "")) or datetime.now().astimezone().isoformat(timespec="seconds")
            row["api_synced"] = ""
            row["api_synced_at"] = ""
            row["api_ticket_uuid"] = ""
            row["api_month_displacement"] = ""
            row["api_entry_id"] = ""
            row["api_pending_action"] = ""

        save_work_logs(self.work_logs)
        self._render_worklogs()
        window.destroy()
        messages = {
            "update": "Riga modificata · al prossimo sync aggiorno la voce sul portale",
            "resend": "Riga aggiornata · da sincronizzare come nuova voce",
            "local": "Riga corretta solo in locale",
            "pending": "Riga aggiornata · da sincronizzare",
        }
        self._toast(messages.get(mode, "Riga aggiornata"))

    def _send_as_new_entry(self, row: dict[str, str]) -> None:
        """Give up updating the portal entry: the next sync creates a new one (duplicate warning)."""
        row["api_resend_of"] = str(row.get("api_synced_at", "")) or datetime.now().astimezone().isoformat(timespec="seconds")
        for key in ("api_pending_action", "api_prev_values", "api_entry_id", "api_ticket_uuid", "api_month_displacement"):
            row[key] = ""
        save_work_logs(self.work_logs)
        self._render_worklogs()
        self._toast("La riga verrà inviata come nuova voce", "info")

    def _remove_worklog(self, index: int) -> None:
        if index < 0 or index >= len(self.work_logs):
            return

        row = self.work_logs[index]
        if id(row) in self.rows_in_flight:
            self._toast("Riga in invio al portale: rimuovila a sync finito", "info")
            return
        title = f"{row.get('ticket', '')} · {row.get('working_time', '')} del {self._format_row_date(row)}"
        kind = self._portal_entry_kind(row)

        if kind == "entry":
            answer = messagebox.askyesnocancel(
                "Rimuovi riga",
                f"Rimuovere {title}?\n\n"
                "La voce è anche sul portale.\n\n"
                "Sì = rimuovi qui e cancella la voce dal portale\n"
                "No = rimuovi solo da qui (sul portale resta)\n"
                "Annulla = non fare nulla",
                icon="warning",
            )
            if answer is None:
                return
            if answer:
                self._start_portal_delete(row)
                return
        else:
            question = f"Rimuovere {title}?\n\n"
            if kind == "off":
                question += "È un Extra Off già inviato: verrà rimosso solo da qui, sul portale va cancellato dal web."
            elif kind == "web":
                question += "Le ore sono sul portale come voce web o messaggio: verranno rimosse solo da qui."
            else:
                question += "La riga non è ancora stata inviata al portale."
            if not messagebox.askyesno("Rimuovi riga", question, icon="warning"):
                return

        self.work_logs.pop(index)
        save_work_logs(self.work_logs)
        self._render_worklogs()
        self._toast("Riga rimossa", "info")

    def _start_portal_delete(self, row: dict[str, str]) -> None:
        if self.jobs.running:
            self._toast(f"Attendi: {self.jobs.label} in corso", "info")
            return
        snapshot = dict(row)
        ticket = str(row.get("ticket", ""))
        self.rows_in_flight = {id(row)}

        def worker(_emit: object, _cancel: object) -> str:
            api_log.event(f"=== Cancellazione dal portale: {ticket} · {snapshot.get('log_date', '')} · {snapshot.get('working_time', '')} ===")
            token = self._ensure_api_session()
            ticket_reference = str(snapshot.get("api_ticket_uuid", "")).strip() or ticket
            ticket_uuid = self._resolve_ticket_uuid_cached(token, ticket_reference)
            entry_id = str(snapshot.get("api_entry_id", "")).strip() or self._lookup_entry_id(token, ticket_uuid, snapshot)
            if not entry_id:
                raise RuntimeError("voce non trovata sul portale: cancellala dalla pagina del ticket.")
            self.portal.delete_working_hours(token, entry_id)
            remaining = {str(item.get("Id", "")).upper() for item in self.portal.list_working_hours(token, ticket_uuid)}
            if entry_id.upper() in remaining:
                raise RuntimeError(f"il portale ha risposto ma la voce {entry_id} è ancora presente.")
            api_log.event(f"    ESITO: OK · voce {entry_id} cancellata")
            return entry_id

        def on_finish(result: object, error: BaseException | None) -> None:
            self.rows_in_flight = set()
            self.toast.hide_progress()
            if error is not None:
                api_log.event(f"    ESITO: ERRORE · {error}")
                self._render_worklogs()
                self._notify_error(f"Cancellazione {ticket} non riuscita", error)
                return
            self.work_logs[:] = [item for item in self.work_logs if item is not row]
            save_work_logs(self.work_logs)
            self._render_worklogs()
            self._toast(f"{ticket}: voce cancellata dal portale e rimossa da qui")

        self.jobs.start(f"cancellazione {ticket}", worker, on_event=lambda *_: None, on_finish=on_finish)
        self.toast.progress(f"Cancello la voce {ticket} dal portale…", 0, 1)
        self._render_worklogs()


def run_app() -> None:
    app = LoginWindow()
    app.mainloop()
