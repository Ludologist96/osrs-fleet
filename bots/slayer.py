"""
Slayer bot - attacks highlighted NPCs, one after another.

First target: cows. Built to be reused for other monsters later (change the
hover text and the NPC Indicators list in RuneLite).

How it sees things (RuneLite plugins):
  - NPC Indicators: the monsters to attack are highlighted with a coloured hull
    (default cyan 00FFFF). "NPCs to Highlight" = Cow (or whatever you fight).
    "Ignore dead NPCs" on, so a dying monster loses its highlight.
  - Opponent Information: the box in the top-left of the game view with the
    target's name and a green/red health bar. Bar there with some green = we are
    fighting; bar all red (or gone) = the target is dead.

Loop: not fighting -> click the nearest highlighted monster whose mouse-over
says "Attack Cow" -> wait until the fight starts -> wait while the target has
health -> short human-like pause -> next one. Breaks, tab browsing, long AFK
breaks and camera moves work like the woodcutter.

Not yet: picking up loot, eating food.
"""
from bots.core import BotConfigMixin
from bots.core.cfg_types import (
    StringListParam, BooleanParam, IntParam, FloatParam, RGBParam, RGBListParam,
    RangeParam, BreakCfgParam,
)
from core.bot import Bot
from core.camera import Camera
from core.region_match import MatchResult
from core.control import ScriptTerminationException
from core.logger import get_logger

from PIL import Image
import numpy as np
import cv2
import random
import time


class BotConfig(BotConfigMixin):
    # --- what to attack ---
    # NPC Indicators hull colour(s) of the monsters to attack.
    npc_colors: RGBListParam = RGBListParam([RGBParam(0, 255, 255)])  # cyan (RuneLite default)
    color_tolerance: IntParam = IntParam(40)
    # Mouse-over text a highlighted monster must show before it is clicked.
    attack_hover: StringListParam = StringListParam(["Attack Cow"])
    # Highlights smaller than this (pixels of outline) are ignored (far away / half hidden).
    min_npc_pixels: IntParam = IntParam(60)
    targets_per_try: IntParam = IntParam(4)  # highlighted monsters to try per round

    # --- fighting ---
    # After clicking a monster, wait up to this long for the fight to start (walking there).
    attack_start_timeout: FloatParam = FloatParam(8.0)
    fight_check_delay: RangeParam = RangeParam(0.6, 1.3)
    max_fight_time: FloatParam = FloatParam(90.0)  # give up on one fight after this long
    # Pause after a kill before looking for the next monster (reaction time).
    after_kill_delay: RangeParam = RangeParam(0.4, 2.2)

    # --- nothing to attack ---
    no_target_wait: RangeParam = RangeParam(1.5, 4.0)
    max_no_target: IntParam = IntParam(40)  # stop after this many empty looks in a row
    max_retries: IntParam = IntParam(5)  # unexpected errors in a row before stopping

    # --- camera (like the woodcutter) ---
    camera_chance: FloatParam = FloatParam(0.05)  # after a kill
    camera_rotate_time: RangeParam = RangeParam(0.3, 1.2)
    camera_zoom_chance: FloatParam = FloatParam(0.5)
    zoom_min: IntParam = IntParam(-4)
    zoom_max: IntParam = IntParam(3)
    camera_search: BooleanParam = BooleanParam(True)  # nothing highlighted: look around
    camera_search_time: RangeParam = RangeParam(0.6, 1.4)

    # --- breaks (like the woodcutter) ---
    break_cfg: BreakCfgParam = BreakCfgParam(RangeParam(10, 30), FloatParam(0.01))
    break_ui_browse_chance: FloatParam = FloatParam(0.5)
    long_break_cfg: BreakCfgParam = BreakCfgParam(RangeParam(600, 900), FloatParam(0.01))


# Opponent Information health bar (RuneLite colours, drawn at ~90% opacity).
BAR_GREEN = (0, 146, 54)
BAR_RED = (102, 15, 16)
BAR_TOL = 30
BAR_MIN_RUN = 50     # px: the bar is ~120+ px wide
BAR_MIN_ROWS = 4     # px: and several px high
BAR_SEARCH = (0, 0, 330, 170)  # window-relative area where the overlay sits (top-left)


class BotExecutor(Bot):
    name: str = "Slayer Bot"
    description: str = "Attacks highlighted monsters one after another (cows first)"
    tier: str = "C"
    instructions: str = """
    RuneLite setup:
    - NPC Indicators: NPCs to Highlight = Cow, Highlight hull on, colour cyan (00FFFF),
      Ignore dead NPCs on.
    - Opponent Information: on (shows the target's health bar top-left).
    Stand in the cow field, pick your attack style, then start.
    No looting and no eating yet - only fight things that can't kill you.
    """

    def __init__(self, config: BotConfig, user=''):
        super().__init__(user, break_cfg=config.break_cfg, long_break_cfg=config.long_break_cfg,
                         break_ui_browse_chance=config.break_ui_browse_chance.value)
        self.cfg: BotConfig = config
        self.log = get_logger('SlayerBot')
        self.camera = Camera(self.client, self.cfg.zoom_min.value, self.cfg.zoom_max.value)
        self.kills = 0
        self.no_target = 0
        self.failures = 0

    # ------------------------------------------------------------------
    def start(self):
        self.log.info(f"Starting Slayer Bot ({', '.join(self.cfg.attack_hover.value)})")
        try:
            while not self.terminate:
                try:
                    if self._step() == "stop":
                        return
                    self.failures = 0
                except ScriptTerminationException:
                    raise
                except Exception as e:
                    if self.terminate:
                        break
                    self.failures += 1
                    self.log.error(f"Error ({self.failures}/{self.cfg.max_retries.value}): {e}", exc_info=True)
                    if self.failures > self.cfg.max_retries.value:
                        self.log.critical("Too many errors in a row. Stopping.")
                        return
                    time.sleep(3)
                self.control.propose_break()
        except ScriptTerminationException:
            self.log.info("Terminated by user")
        finally:
            self.log.info(f"Stopped after {self.kills} kills")

    def _step(self):
        state = self.fight_state()
        if state == "fighting":
            self._wait_fight_end()
            return
        # not fighting (no bar, or the last target's bar is empty)
        if self.kills and random.random() < self.cfg.camera_chance.value:
            self.camera.random_move(self.cfg.camera_rotate_time.value, self.cfg.camera_zoom_chance.value)
        if self.attack():
            self.no_target = 0
            return
        self.no_target += 1
        if self.no_target > self.cfg.max_no_target.value:
            self.log.error(f"Nothing to attack for {self.no_target} tries in a row. Stopping.")
            return "stop"
        if self.cfg.camera_search.value and self.no_target >= 2:
            self.camera.search(self.cfg.camera_search_time.value, self.no_target - 1)
        wait = self.cfg.no_target_wait.choose()
        self.log.info(f"Nothing to attack; waiting {wait:.1f}s ({self.no_target}/{self.cfg.max_no_target.value})")
        time.sleep(wait)

    # ------------------------------------------------------------------ combat state
    def opponent_bar(self, sc: Image.Image | None = None) -> tuple[int, int] | None:
        """(green px, red px) of the Opponent Information health bar, or None if no bar."""
        if sc is None:
            sc = self.client.get_screenshot()
        x1, y1, x2, y2 = BAR_SEARCH
        arr = np.asarray(sc.convert("RGB").crop((x1, y1, min(x2, sc.width), min(y2, sc.height))), dtype=np.int16)
        green = np.all(np.abs(arr - BAR_GREEN) <= BAR_TOL, axis=2)
        red = np.all(np.abs(arr - BAR_RED) <= BAR_TOL, axis=2)
        both = green | red
        rows = []
        for y in range(both.shape[0]):
            row = both[y]
            if row.sum() < BAR_MIN_RUN:
                continue
            # longest run of bar pixels in this row
            padded = np.concatenate(([0], row.astype(np.int8), [0]))
            d = np.diff(padded)
            starts, ends = np.where(d == 1)[0], np.where(d == -1)[0]
            if len(starts) and (ends - starts).max() >= BAR_MIN_RUN:
                rows.append(y)
        if len(rows) < BAR_MIN_ROWS:
            return None
        g = int(green[rows].sum())
        r = int(red[rows].sum())
        return g, r

    def fight_state(self) -> str:
        """'fighting' (target has health), 'dead' (bar empty) or 'none' (no bar)."""
        bar = self.opponent_bar()
        if bar is None:
            return "none"
        g, r = bar
        # a sliver of green may be anti-aliasing: need a few columns' worth
        return "fighting" if g > 3 * BAR_MIN_ROWS else "dead"

    def _wait_fight_end(self):
        start = time.time()
        while not self.terminate:
            if time.time() - start > self.cfg.max_fight_time.value:
                self.log.warning("Fight took too long; looking for another target")
                return
            time.sleep(self.cfg.fight_check_delay.choose())
            state = self.fight_state()
            if state != "fighting":
                self.kills += 1
                self.log.info(f"Target down ({state}) after {time.time() - start:.0f}s - kills: {self.kills}")
                time.sleep(self.cfg.after_kill_delay.choose())
                return

    # ------------------------------------------------------------------ targets
    def find_targets(self) -> list[MatchResult]:
        """Highlighted monsters in the game view, biggest (= usually nearest) first."""
        sc = self.client.get_filtered_screenshot()
        arr = np.asarray(sc.convert("RGB"), dtype=np.int16)
        tol = self.cfg.color_tolerance.value
        mask = np.zeros(arr.shape[:2], dtype=bool)
        for c in self.cfg.npc_colors.value:
            mask |= np.all(np.abs(arr - np.array(c.value)) <= tol, axis=2)
        # blackened UI parts are excluded by get_filtered_screenshot; join a hull's pieces
        mask = cv2.dilate(mask.astype(np.uint8), np.ones((3, 3), np.uint8))
        num, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        found = []
        for i in range(1, num):
            x, y, w, h, area = stats[i]
            if area < self.cfg.min_npc_pixels.value or w < 8 or h < 8:
                continue
            found.append((area, MatchResult(int(x), int(y), int(x + w), int(y + h))))
        found.sort(key=lambda t: -t[0])
        return [m for _, m in found]

    def attack(self) -> bool:
        """Click a highlighted monster showing the attack text, then wait for the fight."""
        targets = self.find_targets()
        if not targets:
            self.log.debug("No highlighted monster on screen")
            return False
        # mostly the nearest, sometimes the 2nd/3rd - players don't always pick the closest
        tried = 0
        order = targets[:]
        if len(order) > 1 and random.random() < 0.3:
            k = random.randint(1, min(2, len(order) - 1))
            order.insert(0, order.pop(k))
        for m in order[: self.cfg.targets_per_try.value]:
            tried += 1
            # aim a bit inside the hull, not at its edge
            inner = m.scale_px(-max(2, min(m.width, m.height) // 5))
            try:
                self.client.smart_click_match(inner, list(self.cfg.attack_hover.value), retry_hover=2)
            except RuntimeError as e:
                self.log.debug(f"Not attackable here ({e})")
                continue
            if self._wait_fight_start():
                return True
            self.log.info("Fight didn't start (someone else's, or unreachable); trying another")
        self.log.debug(f"Tried {tried} highlighted monsters, none attackable")
        return False

    def _wait_fight_start(self) -> bool:
        deadline = time.time() + float(self.cfg.attack_start_timeout.value)
        time.sleep(random.uniform(0.5, 0.9))
        while time.time() < deadline and not self.terminate:
            if self.fight_state() == "fighting":
                self.log.info("Fighting")
                return True
            time.sleep(random.uniform(0.4, 0.8))
        return False


if __name__ == "__main__":
    BotExecutor(BotConfig()).start()
