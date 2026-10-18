#!/usr/bin/env bash
# One-time setup of the OSRS fleet inside Ubuntu 24.04 (WSL2 or a normal VM).
#
#   sudo bash /mnt/d/OSRS/osrs-cv-bot-main/fleet/linux/install.sh
#
# Safe to run again: it only adds what is missing and refreshes the code.
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
    echo "Run with sudo:  sudo bash $0" >&2
    exit 1
fi

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
say() { printf '\n\033[1;32m==> %s\033[0m\n' "$*"; }

# ---------------------------------------------------------------- config
mkdir -p /etc/osrs
if [ ! -f /etc/osrs/fleet.conf ]; then
    cp "$HERE/fleet.conf" /etc/osrs/fleet.conf
fi
echo "$REPO" > /etc/osrs/source_dir
source /etc/osrs/fleet.conf
SLOTS=${SLOTS:-8}
APP_DIR=${APP_DIR:-/opt/osrs/app}

# ---------------------------------------------------------------- systemd check (WSL)
if grep -qi microsoft /proc/version 2>/dev/null; then
    if ! grep -qs '^systemd *= *true' /etc/wsl.conf; then
        say "Turning on systemd in WSL"
        printf '[boot]\nsystemd=true\n' >> /etc/wsl.conf
        echo
        echo "systemd was off. In Windows PowerShell run:  wsl --shutdown"
        echo "then open Ubuntu again and re-run this script."
        exit 0
    fi
fi
if [ "$(ps -p 1 -o comm=)" != "systemd" ]; then
    echo "systemd is not running (PID 1 is $(ps -p 1 -o comm=)). Restart the VM / 'wsl --shutdown' and retry." >&2
    exit 1
fi

# ---------------------------------------------------------------- packages
say "Installing packages (a few minutes the first time)"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq \
    xvfb openbox x11vnc x11-utils x11-xserver-utils xdotool xclip \
    tesseract-ocr openjdk-17-jre \
    python3-venv python3-tk python3-dev \
    libgl1 libglib2.0-0 rsync curl fonts-dejavu-core >/dev/null

# ---------------------------------------------------------------- users
say "Creating $SLOTS slot users (bot1..bot$SLOTS)"
getent group osrs >/dev/null || groupadd osrs
for n in $(seq 1 "$SLOTS"); do
    if ! id "bot$n" >/dev/null 2>&1; then
        useradd -m -s /bin/bash -G osrs "bot$n"
    else
        usermod -aG osrs "bot$n"
    fi
done
# let the person who ran sudo manage files too
if [ -n "${SUDO_USER:-}" ] && [ "$SUDO_USER" != root ]; then
    usermod -aG osrs "$SUDO_USER"
fi

# ---------------------------------------------------------------- code
say "Copying code from $REPO to $APP_DIR"
mkdir -p "$APP_DIR" /opt/osrs/bin /opt/osrs/runelite
rsync -a --delete \
    --exclude '.git/' --exclude '.venv/' --exclude '__pycache__/' \
    --exclude 'node_modules/' --exclude '*.log' \
    --exclude 'data/configs/slot*/' \
    "$REPO/" "$APP_DIR/"
chown -R root:osrs "$APP_DIR"
chmod -R g+rwX "$APP_DIR"
find "$APP_DIR" -type d -exec chmod g+s {} +

install -m 755 "$HERE/slot" /opt/osrs/bin/slot
install -m 755 "$HERE/fleetctl" /opt/osrs/bin/fleetctl
ln -sf /opt/osrs/bin/fleetctl /usr/local/bin/fleetctl

# ---------------------------------------------------------------- python
say "Setting up Python environment"
if [ ! -x /opt/osrs/venv/bin/python ]; then
    python3 -m venv /opt/osrs/venv
fi
/opt/osrs/venv/bin/pip install -q --upgrade pip
/opt/osrs/venv/bin/pip install -q -r "$APP_DIR/requirements.txt" python-xlib
sha256sum "$APP_DIR/requirements.txt" | cut -d' ' -f1 > /opt/osrs/.requirements.sha

# ---------------------------------------------------------------- RuneLite
if [ ! -s /opt/osrs/runelite/RuneLite.jar ]; then
    say "Downloading RuneLite"
    curl -fsSL -o /opt/osrs/runelite/RuneLite.jar \
        https://github.com/runelite/launcher/releases/latest/download/RuneLite.jar
fi
chmod 644 /opt/osrs/runelite/RuneLite.jar

# ---------------------------------------------------------------- services
say "Installing services"
# shared X socket folder that every slot's screen can use
echo 'd /tmp/.X11-unix 1777 root root -' > /etc/tmpfiles.d/osrs-x11.conf
# lock that makes the slots start RuneLite one after another (see slot)
cat >> /etc/tmpfiles.d/osrs-x11.conf <<'TMPF'
d /run/osrs 0775 root osrs -
f /run/osrs/runelite-start.lock 0666 root osrs -
TMPF
systemd-tmpfiles --create /etc/tmpfiles.d/osrs-x11.conf
install -m 644 "$HERE"/systemd/* /etc/systemd/system/
systemctl daemon-reload
# tokens for the browser screen view: slotN -> that slot's VNC port
for n in $(seq 1 "$SLOTS"); do echo "slot$n: 127.0.0.1:$((5900 + n))"; done > /etc/osrs/vnc-tokens
systemctl enable --now osrs-dashboard.service >/dev/null
systemctl enable --now osrs-websockify.service >/dev/null
for n in $(seq 1 "$SLOTS"); do
    systemctl enable "osrs-slot@$n.target" >/dev/null 2>&1
    systemctl start "osrs-slot@$n.target"
done

say "Done"
cat <<EOF

  Dashboard (all $SLOTS screens):  http://localhost:${DASHBOARD_PORT:-8000}
  Bot web UI for slot N:          http://localhost:801N   (8011 ... 801$SLOTS)
  Watch / log in to slot N (VNC): localhost:590N          (5901 ... 590$SLOTS)

  Next: log in each account (see fleet/README.md, step 4), then pick a bot
  for it in that slot's web UI.

  Useful:  fleetctl status | fleetctl restart 3 | fleetctl update | fleetctl help
EOF
