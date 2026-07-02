from __future__ import annotations

import tkinter as tk
import webbrowser
from tkinter import messagebox

try:
    from tkinterweb import HtmlFrame
except ImportError:
    HtmlFrame = None

from .config import load_credentials, save_credentials


class LoginWindow(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Login Time")
        self.geometry("980x760")
        self.configure(bg="#1f1f22")
        self.resizable(False, False)

        self.ticket_view: HtmlFrame | None = None
        self.ticket_hint: tk.Label | None = None
        self.last_ticket_url: str | None = None
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

        self.ticket_view = None
        self.ticket_hint = None
        self.last_ticket_url = None

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
            text="Ticket Window",
            font=("Segoe UI", 12, "bold"),
            fg="#f4f4f6",
            bg="#14161b",
        )
        ticket_title.pack(anchor="w", padx=12, pady=(10, 8))

        ticket_actions = tk.Frame(ticket_panel, bg="#14161b")
        ticket_actions.pack(fill="x", padx=10, pady=(0, 8))

        open_browser_btn = tk.Button(
            ticket_actions,
            text="Open current ticket in browser",
            font=("Segoe UI", 9, "bold"),
            bg="#3a3a40",
            fg="#f4f4f6",
            activebackground="#4a4a50",
            activeforeground="#ffffff",
            relief="flat",
            padx=12,
            pady=6,
            command=self._open_last_ticket_in_browser,
        )
        open_browser_btn.pack(side="right")

        if HtmlFrame is None:
            self.ticket_hint = tk.Label(
                ticket_panel,
                text="Viewer interno non disponibile. Installa: pip install -r requirements.txt",
                font=("Segoe UI", 10),
                fg="#bcbcc7",
                bg="#14161b",
            )
            self.ticket_hint.pack(anchor="w", padx=12, pady=(0, 12))
        else:
            self.ticket_view = HtmlFrame(ticket_panel, messages_enabled=False)
            self.ticket_view.pack(fill="both", expand=True, padx=10, pady=(0, 10))

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
        window.geometry("420x220")
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

        open_in_browser = tk.BooleanVar(value=True)
        browser_check = tk.Checkbutton(
            window,
            text="Open in browser (use existing logged session)",
            variable=open_in_browser,
            onvalue=True,
            offvalue=False,
            font=("Segoe UI", 10),
            fg="#f4f4f6",
            bg="#2b2b30",
            activebackground="#2b2b30",
            activeforeground="#f4f4f6",
            selectcolor="#2b2b30",
        )
        browser_check.pack(anchor="w", padx=16, pady=(14, 0))

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
            command=lambda: self._open_ticket_link(ticket_entry.get(), window, open_in_browser.get()),
        )
        open_btn.pack(anchor="e", padx=20, pady=(16, 0))

    def _open_ticket_link(self, ticket_value: str, window: tk.Toplevel, open_in_browser: bool) -> None:
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
        if open_in_browser:
            webbrowser.open(url)
            window.destroy()
            return

        self._load_ticket_in_app(url)
        window.destroy()

    def _load_ticket_in_app(self, url: str) -> None:
        self.last_ticket_url = url

        if self.ticket_view is None:
            webbrowser.open(url)
            messagebox.showinfo(
                "Viewer not available",
                "Viewer interno non disponibile: il ticket e' stato aperto nel browser.",
            )
            return

        try:
            self.ticket_view.load_website(url)
            messagebox.showinfo(
                "Internal viewer",
                "Se il login web interno mostra errori, usa 'Open current ticket in browser'.",
            )
        except Exception:
            webbrowser.open(url)
            messagebox.showinfo(
                "Viewer fallback",
                "La pagina non e' stata caricata nel viewer interno. Ticket aperto nel browser.",
            )

    def _open_last_ticket_in_browser(self) -> None:
        if not self.last_ticket_url:
            messagebox.showinfo("No ticket", "Apri prima un ticket, poi usa questo pulsante.")
            return

        webbrowser.open(self.last_ticket_url)


def run_app() -> None:
    app = LoginWindow()
    app.mainloop()
