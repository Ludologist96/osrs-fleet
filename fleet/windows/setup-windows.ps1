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
#
# Smaller PC / laptop (everything in one go, run again after each restart it asks for):
#   powershell -ExecutionPolicy Bypass -File <repo>\fleet\windows\setup-windows.ps1 -Slots 4 -VmRamGB 5 -VmCpu 3 -Install
#   -Slots N     slots this PC runs (written to /etc/osrs/fleet.conf before the install)
#   -VmRamGB/-VmCpu  VM size instead of the automatic 65% RAM / all-but-2 cores
#   -Install     also runs fleet/linux/install.sh inside the VM (no Ubuntu window needed)
param([int]$Slots = 0, [int]$VmRamGB = 0, [int]$VmCpu = 0, [switch]$Install)

$ErrorActionPreference = "Stop"
$Distro = "Ubuntu-24.04"

function Say($msg) { Write-Host "`n==> $msg" -ForegroundColor Green }

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "Please run this in PowerShell opened with 'Run as administrator'." -ForegroundColor Red
    exit 1
}

# ------------------------------------------------------------------ 0. virtualization (VT-x / AMD-V)
$cs = Get-CimInstance Win32_ComputerSystem
if (-not $cs.HypervisorPresent) {
    $virt = (Get-CimInstance Win32_Processor | Select-Object -First 1).VirtualizationFirmwareEnabled
    if ($virt -eq $false) {
        Write-Host "Virtualization (Intel VT-x / AMD-V) is OFF in the BIOS. WSL2 needs it." -ForegroundColor Red
        Write-Host "Restart into the BIOS (HP laptops: press F10 at power-on), turn on 'Virtualization Technology', save, then run this again."
        exit 1
    }
}

# ------------------------------------------------------------------ 1. WSL + Ubuntu
Say "Checking WSL"
# Windows 10 has an old built-in wsl.exe that knows neither --status nor --no-distribution:
# turn on the two Windows features first (one restart), then install the current WSL package.
$restart = $false
foreach ($f in 'Microsoft-Windows-Subsystem-Linux','VirtualMachinePlatform') {
    if ((Get-WindowsOptionalFeature -Online -FeatureName $f).State -ne 'Enabled') {
        Say "Turning on the Windows feature $f"
        Enable-WindowsOptionalFeature -Online -FeatureName $f -All -NoRestart | Out-Null
        $restart = $true
    }
}
if ($restart) {
    Write-Host "`nRestart the PC, then run this script again." -ForegroundColor Yellow
    exit 0
}
$ErrorActionPreference = "Continue"
wsl.exe --version *> $null
if ($LASTEXITCODE -ne 0) {
    Say "Installing the current WSL (download, a few minutes)"
    wsl.exe --update --web-download
    wsl.exe --version *> $null
    if ($LASTEXITCODE -ne 0) {
        # Store / --web-download install failed (seen on Windows 10: "module could not be found",
        # "Catastrophic failure"): take the MSI straight from Microsoft's GitHub releases.
        Say "Installing WSL from Microsoft's GitHub release"
        try {
            [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
            $rel = Invoke-RestMethod "https://api.github.com/repos/microsoft/WSL/releases/latest" -Headers @{ 'User-Agent' = 'osrs-fleet' }
            $asset = $rel.assets | Where-Object { $_.name -match 'x64\.msi$' } | Select-Object -First 1
            $msi = Join-Path $env:TEMP $asset.name
            Write-Host "Downloading $($asset.name) ..."
            Invoke-WebRequest $asset.browser_download_url -OutFile $msi -UseBasicParsing
            $log = Join-Path (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path "wsl-install.log"
            $p = Start-Process msiexec.exe -ArgumentList "/i `"$msi`" /qn /norestart /l*v `"$log`"" -Wait -PassThru
            Write-Host "WSL installer exit code: $($p.ExitCode) (log: $log)"
            if ($p.ExitCode -eq 3010) { Write-Host "`nRestart the PC, then run this script again." -ForegroundColor Yellow; exit 0 }
        } catch { Write-Host "Download/install failed: $_" -ForegroundColor Red }
    }
    wsl.exe --version *> $null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "WSL could not be updated. Run the script again; if it repeats, send Claude the output." -ForegroundColor Red
        exit 1
    }
} else {
    wsl.exe --update | Out-Null
}
wsl.exe --set-default-version 2 | Out-Null
$ErrorActionPreference = "Stop"

$distros = (wsl.exe --list --quiet) -replace "`0", "" | Where-Object { $_.Trim() -ne "" }
if (-not ($distros -contains $Distro)) {
    Say "Installing $Distro"
    Write-Host "A Ubuntu window will open and ask for a NEW Linux username and password."
    Write-Host "Pick anything (e.g. igor / a password you remember). Then type 'exit' in that window."
    wsl.exe --install -d $Distro --web-download
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
if ($VmRamGB -gt 0) { $vmRam = $VmRamGB }
if ($VmCpu -gt 0) { $vmCpu = [math]::Min($VmCpu, $cores) }
Write-Host "PC: $ramGB GB RAM, $cores logical cores  ->  VM: $vmRam GB RAM, $vmCpu cores"
if ($ramGB -lt 16 -and $Slots -le 0) {
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
    if ((Get-CimInstance Win32_SystemEnclosure).ChassisTypes | Where-Object { $_ -in 8,9,10,14,31,32 }) {
        # laptop: closing the lid on AC power does nothing (otherwise it sleeps and the bots stop)
        powercfg /setacvalueindex SCHEME_CURRENT SUB_BUTTONS LIDACTION 0
        powercfg /setactive SCHEME_CURRENT
        Write-Host "Laptop: closing the lid on AC power now does nothing."
    }
    Write-Host "Sleep disabled on AC power (the screen can still turn off)."
}

$repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$drive = $repo.Substring(0,1).ToLower()
$linuxRepo = "/mnt/$drive" + ($repo.Substring(2) -replace '\\','/')

# ------------------------------------------------------------------ slot count + systemd (before the VM restart)
if ($Slots -gt 0) {
    Say "Setting this PC to $Slots slots"
    wsl.exe -d $Distro -u root -- bash -c "mkdir -p /etc/osrs; [ -f /etc/osrs/fleet.conf ] || cp '$linuxRepo/fleet/linux/fleet.conf' /etc/osrs/fleet.conf; sed -i 's/^SLOTS=.*/SLOTS=$Slots/' /etc/osrs/fleet.conf; grep '^SLOTS' /etc/osrs/fleet.conf"
}
if ($Install) {
    wsl.exe -d $Distro -u root -- bash -c "grep -qs '^systemd *= *true' /etc/wsl.conf || printf '[boot]\nsystemd=true\n' >> /etc/wsl.conf"
}

# ------------------------------------------------------------------ restart VM with new size, start task
Say "Restarting the VM with the new size"
wsl.exe --shutdown
Start-Sleep -Seconds 3
Start-ScheduledTask -TaskName "OSRS Fleet"

if ($Install) {
    Say "Installing the fleet inside the VM (10-20 minutes the first time)"
    Start-Sleep -Seconds 5
    wsl.exe -d $Distro -u root -- bash "$linuxRepo/fleet/linux/install.sh"
    Say "Done. Open http://localhost:8000/launcher"
    exit 0
}

Say "Windows part done"
Write-Host @"

Next, open 'Ubuntu 24.04' from the Start menu and run:

    sudo bash $linuxRepo/fleet/linux/install.sh

"@
