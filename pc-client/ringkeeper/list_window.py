"""The full call-list window — a dark, sortable table of every call.

Newest first, filterable by call type. Unseen calls are emphasized; rows are
zebra-striped. Network fetches run off the Tk thread and results are marshalled
back with root.after.
"""

from __future__ import annotations

import logging
import threading
import tkinter as tk
from tkinter import ttk
from typing import Any

from . import theme
from .api import SupabaseRest, CALL_TYPE_LABELS

log = logging.getLogger("ringkeeper.list")

FILTER_ALL = "All"


class ListWindow:
    def __init__(self, root: tk.Tk, api: SupabaseRest):
        self.root = root
        self.api = api
        self.win: tk.Toplevel | None = None
        self.tree: ttk.Treeview | None = None
        self.filter_var: tk.StringVar | None = None
        self.status_var: tk.StringVar | None = None

    # --- styling ---------------------------------------------------------
    def _apply_style(self) -> None:
        style = ttk.Style(self.win)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(
            "RK.Treeview", background=theme.BG_CARD, fieldbackground=theme.BG_CARD,
            foreground=theme.FG, rowheight=32, borderwidth=0, font=(theme.FONT, 10),
        )
        style.configure(
            "RK.Treeview.Heading", background=theme.BG_ELEV, foreground=theme.FG_SUBTLE,
            relief="flat", font=(theme.FONT_SEMI, 10), padding=(8, 6),
        )
        style.map(
            "RK.Treeview",
            background=[("selected", theme.BG_HOVER)],
            foreground=[("selected", theme.FG)],
        )
        style.map("RK.Treeview.Heading", background=[("active", theme.BG_HOVER)])
        style.configure(
            "RK.TButton", background=theme.BG_ELEV, foreground=theme.FG,
            borderwidth=0, padding=(12, 6), font=(theme.FONT, 10),
        )
        style.map(
            "RK.TButton",
            background=[("active", theme.BG_HOVER), ("pressed", theme.BG_HOVER)],
        )
        style.configure(
            "RK.TCombobox", fieldbackground=theme.BG_ELEV, background=theme.BG_ELEV,
            foreground=theme.FG, arrowcolor=theme.FG_SUBTLE, borderwidth=0,
            padding=4,
        )

    def open(self) -> None:
        if self.win is not None and self.win.winfo_exists():
            self.win.deiconify()
            self.win.lift()
            self.win.focus_force()
            return

        self.win = tk.Toplevel(self.root)
        self.win.title("RingKeeper — Calls")
        self.win.geometry("720x500")
        self.win.minsize(560, 340)
        self.win.configure(bg=theme.BG_CARD)
        self.win.protocol("WM_DELETE_WINDOW", self._hide)
        self._apply_style()

        # Header ----------------------------------------------------------
        header = tk.Frame(self.win, bg=theme.BG_CARD)
        header.pack(fill="x", padx=16, pady=(14, 4))
        tk.Label(
            header, text="Call history", bg=theme.BG_CARD, fg=theme.FG,
            font=(theme.FONT_SEMI, 15),
        ).pack(side="left")

        # Toolbar ---------------------------------------------------------
        toolbar = tk.Frame(self.win, bg=theme.BG_CARD)
        toolbar.pack(fill="x", padx=16, pady=(6, 10))

        tk.Label(
            toolbar, text="Show", bg=theme.BG_CARD, fg=theme.FG_SUBTLE,
            font=(theme.FONT, 10),
        ).pack(side="left", padx=(0, 6))
        self.filter_var = tk.StringVar(value=FILTER_ALL)
        choices = [FILTER_ALL] + list(CALL_TYPE_LABELS.values())
        combo = ttk.Combobox(
            toolbar, textvariable=self.filter_var, values=choices,
            state="readonly", width=12, style="RK.TCombobox",
        )
        combo.pack(side="left", padx=(0, 12))
        combo.bind("<<ComboboxSelected>>", lambda _e: self.refresh())

        ttk.Button(
            toolbar, text="Refresh", command=self.refresh, style="RK.TButton",
        ).pack(side="left")
        ttk.Button(
            toolbar, text="Mark selected seen", command=self._mark_selected,
            style="RK.TButton",
        ).pack(side="left", padx=8)

        # Table -----------------------------------------------------------
        table = tk.Frame(self.win, bg=theme.BG_CARD)
        table.pack(fill="both", expand=True, padx=16, pady=(0, 8))

        cols = ("time", "type", "name", "number", "seen")
        self.tree = ttk.Treeview(
            table, columns=cols, show="headings", style="RK.Treeview",
        )
        for col, text, width, anchor in (
            ("time", "When", 150, "w"),
            ("type", "Type", 90, "w"),
            ("name", "Caller", 170, "w"),
            ("number", "Number", 150, "w"),
            ("seen", "Seen", 60, "center"),
        ):
            self.tree.heading(col, text=text)
            self.tree.column(col, width=width, anchor=anchor)
        self.tree.pack(side="left", fill="both", expand=True)

        scroll = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")

        self.tree.tag_configure("odd", background=theme.BG_CARD)
        self.tree.tag_configure("even", background=theme.BG_CARD_ALT)
        self.tree.tag_configure("unseen", font=(theme.FONT_SEMI, 10), foreground=theme.FG)
        self.tree.bind("<Double-1>", self._on_double_click)

        # Status bar ------------------------------------------------------
        self.status_var = tk.StringVar(value="Loading…")
        tk.Label(
            self.win, textvariable=self.status_var, anchor="w", bg=theme.BG_CARD,
            fg=theme.FG_DIM, font=(theme.FONT, 9),
        ).pack(fill="x", padx=16, pady=(0, 10))

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
            call_type = next((k for k, v in CALL_TYPE_LABELS.items() if v == label), None)
        threading.Thread(target=self._fetch, args=(call_type,), daemon=True).start()

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
        unseen = 0
        for i, c in enumerate(calls):
            seen = bool(c.get("seen"))
            if not seen:
                unseen += 1
            tags = ["even" if i % 2 else "odd"]
            if not seen:
                tags.append("unseen")
            self.tree.insert(
                "", "end", iid=str(c["id"]), tags=tuple(tags),
                values=(
                    theme.relative_time(c.get("call_time", "")),
                    CALL_TYPE_LABELS.get(c.get("call_type", "unknown"), "Unknown"),
                    c.get("caller_name") or "—",
                    c.get("number", ""),
                    "" if seen else "●",
                ),
            )
        total = len(calls)
        self._set_status(
            f"{total} call{'s' if total != 1 else ''}"
            + (f"  ·  {unseen} unseen" if unseen else "  ·  all seen")
        )

    def _set_status(self, text: str) -> None:
        if self.status_var is not None:
            self.status_var.set(text)

    def _on_double_click(self, _event: object) -> None:
        self._mark_selected()

    def _mark_selected(self) -> None:
        if self.tree is None:
            return
        ids = [int(iid) for iid in self.tree.selection() if iid.isdigit()]
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
        """Update a row when another client marked a call seen."""
        if self.tree is None or not self.tree.winfo_exists():
            return
        iid = str(call_id)
        if self.tree.exists(iid):
            vals = list(self.tree.item(iid, "values"))
            if len(vals) == 5:
                vals[4] = ""
                tags = tuple(t for t in self.tree.item(iid, "tags") if t != "unseen")
                self.tree.item(iid, values=vals, tags=tags)
