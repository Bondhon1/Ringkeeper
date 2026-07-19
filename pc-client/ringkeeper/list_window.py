"""The full call-list window — a modern, dark, card-style list of every call.

Newest first, filterable by a row of pill buttons. Each call is rendered as a
row card (colored avatar, name, type badge, relative time, unseen dot) rather
than a spreadsheet-style table. Network fetches run off the Tk thread and
results are marshalled back with root.after.
"""

from __future__ import annotations

import logging
import threading
import tkinter as tk
from typing import Any, Callable

from . import theme
from .api import SupabaseRest, CALL_TYPE_LABELS

log = logging.getLogger("ringkeeper.list")

# Filter pills: label -> predicate over a call_type (None = everything).
FILTERS: list[tuple[str, Callable[[str], bool]]] = [
    ("All", lambda _t: True),
    ("Missed", lambda t: t in ("missed", "whatsapp_missed")),
    ("Incoming", lambda t: t in ("incoming", "whatsapp_incoming")),
    ("Outgoing", lambda t: t == "outgoing"),
    ("WhatsApp", lambda t: t.startswith("whatsapp_")),
    ("Other", lambda t: t in ("rejected", "blocked", "voicemail", "unknown")),
]

MAX_ROWS = 300  # keep rendering snappy on large histories


class ListWindow:
    def __init__(self, root: tk.Tk, api: SupabaseRest):
        self.root = root
        self.api = api
        self.win: tk.Toplevel | None = None
        self.canvas: tk.Canvas | None = None
        self.inner: tk.Frame | None = None
        self.status_var: tk.StringVar | None = None
        self.filter: str = "All"
        self._pills: dict[str, tk.Label] = {}
        self._calls: list[dict[str, Any]] = []
        self._rows: dict[int, tk.Frame] = {}

    # --- window ----------------------------------------------------------
    def open(self) -> None:
        if self.win is not None and self.win.winfo_exists():
            self.win.deiconify()
            self.win.lift()
            self.win.focus_force()
            return

        self.win = tk.Toplevel(self.root)
        self.win.title("RingKeeper — Calls")
        self.win.geometry(f"{theme.px(760)}x{theme.px(560)}")
        self.win.minsize(theme.px(560), theme.px(380))
        self.win.configure(bg=theme.BG_BASE)
        self.win.protocol("WM_DELETE_WINDOW", self._hide)

        # Header ----------------------------------------------------------
        header = tk.Frame(self.win, bg=theme.BG_BASE)
        header.pack(fill="x", padx=22, pady=(20, 6))
        tk.Label(
            header, text="Call history", bg=theme.BG_BASE, fg=theme.FG,
            font=(theme.FONT_SEMI, 17),
        ).pack(side="left")
        refresh = tk.Label(
            header, text="⟳  Refresh", bg=theme.BG_ELEV, fg=theme.FG_SUBTLE,
            font=(theme.FONT_SEMI, 9), padx=12, pady=6, cursor="hand2",
        )
        refresh.pack(side="right")
        refresh.bind("<Button-1>", lambda _e: self.refresh())
        _hoverable(refresh, theme.BG_ELEV, theme.BG_HOVER)

        # Filter pills ----------------------------------------------------
        pills = tk.Frame(self.win, bg=theme.BG_BASE)
        pills.pack(fill="x", padx=22, pady=(4, 12))
        for label, _pred in FILTERS:
            pill = tk.Label(
                pills, text=label, font=(theme.FONT_SEMI, 9), padx=13, pady=6,
                cursor="hand2",
            )
            pill.pack(side="left", padx=(0, 8))
            pill.bind("<Button-1>", lambda _e, l=label: self._select_filter(l))
            self._pills[label] = pill

        # Scrollable list -------------------------------------------------
        body = tk.Frame(self.win, bg=theme.BG_CARD, highlightthickness=1,
                        highlightbackground=theme.STROKE)
        body.pack(fill="both", expand=True, padx=22, pady=(0, 8))

        self.canvas = tk.Canvas(body, bg=theme.BG_CARD, highlightthickness=0, bd=0)
        self.canvas.pack(side="left", fill="both", expand=True)
        scroll = tk.Scrollbar(body, orient="vertical", command=self.canvas.yview)
        scroll.pack(side="right", fill="y")
        self.canvas.configure(yscrollcommand=scroll.set)

        self.inner = tk.Frame(self.canvas, bg=theme.BG_CARD)
        self._win_id = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind(
            "<Configure>",
            lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")),
        )
        self.canvas.bind(
            "<Configure>",
            lambda e: self.canvas.itemconfigure(self._win_id, width=e.width),
        )
        self._bind_wheel(self.canvas)

        # Status bar ------------------------------------------------------
        self.status_var = tk.StringVar(value="Loading…")
        tk.Label(
            self.win, textvariable=self.status_var, anchor="w", bg=theme.BG_BASE,
            fg=theme.FG_DIM, font=(theme.FONT, 9),
        ).pack(fill="x", padx=22, pady=(0, 12))

        self._style_pills()
        self.refresh()

    def _hide(self) -> None:
        if self.win is not None:
            self.win.withdraw()

    # --- filter pills ----------------------------------------------------
    def _select_filter(self, label: str) -> None:
        self.filter = label
        self._style_pills()
        self._populate()

    def _style_pills(self) -> None:
        for label, pill in self._pills.items():
            if label == self.filter:
                pill.configure(bg=theme.BRAND, fg="#ffffff")
                _hoverable(pill, theme.BRAND, theme.BRAND)
            else:
                pill.configure(bg=theme.BG_ELEV, fg=theme.FG_SUBTLE)
                _hoverable(pill, theme.BG_ELEV, theme.BG_HOVER)

    # --- data ------------------------------------------------------------
    def refresh(self) -> None:
        if self.status_var is not None:
            self.status_var.set("Loading…")
        threading.Thread(target=self._fetch, daemon=True).start()

    def _fetch(self) -> None:
        try:
            calls = self.api.list_calls(limit=1000)
            self.root.after(0, lambda: self._on_fetched(calls))
        except Exception as exc:  # noqa: BLE001
            log.warning("List fetch failed: %s", exc)
            self.root.after(0, lambda: self._set_status(f"Error: {exc}"))

    def _on_fetched(self, calls: list[dict[str, Any]]) -> None:
        self._calls = calls
        self._populate()

    def _predicate(self) -> Callable[[str], bool]:
        for label, pred in FILTERS:
            if label == self.filter:
                return pred
        return lambda _t: True

    def _populate(self) -> None:
        if self.inner is None or not self.inner.winfo_exists():
            return
        for child in self.inner.winfo_children():
            child.destroy()
        self._rows.clear()

        pred = self._predicate()
        shown = [c for c in self._calls if pred(c.get("call_type", "unknown"))]
        unseen = sum(1 for c in shown if not c.get("seen"))

        if not shown:
            tk.Label(
                self.inner, text="No calls to show.", bg=theme.BG_CARD,
                fg=theme.FG_DIM, font=(theme.FONT, 11), pady=40,
            ).pack(fill="x")
        else:
            for i, call in enumerate(shown[:MAX_ROWS]):
                self._render_row(call, first=(i == 0))

        total = len(shown)
        capped = "" if total <= MAX_ROWS else f"  ·  showing first {MAX_ROWS}"
        self._set_status(
            f"{total} call{'s' if total != 1 else ''}"
            + (f"  ·  {unseen} unseen" if unseen else "  ·  all seen")
            + capped
        )
        if self.canvas is not None:
            self.canvas.yview_moveto(0.0)

    def _render_row(self, call: dict[str, Any], first: bool) -> None:
        assert self.inner is not None
        call_type = call.get("call_type", "unknown")
        accent = theme.type_color(call_type)
        name = call.get("caller_name") or call.get("number") or "Unknown"
        number = call.get("number", "")
        type_label = CALL_TYPE_LABELS.get(call_type, "Call")
        seen = bool(call.get("seen"))

        if not first:
            tk.Frame(self.inner, bg=theme.STROKE, height=1).pack(fill="x", padx=14)

        row = tk.Frame(self.inner, bg=theme.BG_CARD)
        row.pack(fill="x")
        pad = tk.Frame(row, bg=theme.BG_CARD)
        pad.pack(fill="x", padx=14, pady=9)

        # Avatar
        av_sz = theme.px(42)
        av = tk.Canvas(pad, width=av_sz, height=av_sz, bg=theme.BG_CARD,
                       highlightthickness=0)
        av.pack(side="left")
        av.create_oval(2, 2, av_sz - 2, av_sz - 2, fill=accent, outline="")
        av.create_text(av_sz / 2, av_sz / 2, text=theme.initial_of(name),
                       fill="#ffffff", font=(theme.FONT_SEMI, 15))

        # Name + subtitle
        textcol = tk.Frame(pad, bg=theme.BG_CARD)
        textcol.pack(side="left", fill="x", expand=True, padx=(13, 8))
        name_font = (theme.FONT_SEMI, 11) if seen else (theme.FONT_SEMI, 11)
        tk.Label(textcol, text=name, bg=theme.BG_CARD, fg=theme.FG,
                 font=name_font, anchor="w").pack(fill="x")
        sub = number if (number and number != name) else type_label
        tk.Label(textcol, text=sub, bg=theme.BG_CARD, fg=theme.FG_SUBTLE,
                 font=(theme.FONT, 9), anchor="w").pack(fill="x")

        # Right: type badge + time + unseen dot
        rightcol = tk.Frame(pad, bg=theme.BG_CARD)
        rightcol.pack(side="right")
        badge_row = tk.Frame(rightcol, bg=theme.BG_CARD)
        badge_row.pack(anchor="e")
        if not seen:
            tk.Label(badge_row, text="●", bg=theme.BG_CARD, fg=theme.BRAND,
                     font=(theme.FONT, 9)).pack(side="right", padx=(6, 0))
        tk.Label(badge_row, text=type_label, bg=theme.BG_CARD, fg=accent,
                 font=(theme.FONT_SEMI, 9)).pack(side="right")
        tk.Label(rightcol, text=theme.relative_time(call.get("call_time", "")),
                 bg=theme.BG_CARD, fg=theme.FG_DIM, font=(theme.FONT, 9),
                 anchor="e").pack(anchor="e", pady=(2, 0))

        # Interactions: hover highlight (recolors the whole row) + click to seen.
        def recolor(color: str) -> None:
            for w in _descendants(row):
                try:
                    w.configure(bg=color)
                except tk.TclError:
                    pass

        cid = call.get("id")
        for w in _descendants(row):
            w.bind("<Enter>", lambda _e: recolor(theme.BG_HOVER))
            w.bind("<Leave>", lambda _e: recolor(theme.BG_CARD))
            if isinstance(cid, int) and not seen:
                w.configure(cursor="hand2")
                w.bind("<Button-1>", lambda _e, c=cid: self._mark_seen(c))
            self._bind_wheel(w)

        if isinstance(cid, int):
            self._rows[cid] = row

    # --- interactions ----------------------------------------------------
    def _mark_seen(self, call_id: int) -> None:
        # Optimistic local update, then push.
        for call in self._calls:
            if call.get("id") == call_id:
                call["seen"] = True
                break
        self._populate()

        def worker() -> None:
            try:
                self.api.mark_seen(call_id)
            except Exception as exc:  # noqa: BLE001
                log.warning("mark_seen(%s) failed: %s", call_id, exc)

        threading.Thread(target=worker, daemon=True).start()

    def apply_seen(self, call_id: int) -> None:
        """Update the list when another client marked a call seen."""
        changed = False
        for call in self._calls:
            if call.get("id") == call_id and not call.get("seen"):
                call["seen"] = True
                changed = True
                break
        if changed and self.win is not None and self.win.winfo_exists():
            self._populate()

    def _set_status(self, text: str) -> None:
        if self.status_var is not None:
            self.status_var.set(text)

    # --- scrolling -------------------------------------------------------
    def _bind_wheel(self, widget: tk.Widget) -> None:
        widget.bind("<MouseWheel>", self._on_wheel)

    def _on_wheel(self, event: tk.Event) -> None:
        if self.canvas is not None:
            self.canvas.yview_scroll(int(-event.delta / 120), "units")


def _hoverable(widget: tk.Label, base: str, hover: str) -> None:
    widget.bind("<Enter>", lambda _e: widget.configure(bg=hover), add="+")
    widget.bind("<Leave>", lambda _e: widget.configure(bg=base), add="+")


def _descendants(widget: tk.Widget) -> list[tk.Widget]:
    """A widget plus every widget nested under it (depth-first)."""
    out = [widget]
    for child in widget.winfo_children():
        out.extend(_descendants(child))
    return out
