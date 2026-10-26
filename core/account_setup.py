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


# ------------------------------------------------------------ level-up pop-ups off
# All Settings -> Interfaces -> "Level-up pop-up notifications": a dropdown
# (Disabled / Show level only / Show level & unlocks). Positions measured on the fixed
# layout (Oct 26 2026); the words are found by OCR, the fixed points are only the
# dropdown middle (x) and the window's close button.
SIDE_PANEL = (540, 190, 804, 500)
CATEGORIES = (0, 40, 100, 340)
SETTINGS_LIST = (100, 60, 470, 340)
DROPDOWN_X = 402
CLOSE_BTN = MatchResult(497, 16, 507, 27)


def _wait_line(win, phrase, box, tries=4, min_ratio=0.7):
    for _ in range(tries):
        ln = find_line(_sc(win), phrase, box, min_ratio=min_ratio)
        if ln:
            return ln
        time.sleep(0.4)
    return None


def _close_settings(win):
    click(win, CLOSE_BTN.get_point_within())
    time.sleep(random.uniform(0.5, 0.8))
    tab(win, "inventory")


def disable_levelup_popup(win) -> dict:
    """Set "Level-up pop-up notifications" to Disabled. {"ok": True, "was": <old value>}
    or {"ok": False, "error": ...}. Leaves the inventory tab open."""
    if not tab(win, "settings"):
        return {"ok": False, "error": "settings tab not found"}
    time.sleep(random.uniform(0.3, 0.6))
    ln = _wait_line(win, "All Settings", SIDE_PANEL)
    if not ln:
        tab(win, "inventory")
        return {"ok": False, "error": "'All Settings' button not found"}
    click_box(win, ln)
    time.sleep(random.uniform(0.9, 1.3))
    try:
        ln = _wait_line(win, "Interfaces", CATEGORIES)
        if not ln:
            return {"ok": False, "error": "'Interfaces' not found in All Settings"}
        click_box(win, ln)
        time.sleep(random.uniform(0.7, 1.0))
        row = _wait_line(win, "pop-up notifications", SETTINGS_LIST, min_ratio=0.6)
        if not row:
            return {"ok": False, "error": "level-up setting not found"}
        cy = (row["y1"] + row["y2"]) // 2
        val_box = (330, cy - 12, 470, cy + 12)
        val = find_line(_sc(win), "Disabled", val_box, min_ratio=0.0)
        was = val["text"] if val else "?"
        if val and "disab" in val["text"].lower():
            return {"ok": True, "was": was, "note": "already disabled"}
        click(win, (DROPDOWN_X + random.randint(-15, 15), cy + random.randint(-2, 2)))
        time.sleep(random.uniform(0.6, 0.9))
        opt = _wait_line(win, "Disabled", (330, max(60, cy - 120), 480, min(345, cy + 120)), min_ratio=0.8)
        if not opt:
            return {"ok": False, "error": "'Disabled' option not found in the dropdown", "was": was}
        click_box(win, opt)
        time.sleep(random.uniform(0.6, 0.9))
        now = find_line(_sc(win), "Disabled", val_box, min_ratio=0.0)
        ok = bool(now and "disab" in now["text"].lower())
        return {"ok": ok, "was": was, "now": now["text"] if now else "?"}
    finally:
        _close_settings(win)
