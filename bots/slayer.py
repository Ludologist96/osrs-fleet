"""
Slayer bot - attacks monsters one after another, picks up chosen loot.

First target: cows. Reused for other monsters by changing `targets` (and the loot lists).

How it sees things (RuneLite plugins - the fleet launcher sets these from this
bot's settings before it starts, so there is nothing to set by hand):
  - NPC Indicators: monsters named in `targets` get a cyan hull.
    "Ignore dead NPCs" on, so a dying monster loses its highlight.
  - Opponent Information: the box in the top-left of the game view with the
    target's name and a green/red health bar. Bar with some green = fighting;
    bar all red (or gone) = the target is dead.
  - Ground Items: items in `loot_use` + `loot_keep` are highlighted (purple text
    and a purple tile outline), only items we may take (ownership filter TAKEABLE).

Loop: not fighting -> click the nearest highlighted monster whose mouse-over says
"Attack <target>" -> wait until the fight starts -> wait while the target has
health -> wait for the drop -> pick up highlighted loot near the character
("Take <item>", right-click menu if a monster stands on it) -> use `loot_use`
items at once (left-click: bones are buried, food eaten) -> next monster.
Breaks, tab browsing, long AFK breaks and camera moves work like the woodcutter.

Not yet: banking (a full inventory just stops picking up `loot_keep`), eating to heal.
"""
from bots.core import BotConfigMixin
from bots.core.cfg_types import (
    StringListParam, BooleanParam, IntParam, FloatParam, RGBParam, RGBListParam,
    RangeParam, BreakCfgParam,
)
from core.bot import Bot
from core.camera import Camera
from core.human import HumanMixin
from core.region_match import MatchResult
from core.control import ScriptTerminationException
from core.logger import get_logger
from core import tools, ocr
from core.input.mouse_control import click, ClickType

from PIL import Image
import numpy as np
import cv2
import random
import time


class BotConfig(BotConfigMixin):
    # --- what to attack ---
    # Monster names (as in game). The launcher puts them in RuneLite's NPC Indicators;
    # a highlighted monster is only clicked when its mouse-over says "Attack <name>".
    targets: StringListParam = StringListParam(["Cow"])
    # NPC Indicators hull colour (the launcher sets RuneLite to the first one).
    npc_colors: RGBListParam = RGBListParam([RGBParam(0, 255, 255)])  # cyan
    color_tolerance: IntParam = IntParam(40)
    # Highlights smaller than this (pixels of outline) are ignored (far away / half hidden).
    min_npc_pixels: IntParam = IntParam(60)
    targets_per_try: IntParam = IntParam(4)  # highlighted monsters to try per round
    # Monsters behind a fence: most of the herd is on our side, strays are often not.
    # Prefer monsters with others near them; avoid where an attack just failed.
    herd_radius: IntParam = IntParam(110)        # px: monsters closer than this count as neighbours
    herd_weight: FloatParam = FloatParam(35.0)   # px of distance one neighbour is worth
    lone_penalty: FloatParam = FloatParam(120.0) # extra px for a monster with no neighbours
    unreachable_memory: FloatParam = FloatParam(45.0)  # s: skip spots where a fight didn't start
    unreachable_max_px: IntParam = IntParam(250)  # forget such spots farther than this from the character
    # Not always the "best" monster: random +-px on each one's score, and sometimes the 2nd/3rd.
    rank_jitter: RangeParam = RangeParam(20, 35)
    pick_other_chance: FloatParam = FloatParam(0.15)

    # --- fighting ---
    # After clicking a monster, wait up to this long for the fight to start (walking there).
    attack_start_timeout: FloatParam = FloatParam(6.0)
    fight_check_delay: RangeParam = RangeParam(0.25, 0.5)
    max_fight_time: FloatParam = FloatParam(90.0)  # give up on one fight after this long
    # Pause after a kill before looking for the next monster (reaction time).
    after_kill_delay: RangeParam = RangeParam(0.2, 0.75)
    # Kills without any break: take a short one.
    max_kills_before_forced_break: IntParam = IntParam(70)

    # --- health (no food yet): below min_hp don't start a fight, rest until resume_hp ---
    # In % of max HP, read from the colour of the HP number on the minimap orb
    # (the game colours it green at full health, yellow at half, red when low).
    min_hp: IntParam = IntParam(30)
    resume_hp: IntParam = IntParam(50)
    # Died anyway: the bot stops and leaves the character there (exit_reason "died",
    # the launcher shows it and Telegram sends an alert).
    death_check_jump: IntParam = IntParam(40)  # HP % jump that regeneration can't explain (respawned)
    rest_check: RangeParam = RangeParam(20, 40)  # seconds between HP checks while resting
    # While resting do something small every so often (the game logs out an idle
    # player after ~5 min): turn the camera, a step via the minimap, a look at a tab.
    rest_fidget_every: RangeParam = RangeParam(40, 75)
    rest_walk_chance: FloatParam = FloatParam(0.35)
    # No kill and no resting for this long: look at the screen, save it, reset the view.
    stuck_after: FloatParam = FloatParam(480.0)

    # --- loot (RuneLite Ground Items highlights these; the launcher sets it) ---
    loot: BooleanParam = BooleanParam(True)
    loot_use: StringListParam = StringListParam(["Bones"])     # pick up and use at once (bury / eat)
    loot_keep: StringListParam = StringListParam([])  # pick up and keep (e.g. "Cowhide" once banking exists)
    loot_color: RGBParam = RGBParam(170, 0, 255)  # Ground Items highlight colour (purple)
    # After a kill the drop appears when the death animation ends: watch for it from
    # loot_wait's low end, give up at its high end; react loot_react after it shows.
    loot_wait: RangeParam = RangeParam(0.8, 3.6)
    loot_react: RangeParam = RangeParam(0.08, 0.25)
    loot_max_distance: IntParam = IntParam(170)    # px from the character: ignore loot further away
    max_loot_per_kill: IntParam = IntParam(4)      # pick-ups to try after one kill
    pickup_timeout: FloatParam = FloatParam(8.0)   # walk there + pick up
    use_delay: RangeParam = RangeParam(0.95, 1.25)  # between burying bones (the game buries one per 1.2 s)
    use_check_every: IntParam = IntParam(3)  # every N kills also look for `loot_use` items left in the inventory
    loot_zoom_notches: IntParam = IntParam(2)      # item not found: zoom in this much, try again, zoom back

    # --- nothing to attack ---
    no_target_wait: RangeParam = RangeParam(0.8, 2.2)
    max_no_target: IntParam = IntParam(40)  # stop after this many empty looks in a row
    max_retries: IntParam = IntParam(5)  # unexpected errors in a row before stopping

    # --- camera (like the woodcutter) ---
    camera_chance: FloatParam = FloatParam(0.10)  # after a kill
    camera_force_every: IntParam = IntParam(10)  # kills without a fidget: force one
    camera_rotate_time: RangeParam = RangeParam(0.3, 1.2)
    camera_zoom_chance: FloatParam = FloatParam(0.5)
    zoom_min: IntParam = IntParam(-4)
    zoom_max: IntParam = IntParam(3)
    start_zoom_in: IntParam = IntParam(14)  # home view: fully out, then this many notches in
    camera_search: BooleanParam = BooleanParam(True)  # nothing highlighted: look around
    camera_search_time: RangeParam = RangeParam(0.6, 1.4)

    # --- breaks (like the woodcutter) ---
    break_cfg: BreakCfgParam = BreakCfgParam(RangeParam(12, 40), FloatParam(0.012))
    break_ui_browse_chance: FloatParam = FloatParam(0.5)
    long_break_cfg: BreakCfgParam = BreakCfgParam(RangeParam(1500, 2000), FloatParam(0.014))
    session_max_minutes: IntParam = IntParam(210)  # forced long break after this much play

    # --- player habits (core/human.py) ---
    # Alt-tab: 1-2 s after an attack, sometimes look at another window for a while.
    alt_tab_chance: FloatParam = FloatParam(0.06)
    alt_tab_cooldown: FloatParam = FloatParam(60.0)        # s between two rolls
    alt_tab_short: RangeParam = RangeParam(4.0, 18.0)       # s
    alt_tab_medium: RangeParam = RangeParam(25.0, 90.0)     # s
    alt_tab_medium_chance: FloatParam = FloatParam(0.22)
    # Walk-away: after a kill + loot, sometimes a few steps via the minimap.
    walk_away_chance: FloatParam = FloatParam(0.018)
    walk_away_cooldown: FloatParam = FloatParam(300.0)     # s
    walk_away_tiles: RangeParam = RangeParam(3, 8)
    walk_away_pause: RangeParam = RangeParam(0.8, 2.2)
    # Rarely click a little next to the monster, then attack it again.
    misclick_chance: FloatParam = FloatParam(0.03)
    # Sometimes attack without waiting for the mouse-over text (checked after).
    skip_hover_chance: FloatParam = FloatParam(0.40)
    skip_hover_check: RangeParam = RangeParam(0.9, 1.4)    # s until "is it fighting?"
    # Bury/eat: click at once, check after this long; only then the mouse-over way.
    instant_check: RangeParam = RangeParam(0.6, 1.1)
    # Loot: the same quick click on the pile first. A plain click takes the TOP item of a
    # pile (cows: cowhide/raw beef can lie over the bones): a wrong item is dropped again,
    # and after 2 wrong ones the quick click stops for the rest of the run.
    quick_loot: BooleanParam = BooleanParam(True)
    # After a click, sometimes a short extra pause.
    micro_idle_chance: FloatParam = FloatParam(0.07)
    micro_idle: RangeParam = RangeParam(0.25, 0.9)


# Opponent Information health bar (RuneLite colours, drawn at ~90% opacity).
BAR_GREEN = (0, 146, 54)
BAR_RED = (102, 15, 16)
BAR_TOL = 30
BAR_MIN_RUN = 50     # px: the bar is ~120+ px wide
BAR_MIN_ROWS = 4     # px: and several px high
BAR_SEARCH = (0, 0, 330, 170)  # window-relative area where the overlay sits (top-left)
LOOT_MIN_W, LOOT_MIN_H = 14, 9  # px: smallest tile outline (camera zoomed far out)
LOOT_MAX_FILL = 0.6  # tile outline blob is mostly empty inside (text blobs: 0.65-0.85)
MENU_HEADER = 19     # px: 'Choose Option' row of the right-click menu
MENU_LINE = 15       # px: one menu entry
HOVER_SIM = 0.72     # OCR'd mouse-over text vs wanted text (OCR misreads letters)


def hue_mask(img: Image.Image, rgb, hue_tol: int = 10, min_sat: int = 110, min_val: int = 80) -> np.ndarray:
    """Pixels with about the same hue as `rgb` (OpenCV hue 0-179), strongly coloured.
    Tolerates RuneLite drawing outlines semi-transparent over grass, unlike an RGB match."""
    hsv = cv2.cvtColor(np.asarray(img.convert("RGB")), cv2.COLOR_RGB2HSV)
    target = cv2.cvtColor(np.uint8([[list(rgb)]]), cv2.COLOR_RGB2HSV)[0, 0, 0]
    dh = np.abs(hsv[:, :, 0].astype(np.int16) - int(target))
    dh = np.minimum(dh, 180 - dh)
    return (dh <= hue_tol) & (hsv[:, :, 1] >= min_sat) & (hsv[:, :, 2] >= min_val)


class BotExecutor(HumanMixin, Bot):
    name: str = "Slayer Bot"
    description: str = "Attacks highlighted monsters one after another (cows first)"
    tier: str = "C"
    instructions: str = """
    Set `targets` (monster names) and the loot lists. Start it from the fleet launcher:
    it sets RuneLite (NPC Indicators, Ground Items, Opponent Information) to match.
    Stand where the monsters are, pick your attack style, then start.
    No eating yet - only fight things that can't kill you. No banking yet.
    """

    def __init__(self, config: BotConfig, user=''):
        super().__init__(user, break_cfg=config.break_cfg, long_break_cfg=config.long_break_cfg,
                         break_ui_browse_chance=config.break_ui_browse_chance.value)
        self.cfg: BotConfig = config
        self.log = get_logger('SlayerBot')
        self.camera = Camera(self.client, self.cfg.zoom_min.value, self.cfg.zoom_max.value,
                             self.cfg.start_zoom_in.value)
        self.kills = 0
        self.no_target = 0
        self.failures = 0
        self.looted = 0
        self.full_warned = False
        self.attack_hover = [f"Attack {t}" for t in self.cfg.targets.value]
        self.unreachable: list[tuple[float, int, int]] = []  # (time, x, y) of failed attacks
        self.exit_reason: str | None = None  # "died" / "login_failed"
        self._progress_t = time.time()  # last kill or rest (stuck check)
        self._hp_misses = 0
        self._last_hp: tuple[float, int] | None = None  # (time, %) of the last HP reading
        self._t_click = time.time()  # last attack click

    # ------------------------------------------------------------------
    def start(self):
        self.log.info(f"Starting Slayer Bot: {', '.join(self.cfg.targets.value)}; "
                      f"loot {list(self.cfg.loot_use.value) + list(self.cfg.loot_keep.value) if self.cfg.loot.value else 'off'}")
        self.human_init()
        self.set_activity("looking for a target")
        try:
            while not self.terminate:
                try:
                    if self._step() == "stop":
                        return
                    self.failures = 0
                    continue
                except ScriptTerminationException:
                    raise
                except Exception as e:
                    if self.terminate:
                        break
                    if self.recover_window(e):  # RuneLite restarted: back in, carry on
                        self.failures = 0
                        continue
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
            self.counts["kills"] = self.kills

    def _step(self):
        if not self.watchdog():
            return "stop"
        if time.time() - self._progress_t > self.cfg.stuck_after.value:
            self.log.warning(f"No kill for {self.cfg.stuck_after.value / 60:.0f} min: checking the screen")
            self.save_debug_shot("stuck")
            self._close_menu()
            if not self.watchdog(force=True):
                return "stop"
            try:
                self.camera.top_down()
            except Exception:
                self.log.warning("Couldn't reset the camera", exc_info=True)
            self._progress_t = time.time()
        state = self.fight_state()
        if state == "fighting":
            self.set_activity("fighting")
            self._wait_fight_end()
            return
        # not fighting (no bar, or the last target's bar is empty): the moment for a break
        self.control.propose_break()
        hp = self._hp()
        self.log.debug(f"HP {hp}%")
        if hp is None:
            self._hp_misses += 1
            if self._hp_misses >= 3 and not self.watchdog(force=True):  # HP orb gone: logged out?
                return "stop"
        else:
            self._hp_misses = 0
        if self._died(hp):
            return "stop"
        if hp is not None and hp < self.cfg.min_hp.value:
            return self._rest(hp)
        if self.kills:
            self.maybe_camera_fidget()
        self.set_activity("looking for a target")
        if self.attack():
            self.no_target = 0
            self.set_activity("fighting")
            # 1-2 s after the attack click: sometimes look at another window meanwhile
            wait = self._t_click + random.uniform(1.0, 2.0) - time.time()
            if wait > 0:
                time.sleep(wait)
            if self.maybe_alt_tab(lambda: self.fight_state() == "fighting", "fight"):
                if self.fight_state() != "fighting":
                    # it died while we were away: no death moment seen, loot around us
                    self._on_kill(time.time(), saw_death=False)
            return
        self.no_target += 1
        # nothing to attack around here: a good moment to wander a few steps
        if self.no_target >= 2 and self.maybe_walk_away(prefer=True):
            return
        # nothing around: maybe it died and stands in Lumbridge
        if self.no_target in (3, 10) and self._died(None, check_chat=True):
            return "stop"
        if self.no_target > self.cfg.max_no_target.value:
            self.log.error(f"Nothing to attack for {self.no_target} tries in a row. Stopping.")
            return "stop"
        self.set_activity("searching")
        if self.cfg.camera_search.value and self.no_target >= 2:
            self.camera.search(self.cfg.camera_search_time.value, self.no_target - 1)
        wait = self.cfg.no_target_wait.choose()
        self.log.info(f"Nothing to attack; waiting {wait:.1f}s ({self.no_target}/{self.cfg.max_no_target.value})")
        time.sleep(wait)

    # ------------------------------------------------------------------ health
    def _hp(self) -> int | None:
        """HP in % of max: the red fill level of the minimap HP orb (exact), else the
        colour of the number next to it (coarse: it misread 31% as 90% once)."""
        pct = self._hp_orb()
        if pct is not None:
            return pct
        return self._hp_number_colour()

    def _died(self, hp: int | None, check_chat: bool = False) -> bool:
        """Did the character die? A dead character respawns in Lumbridge with full HP and
        the chat says "Oh dear, you are dead!". HP regenerates ~1 point a minute, so a big
        jump up between two readings means a respawn: then (or when asked) read the chat."""
        now = time.time()
        if hp is not None:
            prev = self._last_hp
            self._last_hp = (now, hp)
            if prev and now - prev[0] < 180 and hp - prev[1] >= self.cfg.death_check_jump.value:
                self.log.info(f"HP jumped {prev[1]}% -> {hp}%: checking the chat for a death")
                check_chat = True
        if not check_chat:
            return False
        try:
            text = self.client.get_chat_text().lower()
        except Exception as e:
            self.log.debug(f"Couldn't read the chat: {e}")
            return False
        if "you are dead" in text or "oh dear" in text:
            self.log.critical("The character died. Stopping and leaving it where it is.")
            self.exit_reason = "died"
            return True
        return False

    def _rest_fidget(self):
        """Something small a resting player does (and it keeps the game from logging
        out an idle player): a step via the minimap, or turn the camera, or a tab look."""
        try:
            r = random.random()
            if r < self.cfg.rest_walk_chance.value:
                # a minimap click only ever walks (a click in the world could attack a cow)
                mm = self.client.minimap.map
                cx, cy = mm.get_center()
                ang = random.uniform(0, 6.283)
                dist = random.uniform(5, 14)  # px on the minimap: ~1-3 tiles
                import math
                pt = (int(cx + dist * math.cos(ang)), int(cy + dist * math.sin(ang)))
                self.client.click(pt)
                self.log.info(f"Resting: a few steps (minimap centre {cx},{cy}, clicked {pt})")
            elif r < 0.8:
                self.camera.rotate(random.uniform(0.25, 0.8))
                self.log.info("Resting: turned the camera")
            else:
                self._browse_tabs()
                self.log.info("Resting: looked at a tab")
        except Exception:
            self.log.warning("Resting fidget failed", exc_info=True)

    def watchdog_in_game(self):
        self._close_menu()  # a menu left open swallows the next click

    def _hp_orb(self) -> int | None:
        """The HP orb fills with red from the bottom in proportion to HP. Per row of the
        orb: mostly red = filled. The heart icon sits in the empty part too, but it covers
        only about half a row, so those rows don't count as filled."""
        try:
            sc = self.client.get_screenshot()
            h = self.client.minimap.health
            # seen on the fleet: orb icon box (568,47)-(590,73), the orb circle x 548-578, y 45-70
            x1, y1, x2, y2 = h.start_x - 21, h.start_y - 4, h.start_x + 11, h.end_y
            arr = np.asarray(sc.convert("RGB").crop((x1, y1, x2, y2)), dtype=np.int16)
            r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
            red = ((r > 60) & (r > 2 * g) & (r > 2 * b)).sum(axis=1)
            dark = (~((r > 60) & (r > 2 * g) & (r > 2 * b)) & (r + g + b < 90)).sum(axis=1)
            rows = list(zip(red.tolist(), dark.tolist()))
            top = next((i for i, (rd, dk) in enumerate(rows) if rd + dk >= 10), None)
            bot = len(rows) - 1
            while bot > 0 and rows[bot][0] < 5:
                bot -= 1
            if top is None or bot - top < 15:
                self.log.debug(f"HP orb not found at ({x1},{y1})-({x2},{y2})")
                return None
            def ratio(i):
                rd, dk = rows[i]
                return rd / float(rd + dk) if rd + dk else 0.0
            # the fill's top row, with filled rows under it (the red regen-timer ring
            # around the orb can make a single top row look filled)
            fill_top = next((i for i, (rd, dk) in enumerate(rows)
                             if top <= i <= bot - 3 and rd >= 6 and ratio(i) >= 0.75
                             and all(ratio(j) >= 0.6 for j in range(i + 1, i + 4))), None)
            if fill_top is None and ratio(bot) < 0.6:
                fill_top = bot + 1  # empty
            pct = 0 if fill_top is None else round(100 * (bot - fill_top + 1) / (bot - top + 1))
            return max(0, min(100, int(pct)))
        except Exception as e:
            self.log.debug(f"Couldn't read the HP orb: {e}")
            return None

    def _hp_number_colour(self) -> int | None:
        """HP in % of max, from the colour of the number next to the minimap HP orb:
        the game draws it pure green at 100%, yellow at 50%, red near 0%.
        (Tesseract can't read those tiny 7 px digits reliably.)"""
        try:
            sc = self.client.get_screenshot()
            h = self.client.minimap.health
            # the number sits left of the orb (seen: orb icon x 568-590, its red-filled
            # circle from ~550, digits "10" at x 531-538): stay clear of the circle
            x1, y1 = max(0, h.start_x - 46), max(0, h.start_y)
            x2, y2 = h.start_x - 20, h.end_y
            arr = np.asarray(sc.convert("RGB").crop((x1, y1, x2, y2)), dtype=np.int16)
            r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
            # text pixels: fully saturated, one of red/green at max, no blue
            txt = (np.maximum(r, g) >= 245) & (b <= 30) & (np.minimum(r, g) <= 250)
            if txt.sum() < 6:
                self.log.debug(f"HP number not found near the orb ({x1},{y1})-({x2},{y2})")
                return None
            ys, xs = np.nonzero(txt)
            if not getattr(self, "_hp_logged", False):
                self._hp_logged = True
                self.log.debug(f"HP orb {h.bounding_box}, search ({x1},{y1})-({x2},{y2}); number pixels "
                               f"{sorted(set((int(x) + x1, int(r[y, x]), int(g[y, x])) for y, x in zip(ys, xs)))[:40]}")
            rm, gm = float(r[txt].mean()), float(g[txt].mean())
            if gm >= rm:   # green .. yellow: 100% .. 50%
                pct = 100 - 50 * rm / 255
            else:          # yellow .. red: 50% .. 0%
                pct = 50 * gm / 255
            return int(round(pct))
        except Exception as e:
            self.log.debug(f"Couldn't read HP: {e}")
            return None

    def _rest(self, hp: int):
        """Too hurt to fight and nothing to eat: stand still until HP comes back
        (about 1 HP a minute). Breaks still happen meanwhile."""
        self.log.warning(f"HP {hp}% < {self.cfg.min_hp.value}%: resting until {self.cfg.resume_hp.value}%")
        self.set_activity("resting")
        start = time.time()
        next_fidget = time.time() + self.cfg.rest_fidget_every.choose()
        misses = 0
        while not self.terminate and time.time() - start < 40 * 60:
            # sleep in short steps so a stop takes effect at once
            until = time.time() + self.cfg.rest_check.choose()
            while not self.terminate and time.time() < until:
                time.sleep(0.5)
                if time.time() >= next_fidget:
                    self._rest_fidget()
                    next_fidget = time.time() + self.cfg.rest_fidget_every.choose()
            if self.terminate:
                break
            self.control.propose_break()
            if not self.watchdog():
                return "stop"
            self._progress_t = time.time()
            hp = self._hp()
            misses = misses + 1 if hp is None else 0
            if misses >= 2 and not self.watchdog(force=True):
                return "stop"
            if self._died(hp):
                return "stop"
            if hp is not None and hp >= self.cfg.resume_hp.value:
                self.log.info(f"HP {hp}%: back to fighting")
                return
        if not self.terminate:
            self.log.error("HP didn't come back after 40 min. Stopping.")
            return "stop"

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
                self.log.info(f"Target down ({state}) after {time.time() - start:.0f}s - kills: {self.kills + 1}")
                self._on_kill(start)
                return

    def _on_kill(self, start: float, saw_death: bool = True):
        """The target died: loot, use items, count it; then the per-kill habits."""
        self.kills += 1
        self.counts["kills"] = self.kills
        self._progress_t = time.time()
        t0 = time.time()
        fight_s = t0 - getattr(self, "_t_fight_start", start)
        if self.cfg.loot.value:
            self.set_activity("looting")
            if saw_death:
                # what's purple on screen as the monster dies: the drop will be what's new
                before = self._loot_mask()
                self._wait_for_drop(before)
            else:
                before = None  # it died while we looked away: the drop lies around us
            t1 = time.time()
            self.pick_up_loot(before)
            t2 = time.time()
            self.use_items()
            t3 = time.time()
            self.log.info(f"Timing: fight {fight_s:.1f}s, drop wait {t1 - t0:.1f}s, "
                          f"pick-up {t2 - t1:.1f}s, use {t3 - t2:.1f}s")
        elif self.cfg.loot_use.value and self.kills % max(1, self.cfg.use_check_every.value) == 0:
            self.use_items()
        self.set_activity("looking for a target")
        time.sleep(self.cfg.after_kill_delay.choose())
        self.note_action()
        self.maybe_forced_break("max_kills_before_forced_break")
        self.maybe_walk_away()
        self._t_idle = time.time()

    def _wait_for_drop(self, before: np.ndarray):
        """Watch for new purple (the drop's highlight) instead of always waiting the
        whole death animation; react shortly after it appears."""
        lo, hi = self.cfg.loot_wait.value
        time.sleep(lo)
        grown = cv2.dilate(before.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)
        deadline = time.time() + max(0.0, hi - lo)
        while time.time() < deadline and not self.terminate:
            if int((self._loot_mask() & ~grown).sum()) >= 25:
                time.sleep(self.cfg.loot_react.choose())
                return
            time.sleep(random.uniform(0.08, 0.15))

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
        """Click a highlighted monster showing the attack text, then wait for the fight.
        Sometimes (skip_hover_chance) click at once and check the fight started after;
        if it didn't, the normal mouse-over-checked click follows."""
        self._close_menu()
        targets = self.find_targets()
        if not targets:
            self.log.debug("No highlighted monster on screen")
            return False
        order = self._rank_targets(targets)
        # mostly the best, sometimes the 2nd or 3rd - players don't always pick the same way
        if len(order) > 1 and random.random() < self.cfg.pick_other_chance.value:
            k = random.choice([1, 2] if len(order) > 2 else [1])
            order.insert(0, order.pop(k))
            self.log.debug(f"Picking monster #{k + 1} this time")
        tried = 0
        for m in order[: self.cfg.targets_per_try.value]:
            tried += 1
            # aim a bit inside the hull, not at its edge
            inner = m.scale_px(-max(2, min(m.width, m.height) // 5))
            reach_before = self._chat_image()
            if random.random() < self.cfg.skip_hover_chance.value:
                pt = inner.get_point_within()
                self.client.click(pt)
                self._t_click = time.time()
                time.sleep(self.cfg.skip_hover_check.choose())
                if self.fight_state() == "fighting":
                    self._fight_started()
                    self._after_attack(inner)
                    return True
                self.log.debug("No fight after the quick click: checking the mouse-over")
            if not self.hover_click(inner, self.attack_hover, tries=2):
                self.log.debug("Not attackable here")
                continue
            self._t_click = time.time()
            if self._wait_fight_start(reach_before):
                self._after_attack(inner)
                return True
            cx, cy = m.get_center()
            self.unreachable.append((time.time(), cx, cy))
            self.log.info("Fight didn't start (someone else's, or unreachable, e.g. behind a fence); "
                          "avoiding that spot for a while")
        self.log.debug(f"Tried {tried} highlighted monsters, none attackable")
        return False

    def _after_attack(self, inner: MatchResult):
        """Fight started: rarely a misclick next to it and attack again; maybe a short pause."""
        avoid = lambda t: (t or "").strip().lower()[:3] in ("att", "tak", "pic")
        if self.maybe_misclick(inner.get_center(), avoid=avoid):
            if self.hover_click(inner, self.attack_hover, tries=3):
                self._t_click = time.time()
                self._wait_fight_start()
        self.micro_idle()

    def _fight_started(self):
        idle = time.time() - getattr(self, "_t_idle", time.time())
        self._t_fight_start = time.time()
        self.log.info(f"Fighting ({idle:.1f}s after the last kill)" if self.kills else "Fighting")

    def _rank_targets(self, targets: list[MatchResult]) -> list[MatchResult]:
        """Near the character and in the herd first; lone strays (often behind a fence) and
        spots where an attack just failed last. A little random jitter on every score."""
        now = time.time()
        px, py = self._player_point()
        far = self.cfg.unreachable_max_px.value
        self.unreachable = [u for u in self.unreachable
                            if now - u[0] < self.cfg.unreachable_memory.value
                            and ((u[1] - px) ** 2 + (u[2] - py) ** 2) ** 0.5 <= far]
        centers = [m.get_center() for m in targets]
        r = self.cfg.herd_radius.value
        jit = self.cfg.rank_jitter.choose()
        scored = []
        for m, (cx, cy) in zip(targets, centers):
            dist = ((cx - px) ** 2 + (cy - py) ** 2) ** 0.5
            neighbours = sum(1 for (ox, oy) in centers
                             if (ox, oy) != (cx, cy) and ((ox - cx) ** 2 + (oy - cy) ** 2) ** 0.5 < r)
            score = dist - self.cfg.herd_weight.value * min(neighbours, 4)
            if neighbours == 0 and len(targets) > 2:
                score += self.cfg.lone_penalty.value
            if any(((cx - ux) ** 2 + (cy - uy) ** 2) ** 0.5 < 50 for _, ux, uy in self.unreachable):
                score += 1000  # tried there a moment ago and couldn't get to it
            score += random.uniform(-jit, jit)
            scored.append((score, m))
        scored.sort(key=lambda t: t[0])
        return [m for _, m in scored]

    # ------------------------------------------------------------------ loot
    def _player_point(self) -> tuple[int, int]:
        """Where the character stands on screen: middle of the game view."""
        chat = self.client.sectors.chat
        return (chat.start_x + chat.end_x) // 2, chat.start_y // 2 + 8

    def find_loot(self) -> list[MatchResult]:
        """Highlighted ground-item tiles near the character, nearest first."""
        sc = self.client.get_filtered_screenshot()
        raw = hue_mask(sc, self.cfg.loot_color.value)
        mask = cv2.dilate(raw.astype(np.uint8), np.ones((3, 3), np.uint8))
        num, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        px, py = self._player_point()
        found, seen = [], []
        for i in range(1, num):
            x, y, w, h, area = stats[i]
            cx, cy = x + w / 2, y + h / 2
            d = ((cx - px) ** 2 + (cy - py) ** 2) ** 0.5
            seen.append((int(x), int(y), int(w), int(h), int(area), round(d)))
            # a tile is a hollow diamond outline; item names are dense, flat rows of letters
            if w < LOOT_MIN_W or h < LOOT_MIN_H or area / float(w * h) > LOOT_MAX_FILL or w > 4 * h:
                continue
            if d > self.cfg.loot_max_distance.value:
                continue
            found.append((d, MatchResult(int(x), int(y), int(x + w), int(y + h))))
        if not found:
            # outline hidden (by the character or a cow): use the item name labels instead -
            # Ground Items stacks them just above the item, so aim a little below the lowest one
            found = self._loot_from_labels(stats, num, px, py)
        found.sort(key=lambda t: t[0])
        self.log.debug(f"Loot tiles: {len(found)} usable of {num - 1} purple blobs (player at {px},{py}); "
                       f"usable x,y,w,h: {[m.bounding_box for _, m in found[:5]]}; "
                       f"big blobs x,y,w,h,area,dist: {[b for b in seen if b[2] >= 10 and b[3] >= 9][:10]}")
        return [m for _, m in found]

    def _loot_from_labels(self, stats, num, px, py) -> list[tuple[float, MatchResult]]:
        letters = []
        for i in range(1, num):
            x, y, w, h, area = (int(v) for v in stats[i])
            if 7 <= h <= 15 and w >= 4 and area / float(w * h) > LOOT_MAX_FILL:
                letters.append((x, y, w, h))
        # join letters/words of one label line: same baseline, small gaps
        letters.sort(key=lambda b: (b[1] + b[3], b[0]))
        lines: list[list[int]] = []  # [x1, y1, x2, y2]
        for x, y, w, h in letters:
            for ln in lines:
                if abs((y + h) - ln[3]) <= 3 and x - ln[2] <= 10 and ln[0] - (x + w) <= 10:
                    ln[0], ln[1], ln[2], ln[3] = min(ln[0], x), min(ln[1], y), max(ln[2], x + w), max(ln[3], y + h)
                    break
            else:
                lines.append([x, y, x + w, y + h])
        lines = [ln for ln in lines if ln[2] - ln[0] >= 25]  # a real label, not one letter
        # a pile has several labels stacked; keep the lowest line of each stack
        piles = []
        for ln in sorted(lines, key=lambda l: -l[3]):
            cx = (ln[0] + ln[2]) / 2
            if any(abs(cx - (p[0] + p[2]) / 2) < 40 and 0 < p[1] - ln[3] < 60 for p in piles):
                continue
            piles.append(ln)
        out = []
        for x1, y1, x2, y2 in piles:
            # seen: the lowest label's bottom edge is about level with the item (tile centre)
            cx, cy = (x1 + x2) // 2, y2 + 3
            d = ((cx - px) ** 2 + (cy - py) ** 2) ** 0.5
            if d <= self.cfg.loot_max_distance.value:
                out.append((d, MatchResult(cx - 5, cy - 4, cx + 5, cy + 4)))
        if out:
            self.log.debug(f"No loot outline visible; aiming under {len(out)} item label(s)")
        return out

    def _wanted_loot(self) -> list[str]:
        """Item names worth picking up now (keep-items only while there's room for them)."""
        use = list(self.cfg.loot_use.value)
        keep = list(self.cfg.loot_keep.value)
        if self._free_slots() <= 0:
            if not self.full_warned:
                self.log.warning("Inventory full - not picking up loot (no banking yet)")
                self.full_warned = True
            return []
        self.full_warned = False
        return use + keep

    def _free_slots(self) -> int:
        from core import inventory
        self._open_inventory()
        return 28 - len(inventory.used_slots(self.client.get_screenshot()))

    def _loot_mask(self) -> np.ndarray:
        """Ground Items highlight (tile outlines + item names) as a pixel mask."""
        return hue_mask(self.client.get_filtered_screenshot(), self.cfg.loot_color.value)

    def _pile_points(self, mask: np.ndarray, around: tuple[int, int] | None = None,
                     radius: int = 80) -> list[tuple[int, int]]:
        """Where to point the mouse to find the items of one pile.
        Ground Items draws the tile outline (a diamond) with the item names stacked just
        above it, so the lowest purple pixels are the tile's bottom corner and the items
        lie a little above that. Returns points from the bottom corner upwards."""
        ys, xs = np.nonzero(mask)
        if around is not None:
            ax, ay = around
            keep = (np.abs(xs - ax) <= radius) & (np.abs(ys - ay) <= radius)
            ys, xs = ys[keep], xs[keep]
        if len(ys) < 12:
            return []
        if around is None:
            # the biggest new cluster = the new drop (ignore stray pixels)
            m = np.zeros_like(mask, dtype=np.uint8)
            m[ys, xs] = 1
            m = cv2.dilate(m, np.ones((5, 5), np.uint8))
            num, labels, stats, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
            if num <= 1:
                return []
            big = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
            sel = labels[ys, xs] == big
            ys, xs = ys[sel], xs[sel]
        ymax = int(ys.max())
        bottom = xs[ys >= ymax - 3]
        vx = int(np.median(bottom))
        # per row going up from the lowest purple: width and how full the row is
        rows = []
        for k in range(0, 70):
            row = xs[(ys == ymax - k) & (np.abs(xs - vx) <= 70)]
            if len(row) >= 2:
                ext = int(row.max() - row.min()) + 1
                rows.append((k, ext, len(row) / ext, int(row.min()), int(row.max())))
            else:
                rows.append((k, 0, 0.0, vx, vx))
        widths = [r[1] for r in rows[:20:2]]
        mid = [r[2] for r in rows[3:10] if r[1] > 0]
        hollow = bool(mid) and sum(mid) / len(mid) < 0.4  # tile outline: only its 2 sides
        pts = []
        widening = rows[0][1] <= 6 and rows[2][1] < rows[4][1] < rows[6][1]
        if widening or (hollow and rows[0][1] <= 6):
            # diamond (camera turned): bottom corner, widens going up; items in its middle
            # the outline widens steadily up to the tile's middle row (a name label on top
            # makes the width jump): the items lie around that row
            kc = 1
            for k in range(2, 50):
                a, b = rows[k - 1][1], rows[k][1]
                if b < a - 3 or b > a + 14:
                    break
                kc = k
            cx = (rows[kc][3] + rows[kc][4]) // 2
            for dx, dy in ((0, 0), (0, 3), (0, -3), (-6, 0), (6, 0), (0, 6)):
                pts.append((cx + dx + random.randint(-1, 1), ymax - kc + dy))
            for k in (4, 8, 13, 18, 24):
                pts.append((vx + random.randint(-2, 2), ymax - k))
            kind = f"diamond tile, middle {kc} px up"
        elif hollow:
            # square-ish tile (camera facing along the grid): flat bottom edge; find the top edge
            w0 = rows[0][1]
            cx = (rows[0][3] + rows[0][4]) // 2
            top = next((k for k, ext, fill, _, _ in rows[4:] if fill > 0.6 and ext >= 0.6 * w0), None)
            h = top if top else int(w0 * 0.6)
            cy = ymax - h // 2
            for dx, dy in ((0, 0), (0, -3), (0, 3), (-5, 0), (5, 0), (0, -6), (0, 6)):
                pts.append((cx + dx + random.randint(-1, 1), cy + dy))
            kind = f"square tile h={h}"
        else:
            # only an item name is purple: the item lies about level with the bottom of its name
            for k, dx in ((2, 0), (5, 0), (-2, 0), (8, 0), (3, -7), (3, 7), (11, 0)):
                pts.append((vx + dx + random.randint(-2, 2), ymax + k))
            kind = "name label"
        self.log.debug(f"Pile ({kind}): lowest purple ({vx},{ymax}), widths going up {widths}")
        return pts

    def pick_up_loot(self, before: np.ndarray | None = None):
        """Pick up wanted items of the monster's drop: find the drop as the purple that
        appeared since it died, take one item, then look again around the character
        (it now stands on the pile) for the rest."""
        spot = None
        for i in range(self.cfg.max_loot_per_kill.value):
            if self.terminate:
                return
            names = self._wanted_loot()
            if not names:
                return
            now = self._loot_mask()
            if i == 0 and before is not None:
                grown = cv2.dilate(before.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)
                pts = self._pile_points(now & ~grown)
                if not pts:
                    self.log.info("No new drop seen (nothing dropped, or it fell out of view)")
            else:
                # after a pick-up the character stands on the pile
                pts = self._pile_points(now, around=self._player_point(), radius=60)
            if not pts:
                return
            before_slots = self._free_slots()
            before_items = self._count_items(names)
            # first a plain click where the item should be (no mouse-over check)...
            quick = self._instant_take(pts[0], before_slots, before_items, names)
            if quick == "ok":
                self.looted += 1
                self.count("loot")
                self.log.info(f"Picked up loot with a quick click ({self.looted} so far)")
                time.sleep(random.uniform(0.6, 0.8))  # a game tick: the taken item's highlight goes
                continue
            if quick:
                # ...not taken (it walked onto the pile, or took something else): it now stands
                # on/next to the pile - look there, then use the mouse-over
                time.sleep(random.uniform(0.3, 0.5))
                before_slots = self._free_slots()
                pts = self._pile_points(self._loot_mask(), around=self._player_point(), radius=70) or pts
            if not self._take_from_points(pts, names):
                pts2 = self._zoom_in_for_pile(pts)
                if not pts2 or not self._take_from_points(pts2, names):
                    self.log.info("Couldn't find a wanted item on the pile")
                    self._zoom_back()
                    return
            # wait until it lands in the inventory (walk there + pick up)
            deadline = time.time() + float(self.cfg.pickup_timeout.value)
            while time.time() < deadline and not self.terminate:
                time.sleep(random.uniform(0.2, 0.35))
                if self._free_slots() < before_slots or self._count_items(names) > before_items:
                    self.looted += 1
                    self.count("loot")
                    self.log.info(f"Picked up loot ({self.looted} so far)")
                    time.sleep(random.uniform(0.5, 0.7))  # a game tick: the taken item's highlight goes
                    break
            else:
                self.log.info("Pick-up didn't happen (someone else took it?)")
                self._zoom_back()
                return
            time.sleep(random.uniform(0.1, 0.3))
        self._zoom_back()

    def _instant_take(self, pt: tuple[int, int], before_slots: int, before_items: int,
                      names: list[str]) -> str:
        """quick_loot: left-click the likeliest item spot at once, then check the inventory
        after instant_check s. "" = not tried, "ok" = got a wanted item, "miss" = nothing
        taken, "wrong" = took another item (dropped again). Skipped when a highlighted
        monster covers the spot (the click would attack it)."""
        if not self.cfg.quick_loot.value or getattr(self, "_quick_loot_off", False):
            return ""
        try:
            if any(t.scale_px(4).contains(*pt) for t in self.find_targets()):
                self.log.debug("A monster covers the loot: no quick click")
                return ""
        except Exception:
            return ""
        from core import inventory
        self._open_inventory()
        slots_before = {(r.start_x, r.start_y) for r in inventory.used_slots(self.client.get_screenshot())}
        self.client.click(pt)
        time.sleep(self.cfg.instant_check.choose())
        if self._count_items(names) > before_items:
            return "ok"
        new = [r for r in inventory.used_slots(self.client.get_screenshot())
               if (r.start_x, r.start_y) not in slots_before]
        if not new:
            return "miss"
        # took the top item of the pile, not a wanted one: drop it again
        self._wrong_quick = getattr(self, "_wrong_quick", 0) + 1
        self.log.info(f"Quick click took another item ({self._wrong_quick}x): dropping it")
        from core.input import keys as keyboard
        try:
            keyboard.press("shift")
            for r in new:
                self.client.click(r.scale_px(-6))
                time.sleep(random.uniform(0.15, 0.3))
        finally:
            keyboard.release("shift")
        if self._wrong_quick >= 2:
            self._quick_loot_off = True
            self.log.info("Quick loot clicks keep taking the wrong item here: mouse-over only from now on")
        return "wrong"

    def _zoom_in_for_pile(self, pts: list[tuple[int, int]]) -> list[tuple[int, int]]:
        """Items too small to hit: zoom in a little and look for the pile again
        (zooming moves it away from the screen centre, so search around where it should be)."""
        n = self.cfg.loot_zoom_notches.value
        if n <= 0 or getattr(self, "_loot_zoom", 0):
            return []
        done = self.camera.zoom_by(n)
        if not done:
            return []
        self._loot_zoom = done
        time.sleep(random.uniform(0.3, 0.6))
        px, py = self._player_point()
        x, y = pts[min(2, len(pts) - 1)]
        pred = (int(px + (x - px) * 1.35), int(py + (y - py) * 1.35))
        found = self._pile_points(self._loot_mask(), around=pred, radius=90)
        self.log.info(f"Zoomed in {done} to see the pile better ({'found it' if found else 'still nothing'})")
        return found

    def _zoom_back(self):
        n = getattr(self, "_loot_zoom", 0)
        if n:
            time.sleep(random.uniform(0.2, 0.6))
            self.camera.zoom_by(-n)
            self._loot_zoom = 0

    def _count_items(self, names: list[str]) -> int:
        try:
            return len(self.client.get_inv_items(names, min_confidence=0.85))
        except Exception:
            return 0

    def _take_from_points(self, pts: list[tuple[int, int]], names: list[str]) -> bool:
        """Move the mouse up the pile; left-click as soon as the mouse-over says
        "Take <wanted item>". If a monster/other item covers it, use the right-click menu."""
        hovers = [f"Take {n}" for n in names]
        menu_tried = 0
        for x, y in pts:
            self.client.move_to((x, y))
            time.sleep(random.uniform(0.05, 0.12))
            answers = self.client.get_hover_texts()
            if any(self.text_matches(a, w) for a in answers for w in hovers):
                click(-1, -1)
                return True
            # something on top ("Attack Cow", "Take Raw beef"...): the menu lists everything here
            if menu_tried < 2 and any(a.strip() for a in answers):
                menu_tried += 1
                click(-1, -1, click_type=ClickType.RIGHT)
                time.sleep(random.uniform(0.15, 0.3))
                if self.menu_pick(hovers):
                    return True
                self._close_menu()
        # last try: the menu at the likeliest spot (items' clickboxes are small)
        x, y = pts[min(2, len(pts) - 1)]
        self.client.move_to((x, y))
        click(-1, -1, click_type=ClickType.RIGHT)
        time.sleep(random.uniform(0.15, 0.3))
        if self.menu_pick(hovers):
            return True
        self._close_menu()
        return False

    def _menu_open(self) -> MatchResult | None:
        try:
            return self.client.get_right_click_menu(self.client.get_screenshot())
        except Exception:
            return None

    def _close_menu(self):
        """The game closes the right-click menu when the mouse leaves it. A menu left open
        swallows the next click (seen: the next attack click only closed the menu)."""
        for attempt in range(3):
            menu = self._menu_open()
            if menu is None:
                return
            # go clearly outside the menu box: left or right of it, at its height
            gap = random.randint(25, 60) + 30 * attempt
            if random.random() < 0.5 and menu.start_x - gap > 15:
                x = menu.start_x - gap
            else:
                x = menu.end_x + gap
            y = random.randint(menu.start_y, max(menu.start_y + 1, menu.end_y))
            self.client.move_to((x, y))
            time.sleep(random.uniform(0.15, 0.3))
        if self._menu_open() is not None:
            self.log.warning("Right-click menu didn't close")

    def _take(self, tile: MatchResult, names: list[str]) -> bool:
        """Left-click the tile if its top action is "Take <wanted item>"; otherwise (another
        item or a monster on top) pick "Take <item>" from the right-click menu."""
        hovers = [f"Take {n}" for n in names]
        # items lie in the middle of the tile (the outline is a diamond, its box corners are
        # off the tile) and their models are small: try a few points around the centre
        cx, cy = (tile.start_x + tile.end_x) // 2, (tile.start_y + tile.end_y) // 2
        dx, dy = max(2, tile.width // 6), max(2, tile.height // 6)
        inner = MatchResult(cx - dx, cy - dy, cx + dx, cy + dy)
        if self.hover_click(inner, hovers, tries=3):
            return True
        self.client.move_to(inner.get_point_within())
        # the cursor is on the tile now: open the menu there
        click(-1, -1, click_type=ClickType.RIGHT)
        time.sleep(random.uniform(0.15, 0.3))
        if self.menu_pick(hovers):
            return True
        # nothing wanted there: the game closes the menu when the mouse moves away from it
        x, y = self.client.mouse_position()
        self.client.move_to((max(10, x + random.choice((-1, 1)) * random.randint(140, 200)),
                             max(10, y + random.randint(-40, 40))))
        return False

    # ------------------------------------------------------------------ text-checked clicks
    @staticmethod
    def text_matches(text: str, wanted: str) -> bool:
        """OCR-tolerant: 'Taka Cowids' matches 'Take Cowhide'. The verb and the name are
        checked separately so 'Attack Chicken' never passes for 'Attack Cow'."""
        text = (text or "").lower().strip()
        if not text:
            return False
        verb, _, name = wanted.lower().partition(" ")
        if verb != "*" and tools.text_similarity(text, verb) < HOVER_SIM:
            return False
        rest = text.split(" ", 1)[1] if " " in text else text
        if verb == "*":
            rest = text  # any verb: look for the name anywhere
        if len(name) <= 4:
            return name in rest
        from difflib import SequenceMatcher
        sim = max(tools.text_similarity(rest, name),  # name inside a longer text
                  SequenceMatcher(None, rest[:len(name) + 2], name).ratio())  # OCR dropped letters
        return sim >= HOVER_SIM

    def hover_click(self, rect: MatchResult, wanted: list[str], tries: int = 2,
                    click_type=None) -> bool:
        """Move into `rect` (centre-weighted), click only if the mouse-over text is one of `wanted`."""
        for _ in range(tries):
            self.client.move_to(rect.get_point_within())
            time.sleep(random.uniform(0.05, 0.12))
            answers = self.client.get_hover_texts()
            if any(self.text_matches(a, w) for a in answers for w in wanted):
                click(-1, -1, click_type=click_type or ClickType.LEFT)
                return True
            self.log.debug(f"Mouse-over {answers} isn't {wanted}")
        return False

    def menu_pick(self, wanted: list[str]) -> bool:
        """Read the open right-click menu line by line and click the first wanted entry."""
        try:
            sc = self.client.get_screenshot()
            menu = self.client.get_right_click_menu(sc)
        except Exception as e:
            self.log.debug(f"No right-click menu found: {e}")
            return False
        n = max(1, round((menu.height - MENU_HEADER) / MENU_LINE))
        lines = []
        for i in range(n):
            y1 = menu.start_y + MENU_HEADER + i * MENU_LINE
            row = MatchResult(menu.start_x + 3, y1, menu.end_x - 3, y1 + MENU_LINE)
            img = tools.mask_above_color_value(row.crop_in(sc), 150)
            try:
                text = ocr.execute(img, font=ocr.FontChoice.RUNESCAPE_BOLD_12,
                                   psm=ocr.TessPsm.SINGLE_LINE, raise_on_blank=False).strip()
            except Exception:
                text = ""
            lines.append(text)
            for w in wanted:
                if self.text_matches(text, w):
                    self.log.debug(f"Menu {lines}: choosing line {i + 1} '{text}' for '{w}'")
                    # aim at the text part of the line, not the menu edge
                    target = MatchResult(row.start_x + 4, y1 + 3,
                                         min(row.end_x - 4, row.start_x + 4 + 7 * len(w)), y1 + MENU_LINE - 3)
                    # no random detour here: leaving the menu box closes the menu
                    self.client.move_to(target.get_point_within(), rand_move_chance=0)
                    click(-1, -1)
                    return True
        self.log.debug(f"Menu {lines}: nothing wanted")
        return False

    def use_items(self):
        """Use every `loot_use` item in the inventory (bury bones, eat food...): first a
        plain click on each, then one more look - leftovers get the mouse-over-checked
        click. Also catches ones left from earlier (a misread, a break in between)."""
        names = list(self.cfg.loot_use.value)
        if not names:
            return
        wanted = [f"* {n}" for n in names]  # the left-click action is the use; check the name
        used = 0
        self.set_activity("burying" if any("bone" in n.lower() for n in names) else "using items")
        try:
            items = self.client.get_inv_items(names, min_confidence=0.85)
        except Exception as e:
            self.log.debug(f"Inventory check failed: {e}")
            items = []
        # quick pass: the slots don't move when an item goes
        for i, m in enumerate(items):
            if self.terminate:
                break
            self.client.click(m.scale_px(-6))
            if i < len(items) - 1:
                time.sleep(self.cfg.use_delay.choose())
        if items:
            time.sleep(self.cfg.instant_check.choose())
            try:
                left = self.client.get_inv_items(names, min_confidence=0.85)
            except Exception:
                left = []
            used = max(0, len(items) - len(left))
            for i, m in enumerate(left):
                if self.terminate:
                    break
                if not self.hover_click(m.scale_px(-6), wanted, tries=3):
                    self.log.debug("Inventory item's mouse-over didn't match; trying the next one")
                    continue
                used += 1
                if i < len(left) - 1:
                    time.sleep(self.cfg.use_delay.choose())
        if used:
            self.count("buried" if any("bone" in n.lower() for n in names) else "used", used)
            self.log.info(f"Used {used} item(s) ({', '.join(names)})")

    def _chat_image(self):
        """The chat box as it is now (cheap; only OCR'd if a fight doesn't start)."""
        try:
            return self.client.sectors.chat.crop_in(self.client.get_screenshot())
        except Exception:
            return None

    def _reach_count(self, img) -> int:
        """How many "I can't reach that!" lines a chat box image shows."""
        if img is None:
            return 10 ** 6  # unknown: never claim a new one
        try:
            text = ocr.execute(img, font=ocr.FontChoice.RUNESCAPE_PLAIN_12, psm=ocr.TessPsm.SPARSE_TEXT,
                               raise_on_blank=False, preprocess=True).lower()
        except Exception:
            return 10 ** 6
        return text.count("reach that") + text.count("reach tha!")

    def _cant_reach_count(self) -> int:
        """How many "I can't reach that!" lines the chat box shows (fenced-off monster)."""
        img = self._chat_image()
        return -1 if img is None else self._reach_count(img)

    def _wait_fight_start(self, reach_before=None) -> bool:
        deadline = time.time() + float(self.cfg.attack_start_timeout.value)
        time.sleep(random.uniform(0.3, 0.5))
        checks = 0
        while time.time() < deadline and not self.terminate:
            if self.fight_state() == "fighting":
                self._fight_started()
                return True
            checks += 1
            if reach_before is not None and checks in (3, 6) and self._cant_reach_count() > self._reach_count(reach_before):
                self.log.info("\"I can't reach that!\" - it's behind a fence")
                return False
            time.sleep(random.uniform(0.2, 0.35))
        return False


if __name__ == "__main__":
    BotExecutor(BotConfig()).start()
