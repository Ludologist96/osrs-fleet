"""
Per-instance settings for running several bot copies on one machine.

Each copy ("slot") is started with the environment variable OSRS_SLOT=<n>
(1..8 on the fleet VM). Slot 0 is the normal single-PC mode and keeps every
original port and folder, so nothing changes when OSRS_SLOT is not set.

Every internal port is shifted by 10 per slot so copies never collide:

    service              slot 0   slot 1   slot 8
    bot API (Flask)      5432     5442     5512
    CV debug (bot)       5555     5565     5635
    CV debug (UI proxy)  5055     5065     5135
    log WebSocket        18765    18775    18845

The web UI port is passed on the command line (main.py --port 8010+slot).
"""

import os
from pathlib import Path

try:
    SLOT = int(os.environ.get("OSRS_SLOT", "0") or 0)
except ValueError:
    SLOT = 0

PORT_STEP = 10

IS_FLEET = SLOT > 0


def port(base: int) -> int:
    """Return `base` shifted for this slot."""
    return base + SLOT * PORT_STEP


def config_dir(project_root: Path) -> Path:
    """Where saved bot configs live for this slot."""
    base = Path(project_root) / "data" / "configs"
    return base if SLOT == 0 else base / f"slot{SLOT}"
