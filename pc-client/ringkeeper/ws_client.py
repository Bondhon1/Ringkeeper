"""Auto-reconnecting WebSocket client.

Runs its own asyncio event loop on a background thread and invokes plain
callbacks for each server message and for connection state changes. Callbacks
are called from the WS thread — the GUI code marshals them onto the Tk thread.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from typing import Any, Callable

import websockets

from .config import Config

log = logging.getLogger("ringkeeper.ws")

MessageHandler = Callable[[dict[str, Any]], None]
StatusHandler = Callable[[bool], None]


class WsClient:
    def __init__(
        self,
        config: Config,
        on_message: MessageHandler,
        on_status: StatusHandler | None = None,
    ):
        self.config = config
        self.on_message = on_message
        self.on_status = on_status or (lambda _connected: None)
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="ws-client", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        loop = self._loop
        if loop is not None:
            loop.call_soon_threadsafe(lambda: None)  # wake the loop

    def _run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._connect_forever())
        finally:
            self._loop.close()

    async def _connect_forever(self) -> None:
        # token as a query param — the server accepts either that or a first
        # {"type":"auth"} message.
        uri = f"{self.config.ws_url}?token={self.config.token}"
        backoff = 1.0
        while not self._stop.is_set():
            try:
                async with websockets.connect(uri, ping_interval=20, ping_timeout=20) as ws:
                    log.info("WebSocket connected to %s", self.config.ws_url)
                    self.on_status(True)
                    backoff = 1.0  # reset backoff on a good connection
                    async for raw in ws:
                        self._dispatch(raw)
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001 — reconnect on any failure
                log.warning("WebSocket error: %s", exc)
            finally:
                self.on_status(False)

            if self._stop.is_set():
                break
            # Exponential backoff, capped, so we don't hammer a down server.
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30.0)

    def _dispatch(self, raw: Any) -> None:
        try:
            msg = json.loads(raw)
        except (ValueError, TypeError):
            log.warning("Ignoring non-JSON WS frame: %r", raw)
            return
        if not isinstance(msg, dict):
            return
        try:
            self.on_message(msg)
        except Exception:  # noqa: BLE001 — a bad handler must not kill the socket
            log.exception("on_message handler raised")
