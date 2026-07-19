"""Shared dark-theme palette and helpers for the PC client UI."""

from __future__ import annotations

from datetime import datetime, timezone

FONT = "Segoe UI"
FONT_SEMI = "Segoe UI Semibold"

# --- DPI scaling --------------------------------------------------------------
# Once the process is DPI-aware (see main._enable_dpi_awareness), Tk draws in
# physical pixels and scales point-based fonts to the display DPI automatically —
# but hard-coded pixel sizes (card widths, avatars, paddings) do NOT scale on
# their own. px() multiplies a logical (96-DPI) pixel value by the display's
# scale factor so those dimensions track the fonts and keep their proportions.
_UI_SCALE = 1.0


def set_ui_scale(root) -> None:
    """Capture the display's scale factor from a live Tk root (1.0 at 96 DPI,
    1.5 at 150%, …). Call once after the root exists and DPI awareness is set."""
    global _UI_SCALE
    try:
        _UI_SCALE = max(1.0, root.winfo_fpixels("1i") / 96.0)
    except Exception:  # noqa: BLE001
        _UI_SCALE = 1.0


def px(value: float) -> int:
    """Scale a logical pixel measurement to the current display."""
    return int(round(value * _UI_SCALE))

# Surfaces (dark) --------------------------------------------------------------
BG_BASE = "#0e1320"     # app background behind cards
BG_BORDER = "#0a0d15"   # near-black outer edge (popup hairline)
BG_CARD = "#171e2e"     # popup / window body
BG_CARD_ALT = "#1c2434"  # zebra-striped row
BG_ELEV = "#232c40"     # buttons / inputs
BG_HOVER = "#2f3a52"    # hover state
STROKE = "#2a3446"      # hairline separators / card outlines

# Brand ------------------------------------------------------------------------
BRAND = "#6b8afd"       # accent / primary actions
BRAND_DIM = "#38507f"   # muted brand (pressed/hover)

# Text -------------------------------------------------------------------------
FG = "#eef1f7"
FG_SUBTLE = "#aeb7c7"
FG_DIM = "#7e8798"

# Per-call-type accent colors --------------------------------------------------
TYPE_COLORS: dict[str, str] = {
    "missed": "#f2555a",
    "whatsapp_missed": "#f2555a",
    "rejected": "#f2555a",
    "incoming": "#33b969",
    "whatsapp_incoming": "#25d366",  # WhatsApp brand green
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
