@echo off
rem Asks for the same 4:20 shutdown again: Windows answers "already scheduled" (1190) if the first one is set.
for /f %%s in ('powershell -NoProfile -Command "$t=(Get-Date).Date.AddHours(4).AddMinutes(20); if($t -lt (Get-Date)){$t=$t.AddDays(1)}; [int]($t-(Get-Date)).TotalSeconds"') do set SECS=%%s
shutdown /s /t %SECS% /c "The PC shuts down at 4:20, after the OSRS bot runs. To cancel: shutdown /a" > "%~dp0shutdown-check.txt" 2>&1
echo errorlevel=%errorlevel% secs=%SECS% >> "%~dp0shutdown-check.txt"
