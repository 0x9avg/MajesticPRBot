@echo off
chcp 65001 >nul
echo ========================================
echo Starting MajesticPRBot Project
echo ========================================
echo.

REM Get the directory where this script is located
set "PROJECT_ROOT=%~dp0"
cd /d "%PROJECT_ROOT%"

echo Starting API Service...
start "API Service" cmd /k "cd services\api && python main.py"
timeout /t 2 /nobreak >nul

echo Starting Discord Bot...
start "Discord Bot" cmd /k "cd services\discord_bot && python main.py"
timeout /t 2 /nobreak >nul

echo Starting Twitch Bot...
start "Twitch Bot" cmd /k "cd services\twitch_bot && python main.py"
timeout /t 2 /nobreak >nul

echo Starting Web Frontend...
start "Web Frontend" cmd /k "cd web && npm install && npm run dev"

echo.
echo ========================================
echo All services started!
echo ========================================
echo Close this window when done.
pause
