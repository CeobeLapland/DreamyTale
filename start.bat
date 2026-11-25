@echo off
rem DreamyTale / PaperTale - one-click launcher.
rem Double-click to start, or pass options: start.bat -Offline -Port 8011
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" %*
if errorlevel 1 pause
endlocal
