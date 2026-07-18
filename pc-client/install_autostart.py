"""Register (or remove) a Windows autostart entry for the RingKeeper PC client.

Uses the per-user "Run" registry key
(HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run) so the client starts
at every login. This deliberately does NOT use Task Scheduler: creating an
ONLOGON task requires Administrator rights, which makes it hard for
non-technical users to set up. The HKCU Run key needs no elevation.

Critically — matching the spec's note about the pyw/python environment mismatch
bug — the autostart command uses the pythonw.exe that sits next to the *current*
interpreter (i.e. the venv you ran this script with), NOT whatever `pythonw`
resolves to on PATH. Run this with the same interpreter you installed the
requirements into. The easiest way is to double-click setup.bat, which does this
for you. Manually:

    .venv\\Scripts\\python.exe install_autostart.py install
    .venv\\Scripts\\python.exe install_autostart.py uninstall
    .venv\\Scripts\\python.exe install_autostart.py status
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

VALUE_NAME = "RingKeeperClient"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def pythonw_path() -> Path:
    """pythonw.exe next to the current interpreter (fallback: python.exe)."""
    exe_dir = Path(sys.executable).resolve().parent
    candidate = exe_dir / "pythonw.exe"
    return candidate if candidate.exists() else Path(sys.executable).resolve()


def main_script() -> Path:
    return Path(__file__).resolve().parent / "main.py"


def autostart_command() -> str:
    """The exact command Windows runs at logon: quoted interpreter + script."""
    return f'"{pythonw_path()}" "{main_script()}"'


def install() -> int:
    import winreg  # Windows-only; imported lazily so --help works anywhere.

    command = autostart_command()
    print("Registering autostart (per-user, no admin needed):")
    print("   interpreter:", pythonw_path())
    print("   script:     ", main_script())
    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE
    ) as key:
        winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, command)
    print(f"\nDone. '{VALUE_NAME}' will start automatically at your next login.")
    print("It is NOT running yet — start it now by double-clicking start.bat,")
    print("or log out and back in.")
    return 0


def uninstall() -> int:
    import winreg

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.DeleteValue(key, VALUE_NAME)
        print(f"Removed autostart entry '{VALUE_NAME}'.")
        return 0
    except FileNotFoundError:
        print(f"No autostart entry '{VALUE_NAME}' found — nothing to remove.")
        return 0


def status() -> int:
    import winreg

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ
        ) as key:
            value, _ = winreg.QueryValueEx(key, VALUE_NAME)
        print(f"Autostart is INSTALLED for '{VALUE_NAME}':")
        print("   ", value)
        return 0
    except FileNotFoundError:
        print(f"Autostart is NOT installed for '{VALUE_NAME}'.")
        return 1


def main() -> None:
    parser = argparse.ArgumentParser(description="RingKeeper PC client autostart")
    parser.add_argument(
        "action", choices=["install", "uninstall", "status"], nargs="?", default="install"
    )
    args = parser.parse_args()
    if sys.platform != "win32":
        print("This installer targets Windows only.")
        sys.exit(1)
    sys.exit({"install": install, "uninstall": uninstall, "status": status}[args.action]())


if __name__ == "__main__":
    main()
