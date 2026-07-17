"""Supabase Auth (GoTrue) token manager.

Signs in the single shared account with email + password and keeps a valid
access-token (JWT) available, refreshing it before it expires. Thread-safe:
both the Realtime thread and the REST calls pull the token through here.
"""

from __future__ import annotations

import logging
import threading
import time

import requests

from .config import Config

log = logging.getLogger("ringkeeper.auth")

# Refresh a bit before the token actually expires.
EXPIRY_SKEW_SECONDS = 60


class AuthError(Exception):
    pass


class TokenManager:
    def __init__(self, config: Config, timeout: float = 15.0):
        self.config = config
        self.timeout = timeout
        self._lock = threading.Lock()
        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._expires_at: float = 0.0

    def sign_in(self) -> None:
        """Initial password login. Raises AuthError on failure."""
        data = self._token_request(
            "password", {"email": self.config.email, "password": self.config.password}
        )
        self._store(data)
        log.info("Signed in to Supabase as %s", self.config.email)

    def access_token(self) -> str:
        """Return a valid JWT, signing in / refreshing as needed."""
        with self._lock:
            now = time.time()
            if self._access_token and now < self._expires_at - EXPIRY_SKEW_SECONDS:
                return self._access_token
            # Need a (re)fresh token.
            if self._refresh_token:
                try:
                    data = self._token_request(
                        "refresh_token", {"refresh_token": self._refresh_token}
                    )
                    self._store(data)
                    return self._access_token  # type: ignore[return-value]
                except AuthError as exc:
                    log.warning("Refresh failed (%s); doing a full sign-in", exc)
            # Fall back to a full sign-in.
            data = self._token_request(
                "password", {"email": self.config.email, "password": self.config.password}
            )
            self._store(data)
            return self._access_token  # type: ignore[return-value]

    # --- internals -------------------------------------------------------
    def _token_request(self, grant_type: str, body: dict) -> dict:
        url = f"{self.config.auth_url}/token?grant_type={grant_type}"
        try:
            resp = requests.post(
                url,
                headers={"apikey": self.config.anon_key, "Content-Type": "application/json"},
                json=body,
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise AuthError(f"network error: {exc}") from exc
        if resp.status_code != 200:
            raise AuthError(f"{resp.status_code}: {resp.text[:200]}")
        return resp.json()

    def _store(self, data: dict) -> None:
        self._access_token = data.get("access_token")
        self._refresh_token = data.get("refresh_token") or self._refresh_token
        if "expires_at" in data:
            self._expires_at = float(data["expires_at"])
        else:
            self._expires_at = time.time() + float(data.get("expires_in", 3600))
        if not self._access_token:
            raise AuthError("no access_token in response")
