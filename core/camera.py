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


class Camera:
    def __init__(self, client, zoom_min: int = -4, zoom_max: int = 3):
        self.client = client
        self.zoom_min = zoom_min
        self.zoom_max = zoom_max
        self.zoom = 0  # notches from the starting zoom; + = zoomed in
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

    def zoom_by(self, notches: int) -> int:
        """Scroll the wheel over the game view (+ = in). Clamped; returns notches done."""
        target = max(self.zoom_min, min(self.zoom_max, self.zoom + notches))
        notches = target - self.zoom
        if not notches:
            return 0
        x1, y1, x2, y2 = GAME_VIEW
        self.client.move_to((random.randint(x1, x2), random.randint(y1, y2)), rand_move_chance=0)
        time.sleep(random.uniform(0.08, 0.2))
        step = 1 if notches > 0 else -1
        unit = 1 if sys.platform.startswith("linux") else 120  # X: clicks, Windows: wheel delta
        for _ in range(abs(notches)):
            pyautogui.scroll(step * unit)
            time.sleep(random.uniform(0.05, 0.18))
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
                # lean back toward the starting zoom when far from it
                dz = random.choice((-2, -1, 1, 2))
                if abs(self.zoom + dz) > abs(self.zoom) and random.random() < 0.6:
                    dz = -dz
                self.zoom_by(dz)
            else:
                self.tilt_up(random.uniform(0.2, 0.6))
            time.sleep(random.uniform(0.1, 0.4))
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
        self.log.info(f"Camera search #{attempt} (zoom {self.zoom:+d})")
