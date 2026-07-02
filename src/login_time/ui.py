from __future__ import annotations

from datetime import datetime
import re
import tkinter as tk
import webbrowser
from tkinter import messagebox

from .config import load_credentials, load_work_logs, save_credentials, save_work_logs


class LoginWindow(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Login Time")
        self.geometry("980x760")
        self.configure(bg="#1f1f22")
        self.resizable(False, False)

        self.work_logs: list[dict[str, str]] = load_work_logs()
        self.worklog_rows: tk.Frame | None = None
        self.worklog_canvas: tk.Canvas | None = None
        self.worklog_canvas_window: int | None = None
        self.credentials = load_credentials()
        self._build_login_ui()

    def _clear_window(self) -> None:
        for child in self.winfo_children():
            child.destroy()

    def _build_login_ui(self) -> None:
        self._clear_window()

        card = tk.Frame(self, bg="#2b2b30", padx=36, pady=36)
        card.place(relx=0.5, rely=0.5, anchor="center")

        title = tk.Label(
            card,
            text="QUIXANT",
            font=("Segoe UI", 28, "bold"),
            fg="#ff6a00",
            bg="#2b2b30",
        )
        title.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 18))

        subtitle = tk.Label(
            card,
            text="Log in",
            font=("Segoe UI", 20),
            fg="#f4f4f6",
            bg="#2b2b30",
        )
        subtitle.grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 18))

        user_label = tk.Label(
            card,
            text="Username",
            font=("Segoe UI", 12),
            fg="#e9e9ee",
            bg="#2b2b30",
        )
        user_label.grid(row=2, column=0, sticky="w")

        self.user_entry = tk.Entry(card, width=42, font=("Segoe UI", 12))
        self.user_entry.grid(row=3, column=0, columnspan=2, pady=(6, 16))
        self.user_entry.insert(0, self.credentials["username"])

        pass_label = tk.Label(
            card,
            text="Password",
            font=("Segoe UI", 12),
            fg="#e9e9ee",
            bg="#2b2b30",
        )
        pass_label.grid(row=4, column=0, sticky="w")

        self.pass_entry = tk.Entry(card, width=42, font=("Segoe UI", 12), show="*")
        self.pass_entry.grid(row=5, column=0, columnspan=2, pady=(6, 20))
        self.pass_entry.insert(0, self.credentials["password"])

        login_btn = tk.Button(
            card,
            text="LOG IN",
            font=("Segoe UI", 11, "bold"),
            bg="#ff6a00",
            fg="#ffffff",
            activebackground="#e65f00",
            activeforeground="#ffffff",
            relief="flat",
            padx=22,
            pady=8,
            command=self._handle_login,
        )
        login_btn.grid(row=6, column=0, sticky="w", pady=(0, 8))

        save_btn = tk.Button(
            card,
            text="Save as default",
            font=("Segoe UI", 10),
            bg="#3a3a40",
            fg="#f4f4f6",
            relief="flat",
            padx=16,
            pady=8,
            command=self._save_defaults,
        )
        save_btn.grid(row=6, column=1, sticky="e", pady=(0, 8))

    def _save_defaults(self) -> None:
        username = self.user_entry.get().strip()
        password = self.pass_entry.get().strip()

        if not username or not password:
            messagebox.showerror("Error", "Username and password are required.")
            return

        save_credentials(username, password)
        self.credentials = {"username": username, "password": password}
        messagebox.showinfo("Saved", "Default credentials updated.")

    def _handle_login(self) -> None:
        username = self.user_entry.get().strip()
        password = self.pass_entry.get().strip()

        if username == self.credentials["username"] and password == self.credentials["password"]:
            messagebox.showinfo("Success", "Login done")
            self._show_dashboard(username)
            return

        messagebox.showerror("Error", "Invalid credentials.")

    def _show_dashboard(self, username: str) -> None:
        self._clear_window()

        dashboard = tk.Frame(self, bg="#1f1f22", padx=28, pady=28)
        dashboard.pack(fill="both", expand=True)

        topbar = tk.Frame(dashboard, bg="#1f1f22")
        topbar.pack(fill="x", anchor="n")

        search_entry = tk.Entry(topbar, font=("Segoe UI", 12), width=34)
        search_entry.insert(0, "Search")
        search_entry.pack(side="right", padx=(0, 12), pady=(0, 18))

        profile_btn = tk.Button(
            topbar,
            text="MP",
            font=("Segoe UI", 12, "bold"),
            bg="#ff6a00",
            fg="#ffffff",
            activebackground="#e65f00",
            activeforeground="#ffffff",
            relief="flat",
            width=4,
            command=lambda: self._show_profile_menu(profile_btn),
        )
        profile_btn.pack(side="right", pady=(0, 18))

        ticket_btn = tk.Button(
            topbar,
            text="Open Ticket",
            font=("Segoe UI", 10, "bold"),
            bg="#3a3a40",
            fg="#f4f4f6",
            activebackground="#4a4a50",
            activeforeground="#ffffff",
            relief="flat",
            padx=14,
            pady=8,
            command=self._open_ticket_window,
        )
        ticket_btn.pack(side="right", padx=(0, 12), pady=(0, 18))

        monthly_report_btn = tk.Button(
            topbar,
            text="Monthly Report",
            font=("Segoe UI", 10, "bold"),
            bg="#3a3a40",
            fg="#f4f4f6",
            activebackground="#4a4a50",
            activeforeground="#ffffff",
            relief="flat",
            padx=14,
            pady=8,
            command=self._open_monthly_report,
        )
        monthly_report_btn.pack(side="right", padx=(0, 12), pady=(0, 18))

        first_name = username.split("@")[0].split(".")[0].capitalize() if username else "Marco"
        welcome = tk.Label(
            dashboard,
            text=f"Welcome {first_name}",
            font=("Segoe UI", 36, "bold"),
            fg="#f4f4f6",
            bg="#1f1f22",
        )
        welcome.pack(anchor="nw")

        info = tk.Label(
            dashboard,
            text="Dashboard ready",
            font=("Segoe UI", 16),
            fg="#bcbcc7",
            bg="#1f1f22",
        )
        info.pack(anchor="nw", pady=(18, 0))

        ticket_panel = tk.Frame(dashboard, bg="#14161b", highlightthickness=1, highlightbackground="#2c2f36")
        ticket_panel.pack(fill="both", expand=True, pady=(22, 0))

        ticket_title = tk.Label(
            ticket_panel,
            text="Log working time (local)",
            font=("Segoe UI", 12, "bold"),
            fg="#f4f4f6",
            bg="#14161b",
        )
        ticket_title.pack(anchor="w", padx=12, pady=(10, 8))

        ticket_actions = tk.Frame(ticket_panel, bg="#14161b")
        ticket_actions.pack(fill="x", padx=10, pady=(0, 8))

        add_worklog_btn = tk.Button(
            ticket_actions,
            text="+ Log new working time",
            font=("Segoe UI", 10),
            bg="#14161b",
            fg="#f4f4f6",
            activebackground="#1d2129",
            activeforeground="#ffffff",
            relief="flat",
            padx=4,
            pady=4,
            command=self._open_worklog_window,
        )
        add_worklog_btn.pack(side="left")

        line = tk.Frame(ticket_panel, bg="#ff6a00", height=1)
        line.pack(fill="x", padx=10, pady=(6, 10))

        scroll_host = tk.Frame(ticket_panel, bg="#14161b")
        scroll_host.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        self.worklog_canvas = tk.Canvas(scroll_host, bg="#14161b", highlightthickness=0)
        self.worklog_canvas.pack(side="left", fill="both", expand=True)

        scrollbar = tk.Scrollbar(scroll_host, orient="vertical", command=self.worklog_canvas.yview)
        scrollbar.pack(side="right", fill="y")
        self.worklog_canvas.configure(yscrollcommand=scrollbar.set)

        self.worklog_rows = tk.Frame(self.worklog_canvas, bg="#14161b")
        self.worklog_canvas_window = self.worklog_canvas.create_window((0, 0), window=self.worklog_rows, anchor="nw")

        self.worklog_rows.bind(
            "<Configure>",
            lambda _event: self.worklog_canvas.configure(scrollregion=self.worklog_canvas.bbox("all")),
        )
        self.worklog_canvas.bind(
            "<Configure>",
            lambda event: self.worklog_canvas.itemconfig(self.worklog_canvas_window, width=event.width),
        )
        self._render_worklogs()

    def _show_profile_menu(self, anchor: tk.Widget) -> None:
        menu = tk.Menu(self, tearoff=0, bg="#2b2b30", fg="#f4f4f6", activebackground="#3a3a40")
        menu.add_command(label="My Profile")
        menu.add_command(label="Company Profiles")
        menu.add_command(label="Legal Documents")
        menu.add_command(label="My Subscriptions")
        menu.add_separator()
        menu.add_command(label="Logout", command=self._logout)

        x = anchor.winfo_rootx()
        y = anchor.winfo_rooty() + anchor.winfo_height()
        menu.tk_popup(x, y)

    def _logout(self) -> None:
        messagebox.showinfo("Logout", "Logout done")
        self._build_login_ui()

    def _open_ticket_window(self) -> None:
        window = tk.Toplevel(self)
        window.title("Open Ticket")
        window.geometry("460x330")
        window.configure(bg="#2b2b30")
        window.resizable(False, False)
        window.transient(self)
        window.grab_set()

        label = tk.Label(
            window,
            text="Ticket ID",
            font=("Segoe UI", 12),
            fg="#f4f4f6",
            bg="#2b2b30",
        )
        label.pack(anchor="w", padx=20, pady=(18, 8))

        ticket_entry = tk.Entry(window, width=34, font=("Segoe UI", 12))
        ticket_entry.pack(anchor="w", padx=20)
        ticket_entry.insert(0, "QUIX-")
        ticket_entry.focus_set()

        creds_title = tk.Label(
            window,
            text="Default credentials",
            font=("Segoe UI", 10, "bold"),
            fg="#f4f4f6",
            bg="#2b2b30",
        )
        creds_title.pack(anchor="w", padx=20, pady=(12, 4))

        browser_user = tk.Entry(window, width=34, font=("Segoe UI", 10))
        browser_user.pack(anchor="w", padx=20)
        browser_user.insert(0, self.credentials["username"])

        browser_pass = tk.Entry(window, width=34, font=("Segoe UI", 10), show="*")
        browser_pass.pack(anchor="w", padx=20, pady=(6, 0))
        browser_pass.insert(0, self.credentials["password"])

        copy_btn = tk.Button(
            window,
            text="Copy credentials",
            font=("Segoe UI", 9, "bold"),
            bg="#3a3a40",
            fg="#f4f4f6",
            activebackground="#4a4a50",
            activeforeground="#ffffff",
            relief="flat",
            padx=10,
            pady=6,
            command=lambda: self._copy_credentials(browser_user.get().strip(), browser_pass.get().strip()),
        )
        copy_btn.pack(anchor="w", padx=20, pady=(8, 0))

        open_btn = tk.Button(
            window,
            text="Open Link",
            font=("Segoe UI", 10, "bold"),
            bg="#ff6a00",
            fg="#ffffff",
            activebackground="#e65f00",
            activeforeground="#ffffff",
            relief="flat",
            padx=14,
            pady=8,
            command=lambda: self._open_ticket_link(ticket_entry.get(), window),
        )
        open_btn.pack(anchor="e", padx=20, pady=(20, 0))

    def _open_worklog_window(self) -> None:
        window = tk.Toplevel(self)
        window.title("Log working time")
        window.geometry("620x470")
        window.configure(bg="#2b2b30")
        window.resizable(False, False)
        window.transient(self)
        window.grab_set()

        tk.Label(window, text="Ticket", font=("Segoe UI", 11), fg="#f4f4f6", bg="#2b2b30").pack(anchor="w", padx=20, pady=(16, 6))
        ticket_entry = tk.Entry(window, width=40, font=("Segoe UI", 11))
        ticket_entry.pack(anchor="w", padx=20)
        ticket_entry.insert(0, "QUIX-")

        tk.Label(window, text="Working time", font=("Segoe UI", 11), fg="#f4f4f6", bg="#2b2b30").pack(anchor="w", padx=20, pady=(12, 6))
        hours_entry = tk.Entry(window, width=14, font=("Segoe UI", 11))
        hours_entry.pack(anchor="w", padx=20)
        hours_entry.insert(0, "1h")

        tk.Label(window, text="Description", font=("Segoe UI", 11), fg="#f4f4f6", bg="#2b2b30").pack(anchor="w", padx=20, pady=(12, 6))
        description_text = tk.Text(window, width=70, height=4, font=("Segoe UI", 10), wrap="word")
        description_text.pack(anchor="w", padx=20)

        def prefill_description(*_: object) -> None:
            ticket_code = self._normalize_ticket_code(ticket_entry.get().strip())
            if not ticket_code:
                return

            existing_description = self._find_ticket_description(ticket_code)
            if not existing_description:
                return

            if description_text.get("1.0", "end").strip():
                return

            description_text.insert("1.0", existing_description)

        ticket_entry.bind("<FocusOut>", prefill_description)

        tk.Label(window, text="Comment", font=("Segoe UI", 11), fg="#f4f4f6", bg="#2b2b30").pack(anchor="w", padx=20, pady=(12, 6))
        comment_text = tk.Text(window, width=55, height=6, font=("Segoe UI", 10), wrap="word")
        comment_text.pack(anchor="w", padx=20)

        save_btn = tk.Button(
            window,
            text="Save log",
            font=("Segoe UI", 10, "bold"),
            bg="#ff6a00",
            fg="#ffffff",
            activebackground="#e65f00",
            activeforeground="#ffffff",
            relief="flat",
            padx=14,
            pady=8,
            command=lambda: self._save_worklog(
                ticket_entry.get().strip(),
                hours_entry.get().strip(),
                description_text.get("1.0", "end").strip(),
                comment_text.get("1.0", "end").strip(),
                window,
            ),
        )
        save_btn.pack(anchor="e", padx=20, pady=(16, 0))

    def _copy_credentials(self, username: str, password: str) -> None:
        if not username or not password:
            messagebox.showerror("Error", "Username and password are required.")
            return

        self.clipboard_clear()
        self.clipboard_append(f"{username}\n{password}")
        messagebox.showinfo("Copied", "Credentials copied to clipboard (username then password).")

    def _open_ticket_link(self, ticket_value: str, window: tk.Toplevel) -> None:
        ticket = ticket_value.strip().upper()
        if not ticket:
            messagebox.showerror("Error", "Insert a ticket code.")
            return

        if not ticket.startswith("QUIX-"):
            ticket = f"QUIX-{ticket}"

        if ticket == "QUIX-":
            messagebox.showerror("Error", "Insert a valid ticket code.")
            return

        url = f"https://support.quixant.com/ticket/Edit/{ticket}"
        webbrowser.open(url)
        window.destroy()

    def _save_worklog(self, ticket: str, hours: str, description: str, comment: str, window: tk.Toplevel) -> None:
        ticket_code = self._normalize_ticket_code(ticket)
        if not ticket_code:
            messagebox.showerror("Error", "Ticket is required.")
            return
        if ticket_code == "QUIX-":
            messagebox.showerror("Error", "Insert a valid ticket code.")
            return

        parsed = self._parse_working_time(hours)
        if parsed is None:
            messagebox.showerror(
                "Error",
                "Working time non valido. Esempi: 1h, 2.5h, 1d, 1d 4h",
            )
            return
        working_time_label, _hours_value = parsed

        if not comment:
            messagebox.showerror("Error", "Comment is required.")
            return

        ticket_description = description.strip() or self._find_ticket_description(ticket_code)

        item = {
            "working_time": working_time_label,
            "month": datetime.now().strftime("%B %Y"),
            "work_log": comment,
            "ticket": ticket_code,
            "comment": comment,
            "description": ticket_description,
        }
        self.work_logs.insert(0, item)
        save_work_logs(self.work_logs)
        self._render_worklogs()
        window.destroy()
        messagebox.showinfo("Saved", "Working time logged locally.")

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

    def _render_worklogs(self) -> None:
        if self.worklog_rows is None:
            return

        for child in self.worklog_rows.winfo_children():
            child.destroy()

        if not self.work_logs:
            empty = tk.Label(
                self.worklog_rows,
                text="No working hours logged!",
                font=("Segoe UI", 14),
                fg="#f4f4f6",
                bg="#14161b",
            )
            empty.pack(anchor="center", pady=(28, 0))
            return

        grouped_logs = self._group_worklogs_by_ticket()

        for ticket, bundle in grouped_logs.items():
            card = tk.Frame(self.worklog_rows, bg="#171a20", highlightthickness=1, highlightbackground="#2c2f36")
            card.pack(fill="x", pady=(0, 10))

            top = tk.Frame(card, bg="#171a20")
            top.pack(fill="x", padx=10, pady=(10, 6))

            title_block = tk.Frame(top, bg="#171a20")
            title_block.pack(side="left", fill="x", expand=True)

            tk.Label(title_block, text=ticket, font=("Segoe UI", 12, "bold"), fg="#f4f4f6", bg="#171a20").pack(anchor="w")
            tk.Label(
                title_block,
                text=bundle["description"] or "No description",
                font=("Segoe UI", 10),
                fg="#bcbcc7",
                bg="#171a20",
                wraplength=520,
                justify="left",
            ).pack(anchor="w", pady=(2, 0))

            ticket_actions = tk.Frame(top, bg="#171a20")
            ticket_actions.pack(side="right")

            tk.Button(
                ticket_actions,
                text="Open ticket",
                font=("Segoe UI", 9),
                bg="#3a3a40",
                fg="#f4f4f6",
                activebackground="#4a4a50",
                activeforeground="#ffffff",
                relief="flat",
                padx=8,
                pady=3,
                command=lambda ticket_code=ticket: self._open_ticket_for_row(ticket_code),
            ).pack(side="left", padx=(0, 4))

            tk.Button(
                ticket_actions,
                text="Copy description",
                font=("Segoe UI", 9),
                bg="#3a3a40",
                fg="#f4f4f6",
                activebackground="#4a4a50",
                activeforeground="#ffffff",
                relief="flat",
                padx=8,
                pady=3,
                command=lambda text=bundle["description"]: self._copy_text_direct(text),
            ).pack(side="left")

            header = tk.Frame(card, bg="#171a20")
            header.pack(fill="x", padx=10, pady=(4, 0))
            tk.Label(header, text="Working time", font=("Segoe UI", 10, "bold"), fg="#f4f4f6", bg="#171a20", width=14, anchor="w").pack(side="left")
            tk.Label(header, text="Month", font=("Segoe UI", 10, "bold"), fg="#f4f4f6", bg="#171a20", width=14, anchor="w").pack(side="left")
            tk.Label(header, text="Work log", font=("Segoe UI", 10, "bold"), fg="#f4f4f6", bg="#171a20", anchor="w").pack(side="left", fill="x", expand=True)

            divider = tk.Frame(card, bg="#ff6a00", height=1)
            divider.pack(fill="x", padx=10, pady=(6, 8))

            for entry in bundle["entries"]:
                row = entry["row"]
                row_frame = tk.Frame(card, bg="#171a20")
                row_frame.pack(fill="x", padx=10, pady=(0, 6))

                row_actions = tk.Frame(row_frame, bg="#171a20")
                row_actions.pack(side="right")

                tk.Button(
                    row_actions,
                    text="Copy work log",
                    font=("Segoe UI", 9),
                    bg="#3a3a40",
                    fg="#f4f4f6",
                    activebackground="#4a4a50",
                    activeforeground="#ffffff",
                    relief="flat",
                    padx=8,
                    pady=3,
                    command=lambda text=entry["work_log"]: self._copy_text_direct(text),
                ).pack(side="left", padx=(0, 4))

                tk.Button(
                    row_actions,
                    text="Copy working time",
                    font=("Segoe UI", 9),
                    bg="#3a3a40",
                    fg="#f4f4f6",
                    activebackground="#4a4a50",
                    activeforeground="#ffffff",
                    relief="flat",
                    padx=8,
                    pady=3,
                    command=lambda text=row["working_time"]: self._copy_text_direct(text),
                ).pack(side="left", padx=(0, 4))

                tk.Button(
                    row_actions,
                    text="Remove",
                    font=("Segoe UI", 9),
                    bg="#3a3a40",
                    fg="#f4f4f6",
                    activebackground="#4a4a50",
                    activeforeground="#ffffff",
                    relief="flat",
                    padx=8,
                    pady=3,
                    command=lambda i=entry["index"]: self._remove_worklog(i),
                ).pack(side="left")

                tk.Label(row_frame, text=row["working_time"], font=("Segoe UI", 10), fg="#e7e7ee", bg="#171a20", width=14, anchor="w").pack(side="left")
                tk.Label(row_frame, text=row["month"], font=("Segoe UI", 10), fg="#e7e7ee", bg="#171a20", width=14, anchor="w").pack(side="left")
                tk.Label(row_frame, text=entry["work_log"], font=("Segoe UI", 10), fg="#e7e7ee", bg="#171a20", anchor="w").pack(side="left", fill="x", expand=True)

    def _open_ticket_for_row(self, ticket: str) -> None:
        ticket_code = ticket.strip().upper()
        if not ticket_code.startswith("QUIX-"):
            ticket_code = f"QUIX-{ticket_code}"
        webbrowser.open(f"https://support.quixant.com/ticket/Edit/{ticket_code}")

    def _open_monthly_report(self) -> None:
        webbrowser.open("https://support.quixant.com/admin/MonthlyReport")

    def _copy_text_direct(self, value: str) -> None:
        self.clipboard_clear()
        self.clipboard_append(value)

    def _normalize_ticket_code(self, ticket: str) -> str:
        ticket_code = ticket.upper().strip()
        if not ticket_code:
            return ""
        if not ticket_code.startswith("QUIX-"):
            ticket_code = f"QUIX-{ticket_code}"
        return ticket_code

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

    def _group_worklogs_by_ticket(self) -> dict[str, dict[str, object]]:
        grouped: dict[str, dict[str, object]] = {}
        for index, row in enumerate(self.work_logs[:12]):
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

    def _remove_worklog(self, index: int) -> None:
        if index < 0 or index >= len(self.work_logs):
            return

        self.work_logs.pop(index)
        save_work_logs(self.work_logs)
        self._render_worklogs()

        messagebox.showinfo("Removed", "Working time log removed.")


def run_app() -> None:
    app = LoginWindow()
    app.mainloop()
