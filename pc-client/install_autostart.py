"""Register (or remove) a Windows autostart entry for the RingKeeper PC client.

Uses Task Scheduler (ONLOGON) so the client comes back after every login.

Critically — matching the spec's note about the pyw/python environment mismatch
bug — the scheduled action uses the pythonw.exe that sits next to the *current*
interpreter (i.e. the venv you ran this script with), NOT whatever `pythonw`
resolves to on PATH. Run this with the same interpreter you installed the
requirements into:

    .venv\\Scripts\\python.exe install_autostart.py install
    .venv\\Scripts\\python.exe install_autostart.py uninstall
    .venv\\Scripts\\python.exe install_autostart.py status
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

TASK_NAME = "RingKeeperClient"


def pythonw_path() -> Path:
    """pythonw.exe next to the current interpreter (fallback: python.exe)."""
    exe_dir = Path(sys.executable).resolve().parent
    candidate = exe_dir / "pythonw.exe"
    return candidate if candidate.exists() else Path(sys.executable).resolve()


def main_script() -> Path:
    return Path(__file__).resolve().parent / "main.py"


def install() -> int:
    pyw = pythonw_path()
    script = main_script()
    # /TR value: quoted interpreter + quoted script. schtasks wants the whole
    # thing as one argument, with inner quotes.
    run = f'"{pyw}" "{script}"'
    cmd = [
        "schtasks", "/Create",
        "/TN", TASK_NAME,
        "/TR", run,
        "/SC", "ONLOGON",
        "/RL", "LIMITED",
        "/F",
    ]
    print("Registering Task Scheduler entry:")
    print("   interpreter:", pyw)
    print("   script:     ", script)
    result = subprocess.run(cmd, capture_output=True, text=True)
    sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)
    if result.returncode == 0:
        print(f"\nDone. '{TASK_NAME}' will start at next logon.")
        print("Start it now with:  schtasks /Run /TN", TASK_NAME)
    return result.returncode


def uninstall() -> int:
    result = subprocess.run(
        ["schtasks", "/Delete", "/TN", TASK_NAME, "/F"],
        capture_output=True, text=True,
    )
    sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)
    return result.returncode


def status() -> int:
    result = subprocess.run(
        ["schtasks", "/Query", "/TN", TASK_NAME, "/V", "/FO", "LIST"],
        capture_output=True, text=True,
    )
    sys.stdout.write(result.stdout or result.stderr)
    return result.returncode


def main() -> None:
    parser = argparse.ArgumentParser(description="RingKeeper PC client autostart")
    parser.add_argument(
        "action", choices=["install", "uninstall", "status"], nargs="?", default="install"
    )
    args = parser.parse_args()
    if sys.platform != "win32":
        print("This installer targets Windows Task Scheduler only.")
        sys.exit(1)
    sys.exit({"install": install, "uninstall": uninstall, "status": status}[args.action]())


if __name__ == "__main__":
    main()
