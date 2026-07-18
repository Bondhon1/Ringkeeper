"""System tray icon (pystray). Runs on its own thread.

Menu actions marshal back to the Tk thread via the callbacks passed in, which
are expected to be thread-safe (they use root.after under the hood).
"""

from __future__ import annotations

import logging
from typing import Callable

import pystray
from PIL import Image, ImageDraw

log = logging.getLogger("ringkeeper.tray")

# Icon ring colors per state.
_GREEN = (46, 204, 113, 255)   # connected, monitoring on, phone alive
_AMBER = (230, 160, 30, 255)   # paused (shared off-switch) or phone inactive
_GREY = (150, 150, 150, 255)   # not connected to Supabase


def _make_icon_image(color: tuple[int, int, int, int]) -> Image.Image:
    """A simple ring glyph in the given state color."""
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((8, 8, 56, 56), outline=color, width=8)
    d.ellipse((26, 26, 38, 38), fill=color)
    return img


class Tray:
    def __init__(
        self,
        on_show_list: Callable[[], None],
        on_quit: Callable[[], None],
        on_test: Callable[[], None] | None = None,
        on_toggle: Callable[[], None] | None = None,
    ):
        self.on_show_list = on_show_list
        self.on_quit = on_quit
        self.on_test = on_test or (lambda: None)
        self.on_toggle = on_toggle or (lambda: None)
        self._connected = False
        self._monitoring_on = True
        self._phone_active = True
        self.icon = pystray.Icon(
            "ringkeeper",
            icon=_make_icon_image(_GREY),
            title="RingKeeper — connecting…",
            menu=self._build_menu("Status: connecting…"),
        )

    def _build_menu(self, status: str) -> "pystray.Menu":
        toggle_label = "Turn off (pause both)" if self._monitoring_on else "Turn on (resume both)"
        return pystray.Menu(
            pystray.MenuItem("Show calls", self._show_list, default=True),
            pystray.MenuItem(toggle_label, self._toggle),
            pystray.MenuItem("Send test popup", self._test),
            pystray.MenuItem(status, None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", self._quit),
        )

    def _show_list(self, _icon=None, _item=None) -> None:
        self.on_show_list()

    def _test(self, _icon=None, _item=None) -> None:
        self.on_test()

    def _toggle(self, _icon=None, _item=None) -> None:
        self.on_toggle()

    def _quit(self, _icon=None, _item=None) -> None:
        try:
            self.icon.stop()
        finally:
            self.on_quit()

    def set_connected(self, connected: bool) -> None:
        self._connected = connected
        self._refresh()

    def set_state(self, connected: bool, monitoring_on: bool, phone_active: bool) -> None:
        self._connected = connected
        self._monitoring_on = monitoring_on
        self._phone_active = phone_active
        self._refresh()

    def _refresh(self) -> None:
        if not self._connected:
            color, status, title = _GREY, "offline", "RingKeeper — offline"
        elif not self._monitoring_on:
            color, status, title = _AMBER, "paused (off)", "RingKeeper — paused"
        elif not self._phone_active:
            color, status, title = _AMBER, "phone inactive", "RingKeeper — phone inactive"
        else:
            color, status, title = _GREEN, "watching", "RingKeeper — connected"
        try:
            self.icon.icon = _make_icon_image(color)
            self.icon.title = title
            self.icon.menu = self._build_menu(f"Status: {status}")
            self.icon.update_menu()
        except Exception as exc:  # noqa: BLE001
            log.debug("tray update failed: %s", exc)

    def run(self) -> None:
        # Blocks — call from the thread you want to own the tray loop.
        self.icon.run()
