# OSRS fleet - Windows side setup.
#
# Run in PowerShell *as Administrator*:
#   powershell -ExecutionPolicy Bypass -File D:\OSRS\osrs-cv-bot-main\fleet\windows\setup-windows.ps1
#
# What it does:
#   1. Installs WSL2 + Ubuntu 24.04 if missing (asks you to reboot / create a user once).
#   2. Gives the Linux VM enough RAM and CPU for 8 RuneLite clients (.wslconfig).
#   3. Adds a hidden logon task that keeps the VM running while you are logged in.
#   4. Optionally stops the PC from going to sleep (bots stop when it sleeps).

$ErrorActionPreference = "Stop"
$Distro = "Ubuntu-24.04"

function Say($msg) { Write-Host "`n==> $msg" -ForegroundColor Green }

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "Please run this in PowerShell opened with 'Run as administrator'." -ForegroundColor Red
    exit 1
}

# ------------------------------------------------------------------ 1. WSL + Ubuntu
Say "Checking WSL"
$wslOk = $true
try { wsl.exe --status *> $null; if ($LASTEXITCODE -ne 0) { $wslOk = $false } } catch { $wslOk = $false }
if (-not $wslOk) {
    Say "Installing WSL (Windows will need a restart)"
    wsl.exe --install --no-distribution
    Write-Host "`nRestart the PC, then run this script again." -ForegroundColor Yellow
    exit 0
}
wsl.exe --update | Out-Null

$distros = (wsl.exe --list --quiet) -replace "`0", "" | Where-Object { $_.Trim() -ne "" }
if (-not ($distros -contains $Distro)) {
    Say "Installing $Distro"
    Write-Host "A Ubuntu window will open and ask for a NEW Linux username and password."
    Write-Host "Pick anything (e.g. igor / a password you remember). Then type 'exit' in that window."
    wsl.exe --install -d $Distro
    Write-Host "`nWhen you have created the user and closed Ubuntu, run this script again." -ForegroundColor Yellow
    exit 0
}

# ------------------------------------------------------------------ 2. .wslconfig
Say "Sizing the Linux VM"
$ramGB = [math]::Floor((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB)
$cores = (Get-CimInstance Win32_Processor | Measure-Object -Property NumberOfLogicalProcessors -Sum).Sum
# Leave room for Windows: give the VM ~65% of RAM (max 48 GB) and all but 2 logical cores.
$vmRam = [math]::Min(48, [math]::Max(8, [math]::Floor($ramGB * 0.65)))
$vmCpu = [math]::Max(2, $cores - 2)
Write-Host "PC: $ramGB GB RAM, $cores logical cores  ->  VM: $vmRam GB RAM, $vmCpu cores"
if ($ramGB -lt 16) {
    Write-Host "Warning: under 16 GB RAM. 8 clients will be tight; lower SLOTS in /etc/osrs/fleet.conf." -ForegroundColor Yellow
}

$cfgPath = Join-Path $env:USERPROFILE ".wslconfig"
if (Test-Path $cfgPath) { Copy-Item $cfgPath "$cfgPath.bak" -Force; Write-Host "Old .wslconfig saved as .wslconfig.bak" }
@"
[wsl2]
memory=${vmRam}GB
processors=$vmCpu
swap=4GB
localhostForwarding=true
# The bots use their own virtual screens; WSL's built-in GUI support would
# take over /tmp/.X11-unix and stop them from starting.
guiApplications=false
"@ | Set-Content -Path $cfgPath -Encoding ASCII

# ------------------------------------------------------------------ 3. keep-alive task
Say "Adding logon task 'OSRS Fleet' (keeps the VM running, no window)"
$action = New-ScheduledTaskAction -Execute "conhost.exe" `
    -Argument "--headless wsl.exe -d $Distro -u root -e sleep infinity"
$trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName "OSRS Fleet" -Action $action -Trigger $trigger -Settings $settings `
    -Description "Keeps the OSRS fleet Linux VM running" -Force | Out-Null

# ------------------------------------------------------------------ 4. sleep
$ans = Read-Host "`nStop this PC from sleeping while plugged in? Bots stop when it sleeps. (y/n)"
if ($ans -match '^[yY]') {
    powercfg /change standby-timeout-ac 0
    powercfg /change hibernate-timeout-ac 0
    Write-Host "Sleep disabled on AC power (the screen can still turn off)."
}

# ------------------------------------------------------------------ restart VM with new size, start task
Say "Restarting the VM with the new size"
wsl.exe --shutdown
Start-Sleep -Seconds 3
Start-ScheduledTask -TaskName "OSRS Fleet"

$repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$drive = $repo.Substring(0,1).ToLower()
$linuxRepo = "/mnt/$drive" + ($repo.Substring(2) -replace '\\','/')

Say "Windows part done"
Write-Host @"

Next, open 'Ubuntu 24.04' from the Start menu and run:

    sudo bash $linuxRepo/fleet/linux/install.sh

"@
