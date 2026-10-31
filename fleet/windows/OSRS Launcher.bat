@echo off
rem Opens the OSRS fleet launcher page. Starts the fleet VM first if it is not running
rem (after a restart the logon task normally does this) and waits for the dashboard.
title OSRS Launcher
curl -s -o nul --max-time 2 http://localhost:8000/launcher && goto open
echo Starting the fleet VM...
schtasks /run /tn "OSRS Fleet" >nul 2>&1 || start "" /min wsl.exe -d Ubuntu-24.04 -u root -e sleep infinity
for /l %%i in (1,1,45) do (
    timeout /t 2 /nobreak >nul
    curl -s -o nul --max-time 2 http://localhost:8000/launcher && goto open
)
echo The dashboard did not answer after 90 s. Try "Restart fleet VM.bat".
pause
exit /b 1
:open
start "" http://localhost:8000/launcher
