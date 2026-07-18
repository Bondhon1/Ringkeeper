@echo off
REM Remove the RingKeeper autostart entry (does not delete any files).
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Nothing to do - RingKeeper does not appear to be set up here.
    pause
    exit /b 0
)
"%~dp0.venv\Scripts\python.exe" install_autostart.py uninstall
echo.
echo RingKeeper will no longer start automatically at login.
echo (It may still be running now - use the tray icon to quit it.)
echo.
pause
