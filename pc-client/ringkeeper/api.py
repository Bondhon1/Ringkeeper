"""Thin REST client for the RingKeeper server (used by the list window)."""

from __future__ import annotations

from typing import Any

import requests

from .config import Config

# Human-friendly labels + an ordering for call types in the UI.
CALL_TYPE_LABELS: dict[str, str] = {
    "missed": "Missed",
    "rejected": "Rejected",
    "incoming": "Incoming",
    "outgoing": "Outgoing",
    "blocked": "Blocked",
    "voicemail": "Voicemail",
    "unknown": "Unknown",
}


class ApiClient:
    def __init__(self, config: Config, timeout: float = 10.0):
        self.config = config
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.config.token}"}

    def list_calls(
        self,
        since: str | None = None,
        call_type: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": limit}
        if since:
            params["since"] = since
        if call_type:
            params["type"] = call_type
        resp = requests.get(
            f"{self.config.http_base}/api/calls",
            headers=self._headers(),
            params=params,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json().get("calls", [])

    def mark_seen(self, call_id: int) -> dict[str, Any]:
        resp = requests.patch(
            f"{self.config.http_base}/api/calls/{call_id}/seen",
            headers=self._headers(),
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json().get("call", {})
