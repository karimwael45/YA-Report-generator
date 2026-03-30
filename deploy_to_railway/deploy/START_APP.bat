@echo off
title IGCSE Math Report Generator — Mr. Youssef Ahmed
color 1F
echo.
echo  ============================================================
echo   IGCSE Math Report Card Generator
echo   Mr. Youssef Ahmed - Cambridge IGCSE Course
echo  ============================================================
echo.
echo  Starting... A browser window will open automatically.
echo  To close the app, close this window.
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo  ERROR: Python is not installed.
    echo  Download from: https://www.python.org/downloads/
    echo  Tick "Add Python to PATH" during installation.
    pause & exit /b
)

echo  Checking packages...
python -m pip install flask reportlab --quiet --no-warn-script-location 2>nul
echo  Launching app...
start "" python "%~dp0app.py"
timeout /t 2 /nobreak >nul
start "" "http://127.0.0.1:5050"
echo  Running at: http://127.0.0.1:5050
echo  Press any key to STOP.
pause >nul
taskkill /f /im python.exe >nul 2>&1
