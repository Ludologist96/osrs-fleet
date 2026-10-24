@echo off
rem Shuts Windows down at 4:20, after tonight's OSRS bot runs end (they stop and log out at ~4:15).
rem To cancel: open a command prompt and run  shutdown /a
for /f %%s in ('powershell -NoProfile -Command "$t=(Get-Date).Date.AddHours(4).AddMinutes(20); if($t -lt (Get-Date)){$t=$t.AddDays(1)}; [int]($t-(Get-Date)).TotalSeconds"') do set SECS=%%s
shutdown /s /t %SECS% /c "The PC shuts down at 4:20, after the OSRS bot runs. To cancel: shutdown /a"
echo Shutdown scheduled in %SECS% seconds (at 4:20). To cancel: shutdown /a
timeout /t 10
