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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HEARTBEAT_CHECK_MS = 30000  # how often the PC re-evaluates the phone's heartbeat

from ringkeeper.api import SupabaseRest
from ringkeeper.auth import AuthError, TokenManager
from ringkeeper.config import load_config
from ringkeeper.list_window import ListWindow
from ringkeeper.popup import PopupManager
from ringkeeper.realtime import SupabaseRealtime
from ringkeeper.sound import play_notification
from ringkeeper.tray import Tray

LOG_PATH = Path(__file__).resolve().parent / "ringkeeper-client.log"
log = logging.getLogger("ringkeeper")


def _parse_iso(value: Any) -> "datetime | None":
    """Parse a Postgres timestamptz string into an aware datetime, or None."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


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
        self.tray = Tray(
            on_show_list=self._show_list,
            on_quit=self._quit,
            on_test=self._test_popup,
            on_toggle=self._toggle_monitoring,
        )
        self.realtime = SupabaseRealtime(
            self.config,
            self.tokens,
            on_new_call=self._on_new_call,
            on_status=self._on_status,
            on_app_state=self._on_app_state,
            on_message=self._on_message,
        )
        self._popup_types = set(self.config.popup_for)

        # Shared-control + heartbeat state (all touched on the Tk thread).
        self._connected = False
        self._monitoring_on = True
        self._phone_active = True
        self._last_phone_seen: datetime | None = None
        self._inactive_alerted = False
        # Seed from the current server state so we don't start out wrong.
        self._prime_state()

    def _prime_state(self) -> None:
        """Read the current app_state once at startup (best-effort)."""
        try:
            state = self.api.get_app_state()
        except Exception as exc:  # noqa: BLE001
            log.warning("Could not read app_state at startup: %s", exc)
            return
        if state:
            self._monitoring_on = bool(state.get("monitoring_enabled", True))
            self._last_phone_seen = _parse_iso(state.get("phone_last_seen"))

    # --- lifecycle -------------------------------------------------------
    def run(self) -> None:
        self.realtime.start()
        threading.Thread(target=self.tray.run, name="tray", daemon=True).start()
        self.root.protocol("WM_DELETE_WINDOW", self._quit)
        logging.getLogger("ringkeeper").info(
            "PC client started. Popups for: %s", sorted(self._popup_types)
        )
        self._push_tray_state()
        self.root.after(HEARTBEAT_CHECK_MS, self._check_heartbeat)
        try:
            self.root.mainloop()
        except KeyboardInterrupt:
            self._quit()

    def _quit(self) -> None:
        logging.getLogger("ringkeeper").info("Shutting down PC client")
        # Closing the PC flips the shared off-switch (pauses the phone too),
        # unless disabled in config. Best-effort with a short timeout.
        if self.config.set_off_on_exit:
            try:
                self.api.set_monitoring(False, source="pc_closed")
                log.info("Set monitoring OFF on exit (pc_closed)")
            except Exception as exc:  # noqa: BLE001
                log.warning("Could not set off-on-exit: %s", exc)
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

    def _test_popup(self) -> None:
        sample = {
            "id": -1,
            "caller_name": "Test Caller",
            "number": "+1 555 0100",
            "call_type": next(iter(self._popup_types), "missed"),
            "call_time": datetime.now(timezone.utc).isoformat(),
        }
        self.root.after(0, lambda: self._handle_new_call(sample))

    def _toggle_monitoring(self) -> None:
        """Tray toggle → flip the shared flag from the PC side."""
        self.root.after(0, self._do_toggle_monitoring)

    def _do_toggle_monitoring(self) -> None:
        new_on = not self._monitoring_on
        self._monitoring_on = new_on  # optimistic; realtime will confirm
        self._push_tray_state()

        def worker() -> None:
            try:
                self.api.set_monitoring(new_on, source="pc")
            except Exception as exc:  # noqa: BLE001
                log.warning("Failed to set monitoring=%s: %s", new_on, exc)

        threading.Thread(target=worker, daemon=True).start()

    # --- realtime callbacks (realtime thread) ----------------------------
    def _on_new_call(self, record: dict[str, Any]) -> None:
        self.root.after(0, lambda: self._handle_new_call(record))

    def _on_status(self, connected: bool) -> None:
        self.root.after(0, lambda: self._set_connected(connected))

    def _on_app_state(self, record: dict[str, Any]) -> None:
        self.root.after(0, lambda: self._handle_app_state(record))

    def _on_message(self, record: dict[str, Any]) -> None:
        self.root.after(0, lambda: self._handle_message(record))

    # --- runs on Tk thread ----------------------------------------------
    def _set_connected(self, connected: bool) -> None:
        self._connected = connected
        self._push_tray_state()

    def _handle_app_state(self, record: dict[str, Any]) -> None:
        self._monitoring_on = bool(record.get("monitoring_enabled", self._monitoring_on))
        seen = _parse_iso(record.get("phone_last_seen"))
        if seen is not None:
            self._last_phone_seen = seen
            # A fresh heartbeat clears any standing "inactive" state.
            if self._inactive_alerted:
                log.info("Phone heartbeat resumed")
            self._phone_active = True
            self._inactive_alerted = False
        self._push_tray_state()

    def _handle_message(self, record: dict[str, Any]) -> None:
        sender = record.get("sender") or "WhatsApp"
        preview = record.get("preview") or ""
        self.popups.show_message(sender, preview)
        if self.config.sound:
            play_notification(self.config.sound_file)
        # Ephemeral: delete the row now that it's been shown.
        msg_id = record.get("id")
        if isinstance(msg_id, int):
            threading.Thread(
                target=self._delete_message_safe, args=(msg_id,), daemon=True
            ).start()

    def _delete_message_safe(self, msg_id: int) -> None:
        try:
            self.api.delete_message(msg_id)
        except Exception as exc:  # noqa: BLE001
            log.warning("Failed to delete message %s: %s", msg_id, exc)

    def _push_tray_state(self) -> None:
        self.tray.set_state(self._connected, self._monitoring_on, self._phone_active)

    def _check_heartbeat(self) -> None:
        """Periodic watchdog: raise a 'phone inactive' alert if the heartbeat is stale."""
        try:
            if self._last_phone_seen is not None:
                age = (datetime.now(timezone.utc) - self._last_phone_seen).total_seconds()
                stale = age > self.config.phone_inactive_after_seconds
                if stale and self._phone_active:
                    self._phone_active = False
                    if not self._inactive_alerted:
                        self._inactive_alerted = True
                        log.warning("Phone inactive: no heartbeat for %.0fs", age)
                        self.popups.show_message(
                            "Phone inactive",
                            "RingKeeper hasn't heard from your phone. It may be off, "
                            "offline, or the app was stopped.",
                        )
                    self._push_tray_state()
        finally:
            self.root.after(HEARTBEAT_CHECK_MS, self._check_heartbeat)

    def _handle_new_call(self, record: dict[str, Any]) -> None:
        # Keep an open list window current for every call (any type).
        if self.list_window.win is not None and self.list_window.win.winfo_exists():
            self.list_window.refresh()
        # Respect the shared off-switch: when paused, no popups (the list still
        # updates so history stays complete).
        if not self._monitoring_on:
            return
        # Only pop up + chime for wanted types that are actually recent. This
        # skips the phone's one-time history backfill (old call_time), which
        # would otherwise flood the screen with popups on first run.
        if record.get("call_type") not in self._popup_types:
            return
        if not self._is_fresh(record):
            log.debug("Skipping popup for old call id=%s", record.get("id"))
            return
        self.popups.show(record)
        if self.config.sound:
            play_notification(self.config.sound_file)

    def _is_fresh(self, record: dict[str, Any]) -> bool:
        iso = record.get("call_time")
        if not iso:
            return True
        try:
            dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            return True  # unparseable → fail open (better to show than miss one)
        age = (datetime.now(timezone.utc) - dt).total_seconds()
        return age <= self.config.popup_max_age_seconds


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
