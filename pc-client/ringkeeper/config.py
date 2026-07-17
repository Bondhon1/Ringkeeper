"""Load and validate the PC client configuration.

Config resolution order:
  1. RINGKEEPER_CONFIG env var (explicit path)
  2. config.json next to the project root (pc-client/config.json)
Values can be overridden by env vars RINGKEEPER_SERVER_URL / RINGKEEPER_TOKEN,
which is handy for the autostart Task Scheduler entry.
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
    server_url: str
    token: str
    popup_for: list[str] = field(default_factory=lambda: ["missed"])

    @property
    def http_base(self) -> str:
        return self.server_url.rstrip("/")

    @property
    def ws_url(self) -> str:
        """Derive the ws(s):// URL for /ws from the http(s) server URL."""
        parsed = urlparse(self.http_base)
        scheme = "wss" if parsed.scheme == "https" else "ws"
        # Rebuild with the ws scheme and the /ws path.
        return urlunparse((scheme, parsed.netloc, "/ws", "", "", ""))


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
    elif not (os.environ.get("RINGKEEPER_SERVER_URL") and os.environ.get("RINGKEEPER_TOKEN")):
        raise FileNotFoundError(
            f"No config found at {path}. Copy config.example.json to config.json "
            f"and fill in server_url + token (or set RINGKEEPER_SERVER_URL / RINGKEEPER_TOKEN)."
        )

    server_url = os.environ.get("RINGKEEPER_SERVER_URL") or data.get("server_url", "")
    token = os.environ.get("RINGKEEPER_TOKEN") or data.get("token", "")
    popup_for = data.get("popup_for") or ["missed"]

    if not server_url:
        raise ValueError("config: server_url is required")
    if not token or token.startswith("paste-the-same"):
        raise ValueError("config: a real token is required (copy the server's SHARED_TOKEN)")

    return Config(server_url=server_url, token=token, popup_for=list(popup_for))
