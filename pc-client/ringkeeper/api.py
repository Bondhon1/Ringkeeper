"""PostgREST client for the Supabase `calls` table (used by the list + popups)."""

from __future__ import annotations

from typing import Any

import requests

from .auth import TokenManager
from .config import Config

# Human-friendly labels + display order for call types in the UI.
CALL_TYPE_LABELS: dict[str, str] = {
    "missed": "Missed",
    "whatsapp_missed": "WA Missed",
    "rejected": "Rejected",
    "incoming": "Incoming",
    "whatsapp_incoming": "WA Incoming",
    "outgoing": "Outgoing",
    "blocked": "Blocked",
    "voicemail": "Voicemail",
    "unknown": "Unknown",
}


class SupabaseRest:
    def __init__(self, config: Config, tokens: TokenManager, timeout: float = 15.0):
        self.config = config
        self.tokens = tokens
        self.timeout = timeout

    def _headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers = {
            "apikey": self.config.anon_key,
            "Authorization": f"Bearer {self.tokens.access_token()}",
        }
        if extra:
            headers.update(extra)
        return headers

    def list_calls(
        self,
        since: str | None = None,
        call_type: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "select": "*",
            "order": "call_time.desc",
            "limit": limit,
        }
        if call_type:
            params["call_type"] = f"eq.{call_type}"
        if since:
            params["call_time"] = f"gte.{since}"
        resp = requests.get(
            f"{self.config.rest_url}/calls",
            headers=self._headers(),
            params=params,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def mark_seen(self, call_id: int) -> dict[str, Any]:
        resp = requests.patch(
            f"{self.config.rest_url}/calls",
            headers=self._headers(
                {"Content-Type": "application/json", "Prefer": "return=representation"}
            ),
            params={"id": f"eq.{call_id}"},
            json={"seen": True},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        rows = resp.json()
        return rows[0] if rows else {}
