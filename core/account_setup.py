"""One-time game settings for an account (the game keeps them on its server, per account):

  - "Disable level-up interface": no level-up popup in the chat box (it covers the chat
    the bots read and needs a click to go away).

Works on the screen only: the Settings tab icon (data/ui/settings.webp), then the words
on the screen (Tesseract) - "All Settings", the search results - and the colour of the
checkbox next to the setting. Runs with no bot active (the session API / the launcher
calls it once per account).
"""
from __future__ import annotations

import logging
import random
import time

from PIL import Image

from core import login, tools
from core.input import mouse_control
from core.region_match import MatchResult
from core.screen_words import find_line, lines, words

log = logging.getLogger("AccountSetup")

TAB_ICONS = {
    "inventory": "data/ui/inventory.webp", "settings": "data/ui/settings.webp",
    "logout": "data/ui/logout.webp", "skills": "data/ui/stats.webp",
}


def _sc(win) -> Image.Image:
    return login._screenshot(win)


def click(win, pt, button: str = "left") -> None:
    """Humanlike: a curved move to the point, a short pause, a held press."""
    win.bring_to_focus()
    mouse_control.move_to(win.left + int(pt[0]), win.top + int(pt[1]))
    time.sleep(random.uniform(0.08, 0.2))
    mouse_control.press(mouse_control.ClickType.RIGHT if button == "right" else mouse_control.ClickType.LEFT)


def click_box(win, b) -> None:
    """Click inside a word/line box {x1, y1, x2, y2} (normal spread around its middle)."""
    m = MatchResult(b["x1"], b["y1"], max(b["x2"], b["x1"] + 2), max(b["y2"], b["y1"] + 2))
    click(win, m.get_point_within())


def tab(win, name: str) -> bool:
    """Click a side-panel tab by its icon. False when the icon isn't found."""
    sc = _sc(win)
    try:
        m = tools.find_subimage(sc, Image.open(TAB_ICONS[name]), min_scale=0.9, max_scale=1.1)
    except Exception:
        log.debug(f"tab icon {name} not found", exc_info=True)
        return False
    if m.confidence < 0.8:
        log.info(f"Tab icon '{name}' not found (best {m.confidence:.2f})")
        return False
    click(win, m.get_point_within())
    time.sleep(random.uniform(0.5, 0.8))
    return True
