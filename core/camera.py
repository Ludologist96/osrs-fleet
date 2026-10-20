"""
Humanized camera moves for bots: rotate with the arrow keys, zoom with the
mouse wheel over the game view. Works on Windows and on the fleet's virtual
screens (keys via core.input.keys, wheel via pyautogui on the bot's $DISPLAY).

Bots start in a "home" view: fully zoomed out, then HOME_ZOOM_IN wheel notches back
in (about halfway, so loot is big enough to click), tilted straight down. Zoom is
tracked in notches from that home view (0) and kept inside [zoom_min, zoom_max].
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
# From fully zoomed out, scroll back in this many notches for the home view (~halfway).
HOME_ZOOM_IN = 9  # the full range is ~18-20 notches
# After a rotate fidget or a search, chance the camera goes back to the home view.
RETURN_TOP_DOWN_CHANCE = 0.7


class Camera:
    def __init__(self, client, zoom_min: int = -4, zoom_max: int = 3, home_zoom_in: int = HOME_ZOOM_IN):
        self.client = client
        self.home_zoom_in = max(0, int(home_zoom_in))
        # notches from the home view; can't go further out than fully zoomed out
        self.zoom_min = max(zoom_min, -self.home_zoom_in)
        self.zoom_max = zoom_max
        self.zoom = 0  # + = zoomed in (bots start in the home view: top_down())
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
        """The home view bots start in: fully zoom out (the game clamps there, so this
        works from any zoom), back in HOME_ZOOM_IN notches, tilt straight down."""
        self.client.bring_to_focus()
        x1, y1, x2, y2 = GAME_VIEW
        self.client.move_to((random.randint(x1, x2), random.randint(y1, y2)), rand_move_chance=0)
        time.sleep(random.uniform(0.08, 0.2))
        self._scroll(-1, FULL_ZOOM_OUT_NOTCHES)
        if self.home_zoom_in:
            time.sleep(random.uniform(0.1, 0.25))
            self._scroll(1, self.home_zoom_in)
        self.zoom = 0
        self.tilt_up(random.uniform(*TOP_DOWN_TILT_TIME))
        self.log.info(f"Camera: top-down, zoomed out then {self.home_zoom_in} notches in")

    def go_home(self) -> None:
        """Back to the home view the way a player would: undo the zoom, tilt down."""
        if self.zoom:
            self.zoom_by(-self.zoom)
        self.tilt_up(random.uniform(0.5, 0.9))

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
                # usually lean back toward the home view
                dz = random.choice((-2, -1, 1, 2))
                if self.zoom and (dz > 0) == (self.zoom > 0) and random.random() < 0.6:
                    dz = -dz
                self.zoom_by(dz)
            else:
                self.tilt_up(random.uniform(0.2, 0.6))
            time.sleep(random.uniform(0.1, 0.4))
        if random.random() < RETURN_TOP_DOWN_CHANCE:
            time.sleep(random.uniform(0.1, 0.3))
            self.go_home()
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
            self.go_home()
        self.log.info(f"Camera search #{attempt} (zoom {self.zoom:+d})")
