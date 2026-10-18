"""
Get a RuneLite client from the login screen into the game, without a bot running.

Works with saved Jagex-account logins (credentials.properties): the login screen
then shows a "Play Now" button, and after it the welcome screen shows
"CLICK HERE TO PLAY". Positions are relative to the game canvas in RuneLite's
fixed layout (765x503 canvas at the top-left of the client area).

RuneLiteClient can't be used here: it needs the in-game interface to start.
"""

from __future__ import annotations

import random
import time
from typing import Dict, Tuple

import mss
from PIL import Image

from core import tools
from core.input import mouse_control
from core.logger import get_logger
from core.window_manager import WindowManager

log = get_logger("Login")

# Canvas-relative click targets (x, y) and how far a click may stray from them.
PLAY_NOW = (383, 258)          # "Play Now" box on the Jagex-account login screen
CLICK_HERE_TO_PLAY = (383, 323)  # red button on the welcome screen after login
JITTER = 12

# In-game check: the side panel (inventory etc.) must be visible.
_TOOLPLANES = ("data/ui/toolplane-classic.png", "data/ui/toolplane-modern.png")
IN_GAME_CONFIDENCE = 0.95


def _window():
    windows = WindowManager.create().get_windows_with_title("RuneLite")
    if not windows:
        raise RuntimeError("RuneLite window not found")
    return windows[0]


def _screenshot(win) -> Image.Image:
    with mss.mss() as sct:
        raw = sct.grab((win.left, win.top, win.left + win.width, win.top + win.height))
        return Image.frombytes("RGB", raw.size, raw.rgb)


def in_game_confidence(sc: Image.Image) -> float:
    best = 0.0
    for path in _TOOLPLANES:
        try:
            m = tools.find_subimage(sc, Image.open(path), min_scale=1, max_scale=1)
            best = max(best, float(m.confidence))
        except Exception:
            log.debug(f"toolplane match failed for {path}", exc_info=True)
    return best


def state() -> Dict:
    """{'state': 'game' | 'not_in_game', 'in_game_confidence': float, 'window': title}"""
    win = _window()
    conf = in_game_confidence(_screenshot(win))
    return {
        "state": "game" if conf >= IN_GAME_CONFIDENCE else "not_in_game",
        "in_game_confidence": round(conf, 4),
        "window": win.title,
    }


def _click_canvas(win, target: Tuple[int, int]) -> None:
    x = win.left + target[0] + random.randint(-JITTER, JITTER)
    y = win.top + target[1] + random.randint(-JITTER // 2, JITTER // 2)
    win.bring_to_focus()
    mouse_control.move_to(x, y)
    time.sleep(random.uniform(0.1, 0.3))
    mouse_control.click(-1, -1)


def _wait_in_game(win, seconds: float) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if in_game_confidence(_screenshot(win)) >= IN_GAME_CONFIDENCE:
            return True
        time.sleep(1.0)
    return False


def login(rounds: int = 3, only_play_now: bool = False) -> Dict:
    """Click "Play Now" then "CLICK HERE TO PLAY" until the game interface shows.
    Returns the final state(). Does nothing if already in game."""
    win = _window()
    if "-" not in win.title:
        raise RuntimeError("No saved login in this slot (window title has no account name)")
    for attempt in range(1, rounds + 1):
        if _wait_in_game(win, 1):
            break
        log.info(f"Login attempt {attempt}: clicking Play Now")
        _click_canvas(win, PLAY_NOW)
        if only_play_now:
            time.sleep(8)
            break
        if _wait_in_game(win, 12):
            break
        log.info("Clicking 'CLICK HERE TO PLAY'")
        _click_canvas(win, CLICK_HERE_TO_PLAY)
        if _wait_in_game(win, 10):
            break
    result = state()
    log.info(f"Login finished: {result}")
    return result
