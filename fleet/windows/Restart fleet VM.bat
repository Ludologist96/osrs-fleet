@echo off
rem Restarts the OSRS fleet's Linux VM so new .wslconfig settings (RAM / CPU) take effect.
rem Bots stop; RuneLite starts again and the accounts need launching again.
echo Stopping the fleet VM...
wsl --shutdown
timeout /t 8 /nobreak >nul
echo Starting it again...
schtasks /run /tn "OSRS Fleet" >nul 2>&1 || start "" /min wsl.exe -d Ubuntu-24.04 -u root -e sleep infinity
timeout /t 20 /nobreak >nul
start "" http://localhost:8000/launcher
echo Done. You can close this window.
timeout /t 5 >nul
