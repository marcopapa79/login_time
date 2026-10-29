"""Design tokens and small widget factories for the login_time UI.

Everything visual lives here so ui.py only describes layout and behaviour.
Values mirror the "Design tokens + mappa Tkinter" board of the redesign.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk
from typing import Callable

# --------------------------------------------------------------------------- colors
C = {
    "bg_app": "#17181c",
    "surface": "#202227",
    "raised": "#2a2d34",
    "hover": "#343842",
    "border": "#33363e",
    "border_strong": "#3f434d",
    "text": "#f4f4f6",
    "muted": "#a9abb6",
    "subtle": "#8a8d99",
    "accent": "#ff6a00",
    "accent_hover": "#e65f00",
    "on_accent": "#141414",
    "accent_text": "#ff8a3d",
    "accent_bg": "#3a2a1f",
    "ok": "#6fcf7a",
    "ok_bg": "#1f3326",
    "warn": "#e5c35c",
    "warn_bg": "#3a3220",
    "danger": "#ff8f80",
    "danger_bg": "#3d2220",
    "off": "#9ec0ff",
    "off_bg": "#2a2f3d",
    "pending_row": "#23221f",
    "overlay": "#0e0f12",
}

# --------------------------------------------------------------------------- fonts
FAMILY = "Segoe UI"
FAMILY_SEMIBOLD = "Segoe UI Semibold"
MONO = "Consolas"

F = {
    "kpi": (FAMILY_SEMIBOLD, 21),
    "brand": (FAMILY, 13, "bold"),
    "title": (FAMILY_SEMIBOLD, 13),
    "subtitle": (FAMILY_SEMIBOLD, 12),
    "body": (FAMILY, 10),
    "body_bold": (FAMILY, 10, "bold"),
    "ticket": (FAMILY, 11, "bold"),
    "small": (FAMILY, 9),
    "small_bold": (FAMILY, 9, "bold"),
    "caption": (FAMILY, 8),
    "mono": (MONO, 10),
}

# --------------------------------------------------------------------------- icons
# Segoe Fluent Icons (Win 11) / Segoe MDL2 Assets (Win 10) share code points.
_ICON_GLYPHS = {
    "copy": ("", "⎘"),
    "edit": ("", "✎"),
    "more": ("", "⋯"),
    "sync": ("", "⟳"),
    "open": ("", "↗"),
    "chev_down": ("", "▾"),
    "chev_right": ("", "▸"),
    "chev_left": ("", "◂"),
    "search": ("", "⌕"),
    "check": ("", "✓"),
    "close": ("", "✕"),
    "warning": ("", "!"),
    "lock": ("", "🔒"),
    "info": ("", "i"),
    "eye": ("", "◉"),
    "delete": ("", "✕"),
    "chat": ("\ue8bd", "✉"),
    "refresh": ("\ue72c", "⟳"),
}

_icon_font: tuple | None = None


def init_fonts(root: tk.Misc) -> None:
    """Pick installed fonts; must run after the Tk root exists."""
    global _icon_font, FAMILY_SEMIBOLD
    families = set(tkfont.families(root))
    for candidate in ("Segoe Fluent Icons", "Segoe MDL2 Assets"):
        if candidate in families:
            _icon_font = (candidate, 10)
            break
    if FAMILY_SEMIBOLD not in families:
        FAMILY_SEMIBOLD = FAMILY
        for key in ("kpi", "title", "subtitle"):
            size = F[key][1]
            F[key] = (FAMILY, size, "bold")


def icon(name: str) -> tuple[str, tuple]:
    """Return (text, font) for an icon, falling back to plain unicode."""
    glyph, fallback = _ICON_GLYPHS[name]
    if _icon_font is not None:
        return glyph, _icon_font
    return fallback, (FAMILY, 11)


# --------------------------------------------------------------------------- ttk
def apply_ttk_style(root: tk.Misc) -> None:
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    style.configure(
        "TCombobox",
        fieldbackground=C["raised"],
        background=C["raised"],
        foreground=C["text"],
        arrowcolor=C["muted"],
        bordercolor=C["border"],
        lightcolor=C["raised"],
        darkcolor=C["raised"],
        insertcolor=C["text"],
        padding=(8, 6),
    )
    style.map(
        "TCombobox",
        fieldbackground=[("readonly", C["raised"]), ("disabled", C["surface"])],
        foreground=[("disabled", C["muted"])],
        bordercolor=[("focus", C["accent"])],
        selectbackground=[("!focus", C["raised"])],
        selectforeground=[("!focus", C["text"])],
    )
    root.option_add("*TCombobox*Listbox.background", C["raised"])
    root.option_add("*TCombobox*Listbox.foreground", C["text"])
    root.option_add("*TCombobox*Listbox.selectBackground", C["accent"])
    root.option_add("*TCombobox*Listbox.selectForeground", C["on_accent"])
    root.option_add("*TCombobox*Listbox.font", F["body"])

    style.configure(
        "Vertical.TScrollbar",
        background=C["raised"],
        troughcolor=C["bg_app"],
        bordercolor=C["bg_app"],
        arrowcolor=C["muted"],
        lightcolor=C["raised"],
        darkcolor=C["raised"],
        gripcount=0,
    )
    style.map("Vertical.TScrollbar", background=[("active", C["hover"])])

    style.configure(
        "Accent.Horizontal.TProgressbar",
        troughcolor=C["bg_app"],
        background=C["accent"],
        bordercolor=C["bg_app"],
        lightcolor=C["accent"],
        darkcolor=C["accent"],
        thickness=4,
    )


# --------------------------------------------------------------------------- factories
_BUTTON_VARIANTS = {
    # variant: (bg, fg, hover_bg, border)
    "primary": (C["accent"], C["on_accent"], C["accent_hover"], None),
    "secondary": (C["raised"], C["text"], C["hover"], C["border"]),
    "outline": (None, C["accent_text"], C["accent_bg"], C["accent"]),
    "ghost": (None, C["muted"], C["hover"], None),
    "link": (None, C["accent_text"], None, None),
    "danger": (C["danger_bg"], C["danger"], "#4a2a27", None),
}


def bind_hover(widget: tk.Widget, normal_bg: str | Callable[[], str], hover_bg: str | None) -> None:
    """Swap bg on hover. normal_bg may be a callable (e.g. the row's current bg)."""
    if not hover_bg:
        return

    def on_enter(_e: tk.Event) -> None:
        if str(widget.cget("state")) != "disabled":
            widget.configure(bg=hover_bg)

    def on_leave(_e: tk.Event) -> None:
        widget.configure(bg=normal_bg() if callable(normal_bg) else normal_bg)

    widget.bind("<Enter>", on_enter, add="+")
    widget.bind("<Leave>", on_leave, add="+")


def button(
    parent: tk.Misc,
    text: str,
    command: Callable[[], object] | None = None,
    *,
    variant: str = "secondary",
    size: str = "md",
    parent_bg: str | None = None,
    bold: bool | None = None,
) -> tk.Button:
    bg, fg, hover_bg, border = _BUTTON_VARIANTS[variant]
    base_bg = bg or parent_bg or C["surface"]
    if variant == "primary" and bold is None:
        bold = True
    font = F["body_bold"] if bold else F["body"]
    if size == "sm":
        font = F["small_bold"] if bold else F["small"]
    padx, pady = {"sm": (10, 4), "md": (14, 8), "lg": (18, 10)}[size]

    btn = tk.Button(
        parent,
        text=text,
        command=command,
        font=font,
        bg=base_bg,
        fg=fg,
        activebackground=hover_bg or base_bg,
        activeforeground=fg,
        disabledforeground=C["subtle"],
        relief="flat",
        bd=0,
        padx=padx,
        pady=pady,
        cursor="hand2",
        highlightthickness=1 if border else 0,
        highlightbackground=border or base_bg,
        highlightcolor=border or base_bg,
    )
    bind_hover(btn, base_bg, hover_bg)
    return btn


def icon_button(
    parent: tk.Misc,
    name: str,
    command: Callable[[], object] | None,
    *,
    parent_bg: str,
    tooltip: str | None = None,
    fg: str | None = None,
    hover_bg: str | None = None,
    base_bg: Callable[[], str] | None = None,
) -> tk.Button:
    text, font = icon(name)
    btn = tk.Button(
        parent,
        text=text,
        font=font,
        command=command,
        bg=parent_bg,
        fg=fg or C["muted"],
        activebackground=hover_bg or C["hover"],
        activeforeground=C["text"],
        relief="flat",
        bd=0,
        width=3,
        pady=4,
        cursor="hand2",
        highlightthickness=0,
    )
    bind_hover(btn, base_bg or parent_bg, hover_bg or C["hover"])
    if tooltip:
        Tooltip(btn, tooltip)
    return btn


def label(
    parent: tk.Misc,
    text: str = "",
    *,
    kind: str = "body",
    bg: str,
    fg: str | None = None,
    **kwargs: object,
) -> tk.Label:
    colors = {
        "body": C["text"],
        "muted": C["muted"],
        "subtle": C["subtle"],
        "title": C["text"],
        "subtitle": C["text"],
        "kpi": C["text"],
        "caption": C["subtle"],
        "small": C["muted"],
        "small_bold": C["text"],
        "brand": C["accent"],
        "ticket": C["text"],
        "body_bold": C["text"],
    }
    font_key = {"muted": "body", "subtle": "small"}.get(kind, kind)
    return tk.Label(
        parent,
        text=text,
        font=F[font_key],
        fg=fg or colors.get(kind, C["text"]),
        bg=bg,
        anchor="w",
        justify="left",
        **kwargs,
    )


PILL_KINDS = {
    "pending": (C["warn_bg"], C["warn"]),
    "synced": (C["ok_bg"], C["ok"]),
    "off": (C["off_bg"], C["off"]),
    "danger": (C["danger_bg"], C["danger"]),
    "neutral": (C["raised"], C["muted"]),
}


def pill(parent: tk.Misc, text: str, kind: str) -> tk.Label:
    bg, fg = PILL_KINDS[kind]
    return tk.Label(parent, text=text, font=F["small_bold"], bg=bg, fg=fg, padx=8, pady=2)


def entry(parent: tk.Misc, *, width: int = 30, textvariable: tk.StringVar | None = None, **kwargs: object) -> tk.Entry:
    return tk.Entry(
        parent,
        width=width,
        textvariable=textvariable,
        font=(FAMILY, 11),
        bg=C["raised"],
        fg=C["text"],
        disabledbackground=C["surface"],
        disabledforeground=C["muted"],
        readonlybackground=C["surface"],
        insertbackground=C["text"],
        selectbackground=C["accent"],
        selectforeground=C["on_accent"],
        relief="flat",
        bd=6,
        highlightthickness=1,
        highlightbackground=C["border"],
        highlightcolor=C["accent"],
        **kwargs,
    )


def text_area(parent: tk.Misc, *, height: int = 4, width: int = 60) -> tk.Text:
    return tk.Text(
        parent,
        height=height,
        width=width,
        font=(FAMILY, 10),
        wrap="word",
        bg=C["raised"],
        fg=C["text"],
        insertbackground=C["text"],
        selectbackground=C["accent"],
        selectforeground=C["on_accent"],
        relief="flat",
        bd=8,
        highlightthickness=1,
        highlightbackground=C["border"],
        highlightcolor=C["accent"],
    )


def checkbox(parent: tk.Misc, text: str, variable: tk.BooleanVar, *, bg: str) -> tk.Checkbutton:
    return tk.Checkbutton(
        parent,
        text=text,
        variable=variable,
        font=F["body"],
        fg=C["text"],
        bg=bg,
        activebackground=bg,
        activeforeground=C["text"],
        selectcolor=C["raised"],
        highlightthickness=0,
        bd=0,
        cursor="hand2",
    )


def menu(parent: tk.Misc) -> tk.Menu:
    return tk.Menu(
        parent,
        tearoff=0,
        bg=C["raised"],
        fg=C["text"],
        activebackground=C["hover"],
        activeforeground=C["text"],
        disabledforeground=C["muted"],
        font=F["body"],
        bd=1,
        relief="flat",
    )


def divider(parent: tk.Misc, *, color: str | None = None) -> tk.Frame:
    return tk.Frame(parent, bg=color or C["border"], height=1)


class Tooltip:
    """Small delayed tooltip, used for icon-only buttons and clipped text."""

    def __init__(self, widget: tk.Widget, text: str, delay_ms: int = 450) -> None:
        self.widget = widget
        self.text = text
        self.delay_ms = delay_ms
        self._after_id: str | None = None
        self._tip: tk.Toplevel | None = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _e: tk.Event) -> None:
        self._cancel()
        self._after_id = self.widget.after(self.delay_ms, self._show)

    def _cancel(self) -> None:
        if self._after_id is not None:
            try:
                self.widget.after_cancel(self._after_id)
            except tk.TclError:
                pass
            self._after_id = None

    def _show(self) -> None:
        if self._tip is not None or not self.widget.winfo_exists():
            return
        x = self.widget.winfo_rootx() + 4
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        tip = tk.Toplevel(self.widget)
        tip.wm_overrideredirect(True)
        tip.wm_geometry(f"+{x}+{y}")
        tk.Label(
            tip,
            text=self.text,
            font=F["small"],
            bg=C["hover"],
            fg=C["text"],
            padx=8,
            pady=4,
            wraplength=420,
            justify="left",
        ).pack()
        self._tip = tip

    def _hide(self, _e: tk.Event | None = None) -> None:
        self._cancel()
        if self._tip is not None:
            self._tip.destroy()
            self._tip = None
