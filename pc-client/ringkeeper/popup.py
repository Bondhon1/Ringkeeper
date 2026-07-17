"""Always-on-top missed-call popups.

Each popup is a borderless Tk Toplevel pinned to the bottom-right corner. They
stack upward when several arrive and — per the spec — never auto-dismiss. Closing
one marks the call as seen on the server and reflows the remaining popups.

All methods must be called on the Tk (main) thread. The WS thread marshals here
via root.after(0, ...).
"""

from __future__ import annotations

import logging
import threading
import tkinter as tk
from datetime import datetime, timezone
from typing import Any

from .api import ApiClient, CALL_TYPE_LABELS

log = logging.getLogger("ringkeeper.popup")

POPUP_W = 340
POPUP_H = 128
GAP = 12
SCREEN_MARGIN = 16
# Rough allowance so the lowest popup sits above the Windows taskbar.
TASKBAR_ALLOWANCE = 48

BG = "#1f2430"
ACCENT = "#e5484d"  # red — missed call
FG = "#f5f7fa"
SUBTLE = "#9aa4b2"


def _format_time(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone()
    except ValueError:
        return iso
    now = datetime.now(timezone.utc).astimezone()
    if dt.date() == now.date():
        return dt.strftime("%H:%M")
    return dt.strftime("%b %d, %H:%M")


class PopupManager:
    def __init__(self, root: tk.Tk, api: ApiClient):
        self.root = root
        self.api = api
        self._open: list[tk.Toplevel] = []

    def show(self, call: dict[str, Any]) -> None:
        win = tk.Toplevel(self.root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg=ACCENT)  # thin accent border via padding
        win.resizable(False, False)

        # Inner frame gives us a 2px accent edge around the dark body.
        body = tk.Frame(win, bg=BG)
        body.pack(fill="both", expand=True, padx=2, pady=2)

        type_label = CALL_TYPE_LABELS.get(call.get("call_type", "missed"), "Call")
        header = tk.Frame(body, bg=BG)
        header.pack(fill="x", padx=14, pady=(12, 2))
        tk.Label(
            header, text=f"● {type_label} call", bg=BG, fg=ACCENT,
            font=("Segoe UI Semibold", 10),
        ).pack(side="left")
        tk.Label(
            header, text=_format_time(call.get("call_time", "")), bg=BG, fg=SUBTLE,
            font=("Segoe UI", 9),
        ).pack(side="right")

        name = call.get("caller_name") or call.get("number") or "Unknown"
        tk.Label(
            body, text=name, bg=BG, fg=FG, font=("Segoe UI Semibold", 14),
            anchor="w", justify="left",
        ).pack(fill="x", padx=14)

        number = call.get("number", "")
        if number and number != name:
            tk.Label(
                body, text=number, bg=BG, fg=SUBTLE, font=("Segoe UI", 10), anchor="w",
            ).pack(fill="x", padx=14, pady=(0, 8))
        else:
            tk.Frame(body, bg=BG, height=8).pack()

        dismiss = tk.Button(
            body, text="Dismiss", relief="flat", bg="#2b3242", fg=FG,
            activebackground="#3a4256", activeforeground=FG, bd=0,
            font=("Segoe UI", 9), cursor="hand2",
            command=lambda: self._close(win, call),
        )
        dismiss.place(relx=1.0, rely=1.0, x=-12, y=-10, anchor="se")

        self._open.append(win)
        self._reflow()

    def _close(self, win: tk.Toplevel, call: dict[str, Any]) -> None:
        if win in self._open:
            self._open.remove(win)
        try:
            win.destroy()
        except tk.TclError:
            pass
        self._reflow()
        # Acknowledge on the server off the GUI thread.
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
