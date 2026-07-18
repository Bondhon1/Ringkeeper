@echo off
REM ===================================================================
REM  RingKeeper PC client - one-click setup (no administrator needed)
REM  Just double-click this file.
REM ===================================================================
setlocal
cd /d "%~dp0"

echo ============================================
echo   RingKeeper PC client setup
echo ============================================
echo.

REM --- 1. Find a Python to bootstrap the venv -----------------------
set "PYBOOT="
py -3 --version >nul 2>&1 && set "PYBOOT=py -3"
if not defined PYBOOT (
    python --version >nul 2>&1 && set "PYBOOT=python"
)
if not defined PYBOOT (
    echo ERROR: Python is not installed.
    echo Please install Python 3 from https://www.python.org/downloads/
    echo and be sure to tick "Add Python to PATH" during install, then run this again.
    echo.
    pause
    exit /b 1
)

REM --- 2. Create the virtual environment if missing -----------------
if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    %PYBOOT% -m venv .venv
    if errorlevel 1 (
        echo ERROR: Could not create the virtual environment.
        pause
        exit /b 1
    )
)
set "VENV_PY=%~dp0.venv\Scripts\python.exe"

REM --- 3. Install / update dependencies -----------------------------
echo Installing dependencies (this can take a minute)...
"%VENV_PY%" -m pip install --upgrade pip >nul
"%VENV_PY%" -m pip install -r requirements.txt
if errorlevel 1 (
    echo ERROR: Could not install dependencies. Check your internet connection.
    pause
    exit /b 1
)

REM --- 4. Create config.json from the example if missing ------------
if not exist "config.json" (
    if exist "config.example.json" (
        copy /y "config.example.json" "config.json" >nul
        echo.
        echo A new config.json was created from the example.
        echo IMPORTANT: open config.json and fill in your details before use.
        echo.
    )
)

REM --- 5. Register autostart (per-user, no admin) -------------------
echo Registering autostart at login...
"%VENV_PY%" install_autostart.py install
if errorlevel 1 (
    echo ERROR: Could not register autostart.
    pause
    exit /b 1
)

REM --- 6. Offer to start it now -------------------------------------
echo.
set /p STARTNOW="Start RingKeeper now? [Y/n] "
if /i "%STARTNOW%"=="n" goto done
start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0main.py"
echo RingKeeper started. Look for its icon in the system tray.

:done
echo.
echo All set. RingKeeper will start automatically every time you log in.
echo.
pause
endlocal
