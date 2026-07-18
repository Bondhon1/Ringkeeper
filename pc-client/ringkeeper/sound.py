"""Notification sound for fresh call popups.

Uses winsound (Windows stdlib) and always plays asynchronously so it never
blocks the Tk thread. Falls back gracefully: a custom .wav if configured and
present, otherwise a Windows system chime, otherwise a plain message beep.
Silently does nothing on non-Windows or if audio fails.
"""

from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger("ringkeeper.sound")

try:
    import winsound
except ImportError:  # non-Windows
    winsound = None  # type: ignore[assignment]

# System sound aliases to try, in order. "SystemAsterisk" is present on every
# Windows install; the others are nicer when available.
_ALIASES = ("SystemNotification", "SystemAsterisk", "SystemDefault")


def play_notification(sound_file: str | None = None) -> None:
    """Play the notification sound. Never raises."""
    if winsound is None:
        return
    try:
        if sound_file:
            path = Path(sound_file).expanduser()
            if path.exists():
                winsound.PlaySound(
                    str(path), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT
                )
                return
            log.warning("sound_file not found: %s — using system sound", path)

        for alias in _ALIASES:
            try:
                winsound.PlaySound(alias, winsound.SND_ALIAS | winsound.SND_ASYNC)
                return
            except RuntimeError:
                continue
        winsound.MessageBeep(winsound.MB_ICONASTERISK)
    except Exception as exc:  # noqa: BLE001 — audio must never break the app
        log.debug("notification sound failed: %s", exc)
