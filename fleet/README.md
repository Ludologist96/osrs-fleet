# OSRS Fleet: 8 accounts on one PC

One Linux VM (WSL2) runs inside Windows. It has 8 virtual screens, and each
screen has its own RuneLite, its own invisible mouse and keyboard, and its own
copy of the bot app. The bots never touch your real mouse, so you can keep
using the PC.

```
Windows PC
└── Ubuntu 24.04 (WSL2 VM)
    ├── slot 1: screen :1 ─ RuneLite (account 1) ─ bot app → http://localhost:8011
    ├── slot 2: screen :2 ─ RuneLite (account 2) ─ bot app → http://localhost:8012
    │   ...
    ├── slot 8: screen :8 ─ RuneLite (account 8) ─ bot app → http://localhost:8018
    └── dashboard: all 8 screens live → http://localhost:8000
```

| Slot N | Address on Windows |
|---|---|
| Bot web UI (pick bot, settings, start/stop, logs) | `http://localhost:801N` |
| See and control the screen yourself (VNC) | `localhost:590N` |
| Dashboard (all slots) | `http://localhost:8000` |

Do the same setup on each PC.

---

## 1. Windows part (about 10 minutes, one restart)

Open **PowerShell as administrator** and run:

```powershell
powershell -ExecutionPolicy Bypass -File D:\OSRS\osrs-cv-bot-main\fleet\windows\setup-windows.ps1
```

Run it again each time it tells you to:

1. If WSL isn't installed yet, it installs WSL and asks you to **restart**.
2. It installs **Ubuntu 24.04**. A window opens and asks for a new Linux
   username and password. Pick anything you'll remember, then type `exit`.
3. On the last run it gives the VM ~65% of your RAM and all but 2 CPU cores.
   It also adds a hidden task that keeps the VM running while you're logged
   in, and asks whether to stop the PC from sleeping. Say **y**: the bots stop
   when the PC sleeps.

At the end it prints the exact command for step 2.

## 2. Linux part (about 10 minutes)

Open **Ubuntu 24.04** from the Start menu and run (the path is the one step 1 printed):

```bash
sudo bash /mnt/d/OSRS/osrs-cv-bot-main/fleet/linux/install.sh
```

This installs everything (virtual screens, VNC, Java, Tesseract, Python
packages), downloads RuneLite and creates users `bot1`…`bot8`. Then it starts
all 8 slots. If it says systemd was off, run `wsl --shutdown` in PowerShell,
open Ubuntu again and re-run it.

Open **http://localhost:8000**. You should see 8 RuneLite login screens.

## 3. Install a VNC viewer on Windows

Install a VNC viewer, for example **TightVNC Viewer** or **RealVNC Viewer**.
Connect to `localhost:5901` for slot 1, `localhost:5902` for slot 2, and so on.
There's no password; VNC only accepts connections from this PC.

You use VNC to log in, change RuneLite settings and fix stuck accounts. Close
the viewer when you're done; the slot keeps running.

## 4. Log in the accounts

**Jagex accounts** (all new accounts are Jagex accounts) need the Jagex
Launcher once per account, on Windows:

1. In the Jagex Launcher, find RuneLite → **Configure** (or run
   `RuneLite (configure)` from the Start menu). In **Client arguments** add:
   `--insecure-write-credentials`
2. Start RuneLite **from the Jagex Launcher** with account N, wait for the
   login screen, then close it. This saves the login to
   `C:\Users\<you>\.runelite\credentials.properties`.
3. In Ubuntu run: `fleetctl creds N`. It copies that file to slot N and
   restarts slot N's RuneLite, which now opens logged in to that account.
4. Repeat for every account, each time with the next slot number.

Keep `credentials.properties` private. Anyone with that file can log in to
the account. Remove the client argument once all slots are done.

**Old-style accounts** (email + password, no Jagex account): open VNC for the
slot and log in normally in RuneLite.

## 5. Set up RuneLite once and copy it to every slot

Over VNC on slot 1, set RuneLite up the way the bots expect:

- The same game layout you use on Windows. Don't resize or maximize the RuneLite
  window: it must stay fully inside the 1280×800 screen.
- The plugins the bot needs (see each bot's instructions in its web UI):
  tile markers and colors, mouse tooltips / action hover, player location
  overlay, and so on.
- Plugin **FPS Control**: limit to **20–30 FPS**. Eight clients at full FPS
  waste a lot of CPU.
- **GPU** plugin **off** (the virtual screens have no graphics card).

Then copy those settings to every other slot (logins are not copied):

```bash
fleetctl copy-settings 1 all
```

## 6. Run bots

Open `http://localhost:801N` for slot N. It's the same web UI as before: pick
a bot, set it up, press start. Each slot remembers its own settings. Until
you save settings in a slot, it uses the shared ones from `data/configs`.

**Page Up / Page Down don't work in the fleet.** The bots have no physical
keyboard. Stop a bot with **Stop bot** on the dashboard or in that slot's web
UI.

## 7. Changing the code

Keep editing the code in `D:\OSRS\osrs-cv-bot-main` on Windows as usual. The
VM runs its own copy, so after a change run:

```bash
fleetctl update
```

This copies the new code, updates Python packages if `requirements.txt`
changed, and restarts the bot apps. RuneLite clients stay logged in.

## Everyday commands (in Ubuntu)

```bash
fleetctl status                 # what's running in every slot, logged-in names
fleetctl restart 3              # restart slot 3 completely
fleetctl restart 3 client       # restart only RuneLite in slot 3
fleetctl restart all app        # restart every bot app
fleetctl stop 5,6               # turn slots 5 and 6 off
fleetctl logs 2                 # follow slot 2's bot log (Ctrl+C to quit)
fleetctl logs 2 client          # follow slot 2's RuneLite log
```

To run fewer than 8 accounts, set `SLOTS=` in `/etc/osrs/fleet.conf`
(`sudo nano /etc/osrs/fleet.conf`), run `fleetctl stop <the extra slots>`,
then `sudo systemctl disable osrs-slot@<n>.target` for each of them.

## Troubleshooting

| Problem | Fix |
|---|---|
| Dashboard doesn't open | In Ubuntu: `systemctl status osrs-dashboard`. If the VM isn't running, open Ubuntu once or restart the **OSRS Fleet** task in Task Scheduler. |
| A slot shows "no screen" | `fleetctl restart N` |
| RuneLite didn't open in a slot | `fleetctl logs N client`. On first start it downloads ~100 MB, so give it a minute. |
| Bot says "window not open" | RuneLite isn't running or not logged in yet. Check over VNC. |
| Bot clicks in the wrong place | RuneLite isn't in Fixed mode, or the window was resized or moved partly off the screen. |
| PC is slow | Lower the RuneLite FPS limit, or run fewer slots (`SLOTS=` in `/etc/osrs/fleet.conf`). |
| Bot app "offline" on the dashboard | `fleetctl logs N` shows the Python error. |

## What changed in the code (for reference)

- `core/instance.py`: slot number from `OSRS_SLOT`. Internal ports move up
  by 10 per slot (bot API 5432→5442…, CV debug, log WebSocket), and saved
  configs go to `data/configs/slotN/`. Without `OSRS_SLOT` nothing changes, so
  running on Windows works exactly as before.
- `core/input/keys.py`: keyboard output. On Windows it uses the old
  `keyboard` package; on the VM it types into the bot's own screen. The bank,
  woodcutter, miners, cooking, item combiner and camera bots use it.
- `core/control.py`: Page Up/Down hotkeys are off on Linux; use the web UI.
- `core/window_manager.py`: on the VM, finds the slot's RuneLite window even
  on the login screen.
- `core/osrs_client.py`: hover text on Linux reads both sources one after
  the other (it used to read only one).
