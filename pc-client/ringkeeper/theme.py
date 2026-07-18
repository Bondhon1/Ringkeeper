"""Shared dark-theme palette and helpers for the PC client UI."""

from __future__ import annotations

from datetime import datetime, timezone

FONT = "Segoe UI"
FONT_SEMI = "Segoe UI Semibold"

# Surfaces (dark) --------------------------------------------------------------
BG_BORDER = "#0c0f16"   # near-black outer edge
BG_CARD = "#1b2130"     # popup / window body
BG_CARD_ALT = "#212838"  # zebra-striped row
BG_ELEV = "#2a3345"     # buttons / inputs
BG_HOVER = "#39445c"    # hover state

# Text -------------------------------------------------------------------------
FG = "#f2f5fa"
FG_SUBTLE = "#93a0b4"
FG_DIM = "#6b7688"

# Per-call-type accent colors --------------------------------------------------
TYPE_COLORS: dict[str, str] = {
    "missed": "#f2555a",
    "rejected": "#f2555a",
    "incoming": "#33b969",
    "outgoing": "#4c8dff",
    "blocked": "#e0a12f",
    "voicemail": "#a06bff",
    "unknown": "#93a0b4",
}
ACCENT = "#f2555a"


def type_color(call_type: str | None) -> str:
    return TYPE_COLORS.get(call_type or "unknown", FG_SUBTLE)


def initial_of(name: str) -> str:
    for ch in name.strip():
        if ch.isalnum():
            return ch.upper()
    return "?"


def relative_time(iso: str) -> str:
    """Human, relative-ish timestamp: '3m ago', 'Today 08:40', 'May 14, 08:40'."""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone()
    except (ValueError, AttributeError):
        return iso or ""
    now = datetime.now(timezone.utc).astimezone()
    delta = (now - dt).total_seconds()
    if 0 <= delta < 60:
        return "just now"
    if 0 <= delta < 3600:
        return f"{int(delta // 60)}m ago"
    if dt.date() == now.date():
        return dt.strftime("Today %H:%M")
    if (now.date() - dt.date()).days == 1:
        return dt.strftime("Yesterday %H:%M")
    if dt.year == now.year:
        return dt.strftime("%b %d, %H:%M")
    return dt.strftime("%b %d %Y, %H:%M")
