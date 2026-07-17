"""Load and validate the PC client configuration (Supabase-native).

Config resolution:
  1. RINGKEEPER_CONFIG env var (explicit path), else
  2. config.json next to the project root (pc-client/config.json)
Individual values can be overridden by env vars (handy for the autostart entry):
  RINGKEEPER_SUPABASE_URL / RINGKEEPER_ANON_KEY / RINGKEEPER_EMAIL / RINGKEEPER_PASSWORD
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse, urlunparse

# pc-client/ringkeeper/config.py -> pc-client/
PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Config:
    supabase_url: str
    anon_key: str
    email: str
    password: str
    popup_for: list[str] = field(default_factory=lambda: ["missed"])

    @property
    def base(self) -> str:
        return self.supabase_url.rstrip("/")

    @property
    def rest_url(self) -> str:
        return f"{self.base}/rest/v1"

    @property
    def auth_url(self) -> str:
        return f"{self.base}/auth/v1"

    @property
    def realtime_url(self) -> str:
        """ws(s)://<host>/realtime/v1 — what AsyncRealtimeClient expects."""
        parsed = urlparse(self.base)
        scheme = "wss" if parsed.scheme == "https" else "ws"
        return urlunparse((scheme, parsed.netloc, "/realtime/v1", "", "", ""))


def _config_path() -> Path:
    override = os.environ.get("RINGKEEPER_CONFIG")
    if override:
        return Path(override).expanduser().resolve()
    return PROJECT_ROOT / "config.json"


def load_config() -> Config:
    path = _config_path()
    data: dict = {}
    if path.exists():
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)

    supabase_url = os.environ.get("RINGKEEPER_SUPABASE_URL") or data.get("supabase_url", "")
    anon_key = os.environ.get("RINGKEEPER_ANON_KEY") or data.get("anon_key", "")
    email = os.environ.get("RINGKEEPER_EMAIL") or data.get("email", "")
    password = os.environ.get("RINGKEEPER_PASSWORD") or data.get("password", "")
    popup_for = data.get("popup_for") or ["missed"]

    missing = [
        name
        for name, value in (
            ("supabase_url", supabase_url),
            ("anon_key", anon_key),
            ("email", email),
            ("password", password),
        )
        if not value or str(value).startswith("paste-") or str(value).startswith("your-")
    ]
    if missing:
        raise ValueError(
            "config: missing/placeholder values: "
            + ", ".join(missing)
            + f". Edit {path} (copy from config.example.json) — see supabase/SETUP.md."
        )

    return Config(
        supabase_url=supabase_url,
        anon_key=anon_key,
        email=email,
        password=password,
        popup_for=list(popup_for),
    )
