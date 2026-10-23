"""Composite widgets for the redesigned UI: toast, progress, menu, segmented bar, month picker, modal."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable

from .theme import C, F, button, icon, icon_button

MONTHS_IT = [
    "Gennaio", "Febbraio", "Marzo", "Aprile", "Maggio", "Giugno",
    "Luglio", "Agosto", "Settembre", "Ottobre", "Novembre", "Dicembre",
]
MONTHS_IT_SHORT = ["Gen", "Feb", "Mar", "Apr", "Mag", "Giu", "Lug", "Ago", "Set", "Ott", "Nov", "Dic"]


def close_on_outside_click(popup: tk.Toplevel) -> None:
    """Grab pointer events so a click anywhere else in the app closes the popup."""

    def on_press(event: tk.Event) -> None:
        x0, y0 = popup.winfo_rootx(), popup.winfo_rooty()
        x1, y1 = x0 + popup.winfo_width(), y0 + popup.winfo_height()
        if not (x0 <= event.x_root < x1 and y0 <= event.y_root < y1):
            popup.destroy()

    def grab() -> None:
        if not popup.winfo_exists():
            return
        try:
            popup.grab_set()
        except tk.TclError:
            popup.after(30, grab)

    popup.bind("<ButtonPress>", on_press, add="+")
    popup.after(20, grab)


class ToastHost:
    """Non-blocking notifications placed bottom-right inside the main window."""

    _STYLES = {
        "success": ("check", C["ok_bg"], C["ok"], C["border_strong"]),
        "info": ("info", C["off_bg"], C["off"], C["border_strong"]),
        "warning": ("warning", C["warn_bg"], C["warn"], C["border_strong"]),
        "error": ("close", C["danger_bg"], C["danger"], "#6b3a35"),
        "progress": ("sync", C["accent_bg"], C["accent_text"], C["border_strong"]),
    }
    _DURATIONS = {"success": 3000, "info": 4000, "warning": 6000, "error": 0, "progress": 0}

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self._frame: tk.Frame | None = None
        self._after_id: str | None = None
        self._progress_frame: tk.Frame | None = None
        self._progress_label: tk.Label | None = None
        self._progress_bar: ttk.Progressbar | None = None
        self._progress_cancel: tk.Button | None = None

    def _toast_y_offset(self) -> int:
        frame = self._progress_frame
        if frame is None or not frame.winfo_exists():
            return -24
        frame.update_idletasks()
        return -24 - frame.winfo_height() - 8

    def show(
        self,
        message: str,
        kind: str = "success",
        *,
        action_text: str | None = None,
        action: Callable[[], object] | None = None,
        duration_ms: int | None = None,
    ) -> None:
        self.hide()
        icon_name, icon_bg, icon_fg, border = self._STYLES[kind]
        frame = tk.Frame(
            self.root,
            bg=C["raised"],
            highlightthickness=1,
            highlightbackground=border,
            padx=12,
            pady=10,
        )
        glyph, glyph_font = icon(icon_name)
        tk.Label(frame, text=glyph, font=glyph_font, bg=icon_bg, fg=icon_fg, width=2, pady=2).pack(side="left")
        tk.Label(
            frame,
            text=message,
            font=F["body"],
            bg=C["raised"],
            fg=C["text"],
            wraplength=380,
            justify="left",
            anchor="w",
        ).pack(side="left", padx=(10, 12))

        if action_text and action:
            def run_action() -> None:
                self.hide()
                action()

            button(frame, action_text, run_action, variant="link", size="sm", parent_bg=C["raised"], bold=True).pack(side="left")

        icon_button(frame, "close", self.hide, parent_bg=C["raised"], tooltip="Chiudi").pack(side="left", padx=(6, 0))
        frame.place(relx=1.0, rely=1.0, x=-24, y=self._toast_y_offset(), anchor="se")
        frame.lift()
        self._frame = frame

        duration = self._DURATIONS[kind] if duration_ms is None else duration_ms
        if duration:
            self._after_id = self.root.after(duration, self.hide)
        self.root.update_idletasks()

    def hide(self) -> None:
        if self._after_id is not None:
            try:
                self.root.after_cancel(self._after_id)
            except tk.TclError:
                pass
            self._after_id = None
        if self._frame is not None:
            try:
                self._frame.destroy()
            except tk.TclError:
                pass
            self._frame = None

    # ------------------------------------------------------------- progress panel
    @property
    def progress_visible(self) -> bool:
        return self._progress_frame is not None and bool(self._progress_frame.winfo_exists())

    def progress(
        self,
        message: str,
        done: int,
        total: int,
        *,
        on_cancel: Callable[[], object] | None = None,
    ) -> None:
        """Show or update the persistent progress panel (bottom-right, below toasts)."""
        frame = self._progress_frame
        if frame is None or not frame.winfo_exists():
            frame = tk.Frame(self.root, bg=C["raised"], highlightthickness=1, highlightbackground=C["border_strong"], padx=12, pady=10)
            top = tk.Frame(frame, bg=C["raised"])
            top.pack(fill="x")
            glyph, glyph_font = icon("sync")
            tk.Label(top, text=glyph, font=glyph_font, bg=C["accent_bg"], fg=C["accent_text"], width=2, pady=2).pack(side="left")
            self._progress_label = tk.Label(top, text="", font=F["body"], bg=C["raised"], fg=C["text"], anchor="w", width=40)
            self._progress_label.pack(side="left", padx=(10, 12))
            self._progress_cancel = button(top, "Annulla", None, variant="link", size="sm", parent_bg=C["raised"], bold=True)
            self._progress_cancel.pack(side="right")
            self._progress_bar = ttk.Progressbar(frame, style="Accent.Horizontal.TProgressbar", mode="determinate", length=380)
            self._progress_bar.pack(fill="x", pady=(8, 0))
            frame.place(relx=1.0, rely=1.0, x=-24, y=-24, anchor="se")
            self._progress_frame = frame
        frame.lift()
        assert self._progress_label and self._progress_bar and self._progress_cancel
        self._progress_label.configure(text=message)
        self._progress_bar.configure(maximum=max(total, 1), value=min(done, max(total, 1)))
        if on_cancel is None:
            self._progress_cancel.pack_forget()
        else:
            self._progress_cancel.configure(command=on_cancel, state="normal", text="Annulla")
            if not self._progress_cancel.winfo_ismapped():
                self._progress_cancel.pack(side="right")
        if self._frame is not None and self._frame.winfo_exists():
            self._frame.place_configure(y=self._toast_y_offset())
            self._frame.lift()

    def progress_cancel_requested(self) -> None:
        if self._progress_cancel is not None and self._progress_cancel.winfo_exists():
            self._progress_cancel.configure(text="Annullo dopo la riga in corso…", state="disabled")

    def hide_progress(self) -> None:
        if self._progress_frame is not None:
            try:
                self._progress_frame.destroy()
            except tk.TclError:
                pass
        self._progress_frame = None
        self._progress_label = None
        self._progress_bar = None
        self._progress_cancel = None
        if self._frame is not None and self._frame.winfo_exists():
            self._frame.place_configure(y=-24)


class DarkMenu(tk.Toplevel):
    """Popup menu drawn with Tk widgets, so it stays dark on Windows too
    (native tk.Menu ignores most colors there)."""

    def __init__(self, root: tk.Misc) -> None:
        super().__init__(root)
        self.withdraw()
        self.overrideredirect(True)
        self.configure(bg=C["border_strong"])
        self.body = tk.Frame(self, bg=C["raised"], padx=4, pady=4)
        self.body.pack(padx=1, pady=1)
        self.bind("<Escape>", lambda _e: self.destroy())
        self.bind("<FocusOut>", lambda _e: self.after(80, self._close_if_unfocused))

    def add_header(self, text: str, *, muted: bool = False) -> None:
        tk.Label(
            self.body,
            text=text,
            font=F["small"] if muted else F["body_bold"],
            bg=C["raised"],
            fg=C["muted"] if muted else C["text"],
            anchor="w",
            padx=12,
        ).pack(fill="x", pady=(4 if not muted else 0, 2))

    def add_command(self, label: str, command: Callable[[], object], *, danger: bool = False, disabled: bool = False) -> None:
        def run() -> None:
            self.destroy()
            command()

        fg = C["danger"] if danger else C["text"]
        item = tk.Button(
            self.body,
            text=label,
            command=run,
            font=F["body"],
            anchor="w",
            bg=C["raised"],
            fg=fg,
            activebackground=C["hover"],
            activeforeground=fg,
            disabledforeground=C["subtle"],
            relief="flat",
            bd=0,
            padx=12,
            pady=6,
            highlightthickness=0,
            cursor="hand2",
        )
        if disabled:
            item.configure(state="disabled", cursor="")
        else:
            item.bind("<Enter>", lambda _e: item.configure(bg=C["hover"]))
            item.bind("<Leave>", lambda _e: item.configure(bg=C["raised"]))
        item.pack(fill="x")

    def add_separator(self) -> None:
        tk.Frame(self.body, bg=C["border_strong"], height=1).pack(fill="x", pady=4)

    def popup_below(self, anchor: tk.Widget, *, align_right: bool = False) -> None:
        self.update_idletasks()
        width = self.winfo_reqwidth()
        height = self.winfo_reqheight()
        x = anchor.winfo_rootx()
        if align_right:
            x = anchor.winfo_rootx() + anchor.winfo_width() - width
        y = anchor.winfo_rooty() + anchor.winfo_height() + 2
        screen_h = anchor.winfo_screenheight()
        if y + height > screen_h - 8:
            y = anchor.winfo_rooty() - height - 2
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        self.deiconify()
        self.lift()
        self.after(10, self.focus_force)
        close_on_outside_click(self)

    def _close_if_unfocused(self) -> None:
        if not self.winfo_exists():
            return
        try:
            focused = self.focus_get()
        except (KeyError, tk.TclError):
            focused = None
        if focused is None or focused.winfo_toplevel() is not self:
            self.destroy()


class SegmentedBar(tk.Canvas):
    """Horizontal bar made of colored segments over a neutral track."""

    def __init__(self, parent: tk.Misc, *, height: int = 10, bg: str) -> None:
        super().__init__(parent, height=height, bg=bg, highlightthickness=0, bd=0)
        self._segments: list[tuple[float, str]] = []
        self.bind("<Configure>", lambda _e: self._redraw())

    def set_segments(self, segments: list[tuple[float, str]]) -> None:
        self._segments = segments
        self._redraw()

    def _redraw(self) -> None:
        self.delete("all")
        width = max(self.winfo_width(), 1)
        height = max(self.winfo_height(), 1)
        self.create_rectangle(0, 0, width, height, fill=C["raised"], outline="")
        x = 0.0
        for fraction, color in self._segments:
            seg_w = max(0.0, min(fraction, 1.0)) * width
            if seg_w <= 0:
                continue
            self.create_rectangle(x, 0, x + seg_w, height, fill=color, outline="")
            x += seg_w


class MonthPickerPopup(tk.Toplevel):
    """Year header + 3x4 month grid. Calls on_pick(year, month)."""

    def __init__(
        self,
        root: tk.Misc,
        anchor: tk.Widget,
        *,
        selected: tuple[int, int],
        latest: tuple[int, int],
        pending_months: set[tuple[int, int]],
        on_pick: Callable[[int, int], None],
    ) -> None:
        super().__init__(root)
        self.overrideredirect(True)
        self.configure(bg=C["border_strong"])
        self.selected = selected
        self.latest = latest
        self.pending_months = pending_months
        self.on_pick = on_pick
        self.year = selected[0]

        self.body = tk.Frame(self, bg=C["raised"], padx=12, pady=12)
        self.body.pack(padx=1, pady=1)
        self._build()

        x = anchor.winfo_rootx()
        y = anchor.winfo_rooty() + anchor.winfo_height() + 4
        self.geometry(f"+{x}+{y}")
        self.bind("<Escape>", lambda _e: self.destroy())
        self.bind("<FocusOut>", self._on_focus_out)
        self.after(10, self.focus_force)
        close_on_outside_click(self)

    def _on_focus_out(self, _e: tk.Event) -> None:
        self.after(80, self._close_if_unfocused)

    def _close_if_unfocused(self) -> None:
        try:
            focused = self.focus_get()
        except (KeyError, tk.TclError):
            focused = None
        if focused is None or focused.winfo_toplevel() is not self:
            self.destroy()

    def _shift_year(self, delta: int) -> None:
        self.year += delta
        self._build()

    def _build(self) -> None:
        for child in self.body.winfo_children():
            child.destroy()

        header = tk.Frame(self.body, bg=C["raised"])
        header.pack(fill="x", pady=(0, 8))
        icon_button(header, "chev_left", lambda: self._shift_year(-1), parent_bg=C["raised"], tooltip="Anno precedente").pack(side="left")
        tk.Label(header, text=str(self.year), font=F["subtitle"], bg=C["raised"], fg=C["text"]).pack(side="left", expand=True)
        next_btn = icon_button(header, "chev_right", lambda: self._shift_year(1), parent_bg=C["raised"], tooltip="Anno successivo")
        if self.year >= self.latest[0]:
            next_btn.configure(state="disabled")
        next_btn.pack(side="right")

        grid = tk.Frame(self.body, bg=C["raised"])
        grid.pack()
        for index, name in enumerate(MONTHS_IT_SHORT):
            month = index + 1
            key = (self.year, month)
            is_selected = key == self.selected
            is_future = key > self.latest
            has_pending = key in self.pending_months
            text = f"{name} •" if has_pending and not is_selected else name
            if is_selected:
                bg, fg, hover = C["accent"], C["on_accent"], C["accent_hover"]
            else:
                bg, fg, hover = C["raised"], (C["subtle"] if is_future else C["text"]), C["hover"]
            btn = tk.Button(
                grid,
                text=text,
                font=F["body_bold"] if is_selected else F["body"],
                width=7,
                pady=5,
                bg=bg,
                fg=C["warn"] if has_pending and not is_selected else fg,
                activebackground=hover,
                activeforeground=fg,
                disabledforeground=C["subtle"],
                relief="flat",
                bd=0,
                highlightthickness=0,
                cursor="hand2",
                command=lambda y=self.year, m=month: self._pick(y, m),
            )
            if is_future:
                btn.configure(state="disabled")
            btn.grid(row=index // 3, column=index % 3, padx=2, pady=2)

        tk.Label(
            self.body,
            text="•  mese con voci da sincronizzare",
            font=F["caption"],
            bg=C["raised"],
            fg=C["muted"],
        ).pack(anchor="w", pady=(8, 0))

    def _pick(self, year: int, month: int) -> None:
        self.destroy()
        self.on_pick(year, month)


class Modal(tk.Toplevel):
    """Dark modal window with header (title + close), body and footer frames."""

    def __init__(self, root: tk.Misc, title: str, *, width: int = 600, height: int | None = None) -> None:
        super().__init__(root)
        self.title(title)
        self.configure(bg=C["surface"])
        self.resizable(False, False)
        self.transient(root)

        header = tk.Frame(self, bg=C["surface"], padx=20, pady=14)
        header.pack(fill="x")
        tk.Label(header, text=title, font=F["title"], bg=C["surface"], fg=C["text"]).pack(side="left")
        icon_button(header, "close", self.destroy, parent_bg=C["surface"], tooltip="Chiudi (Esc)").pack(side="right")
        tk.Frame(self, bg=C["border"], height=1).pack(fill="x")

        self.body = tk.Frame(self, bg=C["surface"], padx=20, pady=18)
        self.body.pack(fill="both", expand=True)

        tk.Frame(self, bg=C["border"], height=1).pack(fill="x")
        self.footer = tk.Frame(self, bg=C["surface"], padx=20, pady=12)
        self.footer.pack(fill="x")

        self.bind("<Escape>", lambda _e: self.destroy())
        self.min_width = width
        self._grab()

    def _grab(self) -> None:
        if not self.winfo_exists():
            return
        try:
            self.grab_set()
        except tk.TclError:
            # Not viewable yet (happens on some window managers): retry shortly.
            self.after(50, self._grab)

    def recenter(self) -> None:
        """Resize to content after the body has been built."""
        self.update_idletasks()
        master = self.master
        width = max(self.winfo_reqwidth(), self.min_width)
        height = self.winfo_reqheight()
        x = master.winfo_rootx() + max((master.winfo_width() - width) // 2, 0)
        y = master.winfo_rooty() + max((master.winfo_height() - height) // 3, 0)
        self.geometry(f"{width}x{height}+{x}+{y}")


def field_label(parent: tk.Misc, text: str, *, required: bool = False, bg: str | None = None) -> tk.Frame:
    frame = tk.Frame(parent, bg=bg or C["surface"])
    tk.Label(frame, text=text, font=F["body"], bg=bg or C["surface"], fg=C["muted"]).pack(side="left")
    if required:
        tk.Label(frame, text=" *", font=F["body"], bg=bg or C["surface"], fg=C["accent_text"]).pack(side="left")
    return frame


class Segmented(tk.Frame):
    """Segmented control bound to a StringVar: [(value, label), ...]."""

    def __init__(self, parent: tk.Misc, variable: tk.StringVar, options: list[tuple[str, str]], *, bg: str) -> None:
        super().__init__(parent, bg=C["bg_app"], highlightthickness=1, highlightbackground=C["border"], padx=3, pady=3)
        self.variable = variable
        self.buttons: dict[str, tk.Button] = {}
        for column, (value, text) in enumerate(options):
            btn = tk.Button(
                self,
                text=text,
                font=F["body"],
                relief="flat",
                bd=0,
                pady=6,
                cursor="hand2",
                highlightthickness=0,
                command=lambda v=value: self.variable.set(v),
            )
            btn.grid(row=0, column=column, sticky="ew", padx=1)
            self.columnconfigure(column, weight=1, uniform="seg")
            self.buttons[value] = btn
        variable.trace_add("write", lambda *_: self._refresh())
        self._refresh()

    def _refresh(self) -> None:
        current = self.variable.get()
        for value, btn in self.buttons.items():
            if value == current:
                btn.configure(bg=C["accent"], fg=C["on_accent"], activebackground=C["accent_hover"], activeforeground=C["on_accent"], font=F["body_bold"])
            else:
                btn.configure(bg=C["bg_app"], fg=C["text"], activebackground=C["hover"], activeforeground=C["text"], font=F["body"])


class ChoiceChips(tk.Frame):
    """Row of selectable chips bound to a StringVar."""

    def __init__(self, parent: tk.Misc, variable: tk.StringVar, options: list[tuple[str, str]], *, bg: str) -> None:
        super().__init__(parent, bg=bg)
        self.variable = variable
        self.buttons: dict[str, tk.Button] = {}
        for value, text in options:
            btn = tk.Button(
                self,
                text=text,
                font=F["body"],
                relief="flat",
                bd=0,
                padx=12,
                pady=6,
                cursor="hand2",
                highlightthickness=1,
                command=lambda v=value: self.variable.set(v),
            )
            btn.pack(side="left", padx=(0, 8))
            self.buttons[value] = btn
        variable.trace_add("write", lambda *_: self._refresh())
        self._refresh()

    def _refresh(self) -> None:
        current = self.variable.get()
        for value, btn in self.buttons.items():
            if value == current:
                btn.configure(bg=C["accent_bg"], fg="#ffb27a", highlightbackground=C["accent"], activebackground=C["accent_bg"], font=F["body_bold"])
            else:
                btn.configure(bg=C["raised"], fg=C["text"], highlightbackground=C["border"], activebackground=C["hover"], font=F["body"])
