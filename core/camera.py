"""
Humanized camera moves for bots: rotate with the arrow keys, zoom with the
mouse wheel over the game view. Works on Windows and on the fleet's virtual
screens (keys via core.input.keys, wheel via pyautogui on the bot's $DISPLAY).

Zoom is tracked relative to where the camera was when the bot started, and
kept inside [zoom_min, zoom_max] wheel notches so it never drifts to an
unusable extreme.
"""

from __future__ import annotations

import random
import sys
import time

import pyautogui

from core.input import keys as keyboard
from core.logger import get_logger

# Game view inside the fixed-layout canvas (window-relative), with a margin so
# the wheel never lands on the chat box, minimap or side panel.
GAME_VIEW = (60, 60, 460, 300)

# Scrolling out this many notches always reaches the game's zoom-out limit, so the
# camera is fully zoomed out whatever the starting zoom was.
FULL_ZOOM_OUT_NOTCHES = 15
# Holding "up" past the tilt limit is harmless and ends straight top-down.
TOP_DOWN_TILT_TIME = (2.0, 2.6)
# After a rotate fidget or a search, chance the camera goes back to top-down.
RETURN_TOP_DOWN_CHANCE = 0.7


class Camera:
    def __init__(self, client, zoom_min: int = -4, zoom_max: int = 3):
        self.client = client
        self.zoom_min = zoom_min
        self.zoom_max = zoom_max
        # notches from the fully zoomed-out view (zoom_min); + = zoomed in.
        # Bots start fully zoomed out (top_down), so the counter starts at the limit.
        self.zoom = zoom_min
        self.search_dir: str | None = None  # keep turning one way while searching
        self.log = get_logger("Camera")

    # ------------------------------------------------------------------
    def rotate(self, seconds: float, direction: str | None = None) -> None:
        """Hold left/right arrow for `seconds` (about 3 s is a full turn)."""
        key = direction or random.choice(("left", "right"))
        self.client.bring_to_focus()
        try:
            keyboard.press(key)
            time.sleep(seconds)
        finally:
            keyboard.release(key)
        self.log.debug(f"rotated {key} for {seconds:.2f}s")

    def tilt_up(self, seconds: float) -> None:
        """Raise the camera (more top-down view, trees easier to see)."""
        self.client.bring_to_focus()
        try:
            keyboard.press("up")
            time.sleep(seconds)
        finally:
            keyboard.release("up")

    def _scroll(self, step: int, count: int) -> None:
        unit = 1 if sys.platform.startswith("linux") else 120  # X: clicks, Windows: wheel delta
        for _ in range(count):
            pyautogui.scroll(step * unit)
            time.sleep(random.uniform(0.05, 0.12))

    def top_down(self) -> None:
        """Fully zoom out and tilt straight down: the view bots start in and return to."""
        self.client.bring_to_focus()
        x1, y1, x2, y2 = GAME_VIEW
        self.client.move_to((random.randint(x1, x2), random.randint(y1, y2)), rand_move_chance=0)
        time.sleep(random.uniform(0.08, 0.2))
        self._scroll(-1, FULL_ZOOM_OUT_NOTCHES)  # out; the game clamps at its limit
        self.zoom = self.zoom_min
        self.tilt_up(random.uniform(*TOP_DOWN_TILT_TIME))
        self.log.info("Camera: top-down, fully zoomed out")

    def zoom_by(self, notches: int) -> int:
        """Scroll the wheel over the game view (+ = in). Clamped; returns notches done."""
        target = max(self.zoom_min, min(self.zoom_max, self.zoom + notches))
        notches = target - self.zoom
        if not notches:
            return 0
        x1, y1, x2, y2 = GAME_VIEW
        self.client.move_to((random.randint(x1, x2), random.randint(y1, y2)), rand_move_chance=0)
        time.sleep(random.uniform(0.08, 0.2))
        self._scroll(1 if notches > 0 else -1, abs(notches))
        self.zoom = target
        self.log.debug(f"zoomed {notches:+d} (now {self.zoom:+d})")
        return notches

    # ------------------------------------------------------------------
    def random_move(self, rotate_time: tuple[float, float], zoom_chance: float = 0.5) -> None:
        """A small, player-like camera fidget: rotate, maybe zoom, maybe tilt up."""
        moves = ["rotate"]
        if random.random() < zoom_chance:
            moves.append("zoom")
        if random.random() < 0.25:
            moves.append("tilt")
        random.shuffle(moves)
        for m in moves:
            if m == "rotate":
                self.rotate(random.uniform(*rotate_time))
            elif m == "zoom":
                # usually lean back out toward the top-down view
                dz = random.choice((-2, -1, 1, 2))
                if dz > 0 and random.random() < 0.6:
                    dz = -dz
                self.zoom_by(dz)
            else:
                self.tilt_up(random.uniform(0.2, 0.6))
            time.sleep(random.uniform(0.1, 0.4))
        if random.random() < RETURN_TOP_DOWN_CHANCE:
            time.sleep(random.uniform(0.1, 0.3))
            self.top_down()
        self.log.info(f"Camera fidget: {', '.join(moves)} (zoom {self.zoom:+d})")

    def search(self, rotate_time: tuple[float, float], attempt: int) -> None:
        """Nothing to click is visible: turn the camera to look elsewhere.
        Every few attempts also zoom out and tilt up to see further."""
        if attempt <= 1 or not self.search_dir:
            self.search_dir = random.choice(("left", "right"))
        self.rotate(random.uniform(*rotate_time), self.search_dir)
        if attempt % 3 == 0:
            self.zoom_by(-random.randint(1, 2))
            self.tilt_up(random.uniform(0.3, 0.8))
        if random.random() < RETURN_TOP_DOWN_CHANCE:
            self.top_down()
        self.log.info(f"Camera search #{attempt} (zoom {self.zoom:+d})")
