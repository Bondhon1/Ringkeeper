@echo off
REM Start the RingKeeper PC client now (runs in the background / system tray).
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo RingKeeper is not set up yet. Please double-click setup.bat first.
    pause
    exit /b 1
)
start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0main.py"
