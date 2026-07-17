"""RingKeeper PC client entry point (Supabase-native).

Threading model:
  - Main thread owns the (withdrawn) Tk root and runs the GUI event loop.
  - SupabaseRealtime runs an asyncio loop on its own thread; INSERT events are
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

from ringkeeper.api import SupabaseRest
from ringkeeper.auth import AuthError, TokenManager
from ringkeeper.config import load_config
from ringkeeper.list_window import ListWindow
from ringkeeper.popup import PopupManager
from ringkeeper.realtime import SupabaseRealtime
from ringkeeper.tray import Tray

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
        self.tokens = TokenManager(self.config)
        # Validate credentials up front so a bad email/password fails loudly
        # instead of silently never connecting. Network errors are tolerated —
        # the Realtime thread will keep retrying.
        try:
            self.tokens.sign_in()
        except AuthError as exc:
            msg = str(exc)
            if msg.startswith("4"):  # 400/401/403 → credentials/config problem
                raise RuntimeError(
                    f"Supabase sign-in rejected ({msg}). Check email/password and "
                    f"that the account exists (see supabase/SETUP.md)."
                ) from exc
            logging.getLogger("ringkeeper").warning(
                "Initial sign-in failed (%s); will retry in background", msg
            )

        self.api = SupabaseRest(self.config, self.tokens)

        self.root = tk.Tk()
        self.root.withdraw()

        self.popups = PopupManager(self.root, self.api)
        self.list_window = ListWindow(self.root, self.api)
        self.tray = Tray(on_show_list=self._show_list, on_quit=self._quit)
        self.realtime = SupabaseRealtime(
            self.config,
            self.tokens,
            on_new_call=self._on_new_call,
            on_status=self._on_status,
        )
        self._popup_types = set(self.config.popup_for)

    # --- lifecycle -------------------------------------------------------
    def run(self) -> None:
        self.realtime.start()
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
            self.realtime.stop()
        except Exception:  # noqa: BLE001
            pass
        try:
            self.root.quit()
            self.root.destroy()
        except tk.TclError:
            pass

    # --- tray callbacks (tray thread) ------------------------------------
    def _show_list(self) -> None:
        self.root.after(0, self.list_window.open)

    # --- realtime callbacks (realtime thread) ----------------------------
    def _on_new_call(self, record: dict[str, Any]) -> None:
        self.root.after(0, lambda: self._handle_new_call(record))

    def _on_status(self, connected: bool) -> None:
        self.tray.set_connected(connected)

    # --- runs on Tk thread ----------------------------------------------
    def _handle_new_call(self, record: dict[str, Any]) -> None:
        if record.get("call_type") in self._popup_types:
            self.popups.show(record)
        if self.list_window.win is not None and self.list_window.win.winfo_exists():
            self.list_window.refresh()


def main() -> None:
    setup_logging()
    try:
        app = App()
    except Exception as exc:  # noqa: BLE001 — surface config/auth errors clearly
        logging.getLogger("ringkeeper").error("Startup failed: %s", exc)
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
