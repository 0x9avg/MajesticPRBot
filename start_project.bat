@echo off
chcp 65001 >nul
title MajesticPRBot Launcher
color 0A

:menu
cls
echo ========================================
echo    MajesticPRBot Project Launcher
echo ========================================
echo.
echo Choose launch mode:
echo.
echo [1] Single Terminal (recommended)
echo     All services in one window with colored output
echo.
echo [2] Multiple Terminals
echo     Each service in separate window
echo.
echo [3] Exit
echo.
echo ========================================
choice /C 123 /N /M "Your choice (1-3): "

if errorlevel 3 goto :exit
if errorlevel 2 goto :multiple
if errorlevel 1 goto :single

:single
cls
echo Starting all services in single terminal...
python launcher.py
goto :end

:multiple
cls
echo ========================================
echo Starting MajesticPRBot (Multiple Windows)
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
start "Web Frontend" cmd /k "cd web && npm run dev"

echo.
echo ========================================
echo All services started in separate windows!
echo ========================================
echo You can close this window now.
goto :end

:exit
exit

:end
pause
