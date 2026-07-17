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

NewCallHandler = Callable[[dict[str, Any]], None]
StatusHandler = Callable[[bool], None]

TOKEN_RECHECK_SECONDS = 60


class SupabaseRealtime:
    def __init__(
        self,
        config: Config,
        tokens: TokenManager,
        on_new_call: NewCallHandler,
        on_status: StatusHandler | None = None,
    ):
        self.config = config
        self.tokens = tokens
        self.on_new_call = on_new_call
        self.on_status = on_status or (lambda _c: None)
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
                    callback=self._on_insert,
                    table="calls",
                    schema="public",
                )
                await channel.subscribe()

                log.info("Subscribed to Realtime INSERTs on public.calls")
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

    def _on_insert(self, payload: dict[str, Any]) -> None:
        record = (payload.get("data") or {}).get("record")
        if not isinstance(record, dict):
            return
        try:
            self.on_new_call(record)
        except Exception:  # noqa: BLE001 — a bad handler must not kill the socket
            log.exception("on_new_call handler raised")
