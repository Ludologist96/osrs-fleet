"""
Things a player does while taking a short break: open a few side-panel tabs
(skills, quests, equipment...), look at each for a moment, then go back to the
tab that was open before (normally the inventory).
"""

from __future__ import annotations

import random
import time

from core.control import ScriptTerminationException
from core.osrs_client import ToolplaneTab

# Tabs worth "looking at". Never the logout tab.
BROWSE_TABS = [
    ToolplaneTab.SKILLS, ToolplaneTab.SKILLS,       # most common: check XP
    ToolplaneTab.COMBAT, ToolplaneTab.PROGRESS,     # combat options, quests
    ToolplaneTab.EQUIPMENT, ToolplaneTab.PRAYER, ToolplaneTab.SPELLS,
    ToolplaneTab.GROUPS, ToolplaneTab.ACCOUNT, ToolplaneTab.EMOTES, ToolplaneTab.MUSIC,
]


def _sleep(control, seconds: float) -> None:
    end = time.time() + seconds
    while time.time() < end:
        if control.terminate:
            raise ScriptTerminationException()
        time.sleep(min(0.25, end - time.time()))


def browse_tabs(client, control, log, look_time=(2.0, 6.0), max_tabs: int = 3) -> None:
    sc = client.get_screenshot()
    before = client.toolplane.get_active_tab(sc) or ToolplaneTab.INVENTORY.value
    back = next((t for t in ToolplaneTab if t.value == before), ToolplaneTab.INVENTORY)
    if back == ToolplaneTab.LOGOUT:
        back = ToolplaneTab.INVENTORY

    tabs = []
    for _ in range(random.randint(1, max_tabs)):
        t = random.choice(BROWSE_TABS)
        if t != back and t not in tabs:
            tabs.append(t)
    if not tabs:
        tabs = [ToolplaneTab.SKILLS if back != ToolplaneTab.SKILLS else ToolplaneTab.PROGRESS]
    log.info(f"Break: looking at {', '.join(t.name.lower() for t in tabs)}, then back to {back.name.lower()}")
    _sleep(control, random.uniform(0.3, 1.2))
    for t in tabs:
        client.click_toolplane(t)
        _sleep(control, random.uniform(*look_time))
    client.click_toolplane(back)
