"""Always-on-top call popups.

Each popup is a borderless card pinned to the bottom-right corner. They stack
upward, newest nearest the taskbar, and — per the spec — never auto-dismiss.
A soft cap keeps a burst from covering the whole screen: only the newest
MAX_VISIBLE are kept on screen (older ones drop off but remain in the list).

All methods must run on the Tk (main) thread; the Realtime thread marshals here
via root.after(0, ...).
"""

from __future__ import annotations

import logging
import threading
import tkinter as tk
from typing import Any

from . import theme
from .api import SupabaseRest, CALL_TYPE_LABELS

log = logging.getLogger("ringkeeper.popup")

POPUP_W = 360
POPUP_H = 116
GAP = 10
SCREEN_MARGIN = 18
TASKBAR_ALLOWANCE = 52
MAX_VISIBLE = 5
AVATAR = 46

# WhatsApp-message popups are ephemeral: they auto-dismiss (nothing is stored).
MESSAGE_ACCENT = "#25d366"
MESSAGE_DISMISS_MS = 12000

# System alerts (e.g. "phone inactive") are not WhatsApp messages: they carry an
# amber accent (matching the tray's inactive state) and stay put until dismissed.
ALERT_ACCENT = "#e6a01e"


class PopupManager:
    def __init__(self, root: tk.Tk, api: SupabaseRest):
        self.root = root
        self.api = api
        self._open: list[tk.Toplevel] = []

    def show(self, call: dict[str, Any]) -> None:
        call_type = call.get("call_type", "missed")
        accent = theme.type_color(call_type)
        type_label = CALL_TYPE_LABELS.get(call_type, "Call")
        name = call.get("caller_name") or call.get("number") or "Unknown"
        number = call.get("number", "")

        win = tk.Toplevel(self.root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg=theme.BG_BORDER)
        win.resizable(False, False)

        body = tk.Frame(win, bg=theme.BG_CARD)
        body.pack(fill="both", expand=True, padx=1, pady=1)

        # Colored accent strip down the left edge.
        tk.Frame(body, bg=accent, width=4).pack(side="left", fill="y")

        content = tk.Frame(body, bg=theme.BG_CARD)
        content.pack(side="left", fill="both", expand=True, padx=(12, 12), pady=10)

        # Header: "● Missed call" + time + close.
        header = tk.Frame(content, bg=theme.BG_CARD)
        header.pack(fill="x")
        tk.Label(
            header, text=f"● {type_label} call", bg=theme.BG_CARD, fg=accent,
            font=(theme.FONT_SEMI, 9),
        ).pack(side="left")
        close = tk.Label(
            header, text="✕", bg=theme.BG_CARD, fg=theme.FG_DIM,
            font=(theme.FONT, 10), cursor="hand2",
        )
        close.pack(side="right")
        close.bind("<Button-1>", lambda _e: self._close(win, call))
        close.bind("<Enter>", lambda _e: close.configure(fg=theme.FG))
        close.bind("<Leave>", lambda _e: close.configure(fg=theme.FG_DIM))
        tk.Label(
            header, text=theme.relative_time(call.get("call_time", "")),
            bg=theme.BG_CARD, fg=theme.FG_SUBTLE, font=(theme.FONT, 9),
        ).pack(side="right", padx=(0, 10))

        # Row: avatar + name/number.
        row = tk.Frame(content, bg=theme.BG_CARD)
        row.pack(fill="x", pady=(8, 0))

        av = tk.Canvas(
            row, width=AVATAR, height=AVATAR, bg=theme.BG_CARD,
            highlightthickness=0,
        )
        av.pack(side="left")
        av.create_oval(2, 2, AVATAR - 2, AVATAR - 2, fill=accent, outline="")
        av.create_text(
            AVATAR / 2, AVATAR / 2, text=theme.initial_of(name),
            fill="#ffffff", font=(theme.FONT_SEMI, 16),
        )

        text = tk.Frame(row, bg=theme.BG_CARD)
        text.pack(side="left", fill="x", expand=True, padx=(12, 0))
        tk.Label(
            text, text=name, bg=theme.BG_CARD, fg=theme.FG,
            font=(theme.FONT_SEMI, 13), anchor="w", justify="left",
        ).pack(fill="x")
        if number and number != name:
            tk.Label(
                text, text=number, bg=theme.BG_CARD, fg=theme.FG_SUBTLE,
                font=(theme.FONT, 10), anchor="w",
            ).pack(fill="x")

        dismiss = tk.Button(
            row, text="Dismiss", relief="flat", bg=theme.BG_ELEV, fg=theme.FG,
            activebackground=theme.BG_HOVER, activeforeground=theme.FG, bd=0,
            font=(theme.FONT, 9), cursor="hand2", padx=14, pady=6,
            command=lambda: self._close(win, call),
        )
        dismiss.pack(side="right", anchor="s")
        dismiss.bind("<Enter>", lambda _e: dismiss.configure(bg=theme.BG_HOVER))
        dismiss.bind("<Leave>", lambda _e: dismiss.configure(bg=theme.BG_ELEV))

        self._open.append(win)
        self._enforce_cap()
        self._reflow()

    def show_message(self, sender: str, preview: str) -> None:
        """A transient WhatsApp-message card. Auto-dismisses; nothing is stored."""
        self._show_card(
            header="WhatsApp message",
            name=sender or "WhatsApp",
            preview=preview,
            accent=MESSAGE_ACCENT,
            auto_dismiss_ms=MESSAGE_DISMISS_MS,
        )

    def show_alert(self, title: str, detail: str) -> None:
        """A system alert (e.g. 'phone inactive') — amber, persistent, not a
        WhatsApp message. Stays on screen until the user dismisses it."""
        self._show_card(
            header="RingKeeper alert",
            name=title,
            preview=detail,
            accent=ALERT_ACCENT,
            auto_dismiss_ms=None,
            avatar_text="!",
        )

    def _show_card(
        self,
        header: str,
        name: str,
        preview: str,
        accent: str,
        auto_dismiss_ms: int | None,
        avatar_text: str | None = None,
    ) -> None:
        """Shared transient card used for WhatsApp messages and system alerts.

        Not tied to a stored call: closing just dismisses it (no mark-seen). When
        ``auto_dismiss_ms`` is set the card fades itself after that delay;
        alerts pass None to stay until dismissed by hand.
        """
        win = tk.Toplevel(self.root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg=theme.BG_BORDER)
        win.resizable(False, False)

        body = tk.Frame(win, bg=theme.BG_CARD)
        body.pack(fill="both", expand=True, padx=1, pady=1)
        tk.Frame(body, bg=accent, width=4).pack(side="left", fill="y")

        content = tk.Frame(body, bg=theme.BG_CARD)
        content.pack(side="left", fill="both", expand=True, padx=(12, 12), pady=10)

        header_row = tk.Frame(content, bg=theme.BG_CARD)
        header_row.pack(fill="x")
        tk.Label(
            header_row, text=f"● {header}", bg=theme.BG_CARD, fg=accent,
            font=(theme.FONT_SEMI, 9),
        ).pack(side="left")
        close = tk.Label(
            header_row, text="✕", bg=theme.BG_CARD, fg=theme.FG_DIM,
            font=(theme.FONT, 10), cursor="hand2",
        )
        close.pack(side="right")
        close.bind("<Button-1>", lambda _e: self._close_message(win))
        close.bind("<Enter>", lambda _e: close.configure(fg=theme.FG))
        close.bind("<Leave>", lambda _e: close.configure(fg=theme.FG_DIM))

        row = tk.Frame(content, bg=theme.BG_CARD)
        row.pack(fill="x", pady=(8, 0))
        av = tk.Canvas(
            row, width=AVATAR, height=AVATAR, bg=theme.BG_CARD, highlightthickness=0,
        )
        av.pack(side="left")
        av.create_oval(2, 2, AVATAR - 2, AVATAR - 2, fill=accent, outline="")
        av.create_text(
            AVATAR / 2, AVATAR / 2, text=avatar_text or theme.initial_of(name),
            fill="#ffffff", font=(theme.FONT_SEMI, 16),
        )
        text_col = tk.Frame(row, bg=theme.BG_CARD)
        text_col.pack(side="left", fill="x", expand=True, padx=(12, 0))
        tk.Label(
            text_col, text=name, bg=theme.BG_CARD, fg=theme.FG,
            font=(theme.FONT_SEMI, 13), anchor="w", justify="left",
        ).pack(fill="x")
        tk.Label(
            text_col, text=preview, bg=theme.BG_CARD, fg=theme.FG_SUBTLE,
            font=(theme.FONT, 10), anchor="w", justify="left", wraplength=POPUP_W - 100,
        ).pack(fill="x")

        self._open.append(win)
        self._enforce_cap()
        self._reflow()
        if auto_dismiss_ms is not None:
            win.after(auto_dismiss_ms, lambda: self._close_message(win))

    def _close_message(self, win: tk.Toplevel) -> None:
        if win in self._open:
            self._open.remove(win)
        try:
            win.destroy()
        except tk.TclError:
            pass
        self._reflow()

    def _enforce_cap(self) -> None:
        """Keep only the newest MAX_VISIBLE popups on screen."""
        while len(self._open) > MAX_VISIBLE:
            oldest = self._open.pop(0)
            try:
                oldest.destroy()
            except tk.TclError:
                pass

    def _close(self, win: tk.Toplevel, call: dict[str, Any]) -> None:
        if win in self._open:
            self._open.remove(win)
        try:
            win.destroy()
        except tk.TclError:
            pass
        self._reflow()
        call_id = call.get("id")
        if isinstance(call_id, int):
            threading.Thread(
                target=self._mark_seen_safe, args=(call_id,), daemon=True
            ).start()

    def _mark_seen_safe(self, call_id: int) -> None:
        try:
            self.api.mark_seen(call_id)
        except Exception as exc:  # noqa: BLE001
            log.warning("Failed to mark call %s seen: %s", call_id, exc)

    def _reflow(self) -> None:
        """Re-stack open popups from the bottom-right corner upward."""
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = sw - POPUP_W - SCREEN_MARGIN
        for i, win in enumerate(reversed(self._open)):
            y = sh - TASKBAR_ALLOWANCE - (i + 1) * POPUP_H - i * GAP
            try:
                win.geometry(f"{POPUP_W}x{POPUP_H}+{x}+{y}")
                win.lift()
                win.attributes("-topmost", True)
            except tk.TclError:
                pass
