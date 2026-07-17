"""RingKeeper PC client entry point.

Threading model:
  - Main thread owns the (withdrawn) Tk root and runs the GUI event loop.
  - WsClient runs an asyncio loop on its own thread; incoming messages are
    marshalled onto the Tk thread with root.after(0, ...).
  - The tray icon owns its own thread (pystray's message loop).

Run with pythonw.exe (no console) in production; python.exe while debugging.
"""

from __future__ import annotations

import logging
import sys
import threading
import tkinter as tk
from pathlib import Path
from typing import Any

from ringkeeper.api import ApiClient
from ringkeeper.config import load_config
from ringkeeper.list_window import ListWindow
from ringkeeper.popup import PopupManager
from ringkeeper.tray import Tray
from ringkeeper.ws_client import WsClient

LOG_PATH = Path(__file__).resolve().parent / "ringkeeper-client.log"


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(LOG_PATH, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


class App:
    def __init__(self) -> None:
        self.config = load_config()
        self.api = ApiClient(self.config)

        # Hidden root — we only ever show Toplevels (popups, list window).
        self.root = tk.Tk()
        self.root.withdraw()

        self.popups = PopupManager(self.root, self.api)
        self.list_window = ListWindow(self.root, self.api)
        self.tray = Tray(on_show_list=self._show_list, on_quit=self._quit)
        self.ws = WsClient(
            self.config,
            on_message=self._on_ws_message,
            on_status=self._on_ws_status,
        )
        self._popup_types = set(self.config.popup_for)

    # --- lifecycle -------------------------------------------------------
    def run(self) -> None:
        self.ws.start()
        threading.Thread(target=self.tray.run, name="tray", daemon=True).start()
        self.root.protocol("WM_DELETE_WINDOW", self._quit)
        logging.getLogger("ringkeeper").info(
            "PC client started. Popups for: %s", sorted(self._popup_types)
        )
        try:
            self.root.mainloop()
        except KeyboardInterrupt:
            self._quit()

    def _quit(self) -> None:
        logging.getLogger("ringkeeper").info("Shutting down PC client")
        try:
            self.ws.stop()
        except Exception:  # noqa: BLE001
            pass
        try:
            self.root.quit()
            self.root.destroy()
        except tk.TclError:
            pass

    # --- tray callbacks (called from tray thread) ------------------------
    def _show_list(self) -> None:
        self.root.after(0, self.list_window.open)

    # --- ws callbacks (called from ws thread) ----------------------------
    def _on_ws_message(self, msg: dict[str, Any]) -> None:
        self.root.after(0, lambda: self._handle_message(msg))

    def _on_ws_status(self, connected: bool) -> None:
        self.tray.set_connected(connected)

    # --- runs on Tk thread ----------------------------------------------
    def _handle_message(self, msg: dict[str, Any]) -> None:
        mtype = msg.get("type")
        data = msg.get("data")
        if mtype == "new_call" and isinstance(data, dict):
            if data.get("call_type") in self._popup_types:
                self.popups.show(data)
            # Keep an open list window fresh.
            if self.list_window.win is not None and self.list_window.win.winfo_exists():
                self.list_window.refresh()
        elif mtype == "call_seen" and isinstance(data, dict):
            cid = data.get("id")
            if isinstance(cid, int):
                self.list_window.apply_seen(cid)


def main() -> None:
    setup_logging()
    try:
        app = App()
    except Exception as exc:  # noqa: BLE001 — surface config errors clearly
        logging.getLogger("ringkeeper").error("Startup failed: %s", exc)
        # Also show a dialog so a double-clicked pythonw launch isn't silent.
        try:
            import tkinter.messagebox as mb

            r = tk.Tk()
            r.withdraw()
            mb.showerror("RingKeeper", f"Startup failed:\n{exc}")
            r.destroy()
        except Exception:  # noqa: BLE001
            pass
        sys.exit(1)
    app.run()


if __name__ == "__main__":
    main()
