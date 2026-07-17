"""The full missed/all-calls list window.

A single reusable Toplevel with a table of calls grouped by nothing but sorted
newest-first, filterable by call type. Network fetches run off the Tk thread and
results are marshalled back with root.after.
"""

from __future__ import annotations

import logging
import threading
import tkinter as tk
from datetime import datetime
from tkinter import ttk
from typing import Any

from .api import ApiClient, CALL_TYPE_LABELS

log = logging.getLogger("ringkeeper.list")

FILTER_ALL = "All"


def _fmt(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone().strftime(
            "%Y-%m-%d  %H:%M"
        )
    except ValueError:
        return iso


class ListWindow:
    def __init__(self, root: tk.Tk, api: ApiClient):
        self.root = root
        self.api = api
        self.win: tk.Toplevel | None = None
        self.tree: ttk.Treeview | None = None
        self.filter_var: tk.StringVar | None = None
        self.status_var: tk.StringVar | None = None

    def open(self) -> None:
        # Re-focus an already-open window instead of spawning a second one.
        if self.win is not None and self.win.winfo_exists():
            self.win.deiconify()
            self.win.lift()
            self.win.focus_force()
            return

        self.win = tk.Toplevel(self.root)
        self.win.title("RingKeeper — Calls")
        self.win.geometry("640x460")
        self.win.minsize(520, 320)
        self.win.protocol("WM_DELETE_WINDOW", self._hide)

        toolbar = tk.Frame(self.win)
        toolbar.pack(fill="x", padx=10, pady=(10, 6))

        tk.Label(toolbar, text="Type:").pack(side="left")
        self.filter_var = tk.StringVar(value=FILTER_ALL)
        choices = [FILTER_ALL] + list(CALL_TYPE_LABELS.values())
        combo = ttk.Combobox(
            toolbar, textvariable=self.filter_var, values=choices,
            state="readonly", width=12,
        )
        combo.pack(side="left", padx=(6, 12))
        combo.bind("<<ComboboxSelected>>", lambda _e: self.refresh())

        ttk.Button(toolbar, text="Refresh", command=self.refresh).pack(side="left")
        ttk.Button(toolbar, text="Mark selected seen", command=self._mark_selected).pack(
            side="left", padx=6
        )

        cols = ("time", "type", "name", "number", "seen")
        self.tree = ttk.Treeview(self.win, columns=cols, show="headings")
        for col, text, width in (
            ("time", "Time", 140),
            ("type", "Type", 90),
            ("name", "Caller", 150),
            ("number", "Number", 140),
            ("seen", "Seen", 60),
        ):
            self.tree.heading(col, text=text)
            self.tree.column(col, width=width, anchor="w")
        self.tree.pack(fill="both", expand=True, padx=10, pady=(0, 6))

        scroll = ttk.Scrollbar(self.tree, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")

        self.status_var = tk.StringVar(value="Loading…")
        tk.Label(self.win, textvariable=self.status_var, anchor="w", fg="#666").pack(
            fill="x", padx=10, pady=(0, 8)
        )

        self.refresh()

    def _hide(self) -> None:
        if self.win is not None:
            self.win.withdraw()

    # --- data ------------------------------------------------------------
    def refresh(self) -> None:
        if self.status_var is not None:
            self.status_var.set("Loading…")
        label = self.filter_var.get() if self.filter_var else FILTER_ALL
        call_type = None
        if label != FILTER_ALL:
            call_type = next(
                (k for k, v in CALL_TYPE_LABELS.items() if v == label), None
            )
        threading.Thread(
            target=self._fetch, args=(call_type,), daemon=True
        ).start()

    def _fetch(self, call_type: str | None) -> None:
        try:
            calls = self.api.list_calls(call_type=call_type, limit=1000)
            self.root.after(0, lambda: self._populate(calls))
        except Exception as exc:  # noqa: BLE001
            log.warning("List fetch failed: %s", exc)
            self.root.after(0, lambda: self._set_status(f"Error: {exc}"))

    def _populate(self, calls: list[dict[str, Any]]) -> None:
        if self.tree is None or not self.tree.winfo_exists():
            return
        self.tree.delete(*self.tree.get_children())
        for c in calls:
            self.tree.insert(
                "", "end", iid=str(c["id"]),
                values=(
                    _fmt(c.get("call_time", "")),
                    CALL_TYPE_LABELS.get(c.get("call_type", "unknown"), "Unknown"),
                    c.get("caller_name") or "—",
                    c.get("number", ""),
                    "✓" if c.get("seen") else "",
                ),
            )
        self._set_status(f"{len(calls)} call(s)")

    def _set_status(self, text: str) -> None:
        if self.status_var is not None:
            self.status_var.set(text)

    def _mark_selected(self) -> None:
        if self.tree is None:
            return
        selected = self.tree.selection()
        ids = [int(iid) for iid in selected if iid.isdigit()]
        if not ids:
            return

        def worker() -> None:
            for cid in ids:
                try:
                    self.api.mark_seen(cid)
                except Exception as exc:  # noqa: BLE001
                    log.warning("mark_seen(%s) failed: %s", cid, exc)
            self.root.after(0, self.refresh)

        threading.Thread(target=worker, daemon=True).start()

    def apply_seen(self, call_id: int) -> None:
        """Update the row when another client marked a call seen (WS call_seen)."""
        if self.tree is None or not self.tree.winfo_exists():
            return
        iid = str(call_id)
        if self.tree.exists(iid):
            vals = list(self.tree.item(iid, "values"))
            if len(vals) == 5:
                vals[4] = "✓"
                self.tree.item(iid, values=vals)
