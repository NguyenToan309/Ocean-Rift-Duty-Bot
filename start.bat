@echo off
REM Homie Medic launcher — double-click to run
REM Forwards all args to start.ps1
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" %*
pause
