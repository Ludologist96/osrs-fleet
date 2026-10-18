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
PLAY_NOW = (383, 258)            # "Play Now" box on the Jagex-account login screen
OK_BUTTON = (383, 322)           # "Ok" under "You were disconnected from the server."
CLICK_HERE_TO_PLAY = (386, 336)  # red button on the welcome screen after login
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


def is_welcome_screen(sc: Image.Image) -> bool:
    """The post-login screen: a big dark-red "CLICK HERE TO PLAY" button."""
    x, y = CLICK_HERE_TO_PLAY
    box = sc.convert("RGB").crop((x - 50, y - 10, x + 50, y + 10))
    r, g, b = [sum(c) / len(c) for c in zip(*box.getdata())]
    return r > 60 and r > 1.8 * g and r > 1.8 * b


def _changed(a: Image.Image, b: Image.Image) -> bool:
    """Did the middle of the login screen change (new dialog, connecting...)?"""
    box = (230, 200, 540, 360)
    pa, pb = a.convert("L").crop(box), b.convert("L").crop(box)
    diff = sum(abs(x - y) for x, y in zip(pa.getdata(), pb.getdata())) / (310 * 160)
    return diff > 6


def login(timeout: float = 120, only_play_now: bool = False) -> Dict:
    """Get from the login screen into the game, reacting to what is on screen:
    welcome screen -> CLICK HERE TO PLAY; login screen -> Play Now; a dialog that
    doesn't react to Play Now (e.g. "You were disconnected") -> Ok.
    Returns the final state(). Does nothing if already in game."""
    win = _window()
    if "-" not in win.title:
        raise RuntimeError("No saved login in this slot (window title has no account name)")
    deadline = time.time() + timeout
    while time.time() < deadline:
        sc = _screenshot(win)
        if in_game_confidence(sc) >= IN_GAME_CONFIDENCE:
            break
        if is_welcome_screen(sc):
            log.info("Welcome screen: clicking CLICK HERE TO PLAY")
            _click_canvas(win, CLICK_HERE_TO_PLAY)
            _wait_in_game(win, 8)
            continue
        log.info("Login screen: clicking Play Now")
        _click_canvas(win, PLAY_NOW)
        if only_play_now:
            time.sleep(5)
            break
        time.sleep(2.5)
        if not _changed(sc, _screenshot(win)):
            log.info("Play Now did nothing: clicking Ok on the dialog")
            _click_canvas(win, OK_BUTTON)
            time.sleep(2.5)
            continue
        # connecting to the server: wait for the welcome screen or the game
        wait_until = time.time() + 25
        while time.time() < wait_until:
            time.sleep(1.5)
            sc2 = _screenshot(win)
            if is_welcome_screen(sc2) or in_game_confidence(sc2) >= IN_GAME_CONFIDENCE:
                break
    result = state()
    log.info(f"Login finished: {result}")
    return result
