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


def _make_icon_image(connected: bool) -> Image.Image:
    """A simple ring glyph — green when connected, grey when not."""
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    ring = (46, 204, 113, 255) if connected else (150, 150, 150, 255)
    d.ellipse((8, 8, 56, 56), outline=ring, width=8)
    d.ellipse((26, 26, 38, 38), fill=ring)
    return img


class Tray:
    def __init__(
        self,
        on_show_list: Callable[[], None],
        on_quit: Callable[[], None],
    ):
        self.on_show_list = on_show_list
        self.on_quit = on_quit
        self._connected = False
        self.icon = pystray.Icon(
            "ringkeeper",
            icon=_make_icon_image(False),
            title="RingKeeper — connecting…",
            menu=pystray.Menu(
                pystray.MenuItem("Show calls", self._show_list, default=True),
                pystray.MenuItem("Status: connecting…", None, enabled=False),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Quit", self._quit),
            ),
        )

    def _show_list(self, _icon=None, _item=None) -> None:
        self.on_show_list()

    def _quit(self, _icon=None, _item=None) -> None:
        try:
            self.icon.stop()
        finally:
            self.on_quit()

    def set_connected(self, connected: bool) -> None:
        self._connected = connected
        try:
            self.icon.icon = _make_icon_image(connected)
            self.icon.title = "RingKeeper — connected" if connected else "RingKeeper — offline"
            # Rebuild the menu so the status line reflects the new state.
            status = "Status: connected" if connected else "Status: offline"
            self.icon.menu = pystray.Menu(
                pystray.MenuItem("Show calls", self._show_list, default=True),
                pystray.MenuItem(status, None, enabled=False),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Quit", self._quit),
            )
            self.icon.update_menu()
        except Exception as exc:  # noqa: BLE001
            log.debug("tray update failed: %s", exc)

    def run(self) -> None:
        # Blocks — call from the thread you want to own the tray loop.
        self.icon.run()
