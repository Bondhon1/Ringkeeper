"""Supabase Realtime subscriber.

Runs the async Realtime client on its own thread and invokes plain callbacks:
  - on_new_call(record: dict)  for every INSERT into public.calls
  - on_status(connected: bool) on connect/disconnect

The Realtime client auto-reconnects internally; this wraps it in an outer retry
loop for hard failures and refreshes the auth JWT periodically so RLS keeps
letting the subscription through. Callbacks fire on the Realtime thread — the
GUI marshals them onto the Tk thread with root.after.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any, Callable

from realtime import AsyncRealtimeClient

from .auth import TokenManager
from .config import Config

log = logging.getLogger("ringkeeper.realtime")

RecordHandler = Callable[[dict[str, Any]], None]
StatusHandler = Callable[[bool], None]

TOKEN_RECHECK_SECONDS = 60


class SupabaseRealtime:
    def __init__(
        self,
        config: Config,
        tokens: TokenManager,
        on_new_call: RecordHandler,
        on_status: StatusHandler | None = None,
        on_app_state: RecordHandler | None = None,
        on_message: RecordHandler | None = None,
    ):
        self.config = config
        self.tokens = tokens
        self.on_new_call = on_new_call
        self.on_status = on_status or (lambda _c: None)
        self.on_app_state = on_app_state or (lambda _r: None)
        self.on_message = on_message or (lambda _r: None)
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="supabase-realtime", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        loop = self._loop
        if loop is not None:
            loop.call_soon_threadsafe(lambda: None)

    def _run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._connect_forever())
        finally:
            self._loop.close()

    async def _connect_forever(self) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            client: AsyncRealtimeClient | None = None
            try:
                client = AsyncRealtimeClient(
                    self.config.realtime_url,
                    token=self.config.anon_key,
                    auto_reconnect=True,
                )
                await client.connect()
                current_token = self.tokens.access_token()
                await client.set_auth(current_token)

                channel = client.channel("rk-calls")
                channel.on_postgres_changes(
                    "INSERT",
                    callback=self._on_call_insert,
                    table="calls",
                    schema="public",
                )
                # app_state changes (control flag + phone heartbeat): catch INSERT
                # and UPDATE — the phone creates the row once, then updates it.
                channel.on_postgres_changes(
                    "*",
                    callback=self._on_app_state,
                    table="app_state",
                    schema="public",
                )
                # Ephemeral WhatsApp messages the phone relays for a one-time popup.
                channel.on_postgres_changes(
                    "INSERT",
                    callback=self._on_message,
                    table="messages",
                    schema="public",
                )
                await channel.subscribe()

                log.info("Subscribed to Realtime on public.calls, app_state, messages")
                self.on_status(True)
                backoff = 1.0

                # Keep the loop alive; refresh the JWT before it expires.
                while not self._stop.is_set():
                    await asyncio.sleep(TOKEN_RECHECK_SECONDS)
                    new_token = self.tokens.access_token()
                    if new_token != current_token:
                        current_token = new_token
                        await client.set_auth(new_token)
                        log.debug("Refreshed Realtime auth token")
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001 — reconnect on any failure
                log.warning("Realtime error: %s", exc)
            finally:
                self.on_status(False)
                if client is not None:
                    try:
                        await client.close()
                    except Exception:  # noqa: BLE001
                        pass

            if self._stop.is_set():
                break
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30.0)

    @staticmethod
    def _record(payload: dict[str, Any]) -> dict[str, Any] | None:
        record = (payload.get("data") or {}).get("record")
        return record if isinstance(record, dict) else None

    def _on_call_insert(self, payload: dict[str, Any]) -> None:
        record = self._record(payload)
        if record is None:
            return
        try:
            self.on_new_call(record)
        except Exception:  # noqa: BLE001 — a bad handler must not kill the socket
            log.exception("on_new_call handler raised")

    def _on_app_state(self, payload: dict[str, Any]) -> None:
        record = self._record(payload)
        if record is None:
            return
        try:
            self.on_app_state(record)
        except Exception:  # noqa: BLE001
            log.exception("on_app_state handler raised")

    def _on_message(self, payload: dict[str, Any]) -> None:
        record = self._record(payload)
        if record is None:
            return
        try:
            self.on_message(record)
        except Exception:  # noqa: BLE001
            log.exception("on_message handler raised")
