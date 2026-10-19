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

    # --- fighting ---
    # After clicking a monster, wait up to this long for the fight to start (walking there).
    attack_start_timeout: FloatParam = FloatParam(8.0)
    fight_check_delay: RangeParam = RangeParam(0.6, 1.3)
    max_fight_time: FloatParam = FloatParam(90.0)  # give up on one fight after this long
    # Pause after a kill before looking for the next monster (reaction time).
    after_kill_delay: RangeParam = RangeParam(0.4, 2.2)

    # --- health (no food yet): below min_hp don't start a fight, rest until resume_hp ---
    # In % of max HP, read from the colour of the HP number on the minimap orb
    # (the game colours it green at full health, yellow at half, red when low).
    min_hp: IntParam = IntParam(50)
    resume_hp: IntParam = IntParam(90)
    rest_check: RangeParam = RangeParam(20, 40)  # seconds between HP checks while resting

    # --- loot (RuneLite Ground Items highlights these; the launcher sets it) ---
    loot: BooleanParam = BooleanParam(True)
    loot_use: StringListParam = StringListParam(["Bones"])     # pick up and use at once (bury / eat)
    loot_keep: StringListParam = StringListParam(["Cowhide"])  # pick up and keep
    loot_color: RGBParam = RGBParam(170, 0, 255)  # Ground Items highlight colour (purple)
    loot_wait: RangeParam = RangeParam(2.4, 3.4)   # after a kill: death animation, then the drop appears
    loot_max_distance: IntParam = IntParam(170)    # px from the character: ignore loot further away
    max_loot_per_kill: IntParam = IntParam(4)      # pick-ups to try after one kill
    pickup_timeout: FloatParam = FloatParam(8.0)   # walk there + pick up
    use_delay: RangeParam = RangeParam(1.1, 1.7)   # between burying bones (one per ~1.2 s)

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


class BotExecutor(Bot):
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
        self.camera = Camera(self.client, self.cfg.zoom_min.value, self.cfg.zoom_max.value)
        self.kills = 0
        self.no_target = 0
        self.failures = 0
        self.looted = 0
        self.full_warned = False
        self.attack_hover = [f"Attack {t}" for t in self.cfg.targets.value]

    # ------------------------------------------------------------------
    def start(self):
        self.log.info(f"Starting Slayer Bot: {', '.join(self.cfg.targets.value)}; "
                      f"loot {list(self.cfg.loot_use.value) + list(self.cfg.loot_keep.value) if self.cfg.loot.value else 'off'}")
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
        # not fighting (no bar, or the last target's bar is empty): the moment for a break
        self.control.propose_break()
        hp = self._hp()
        self.log.debug(f"HP {hp}%")
        if hp is not None and hp < self.cfg.min_hp.value:
            return self._rest(hp)
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

    # ------------------------------------------------------------------ health
    def _hp(self) -> int | None:
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
        start = time.time()
        while not self.terminate and time.time() - start < 40 * 60:
            time.sleep(self.cfg.rest_check.choose())
            self.control.propose_break()
            hp = self._hp()
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
                self.kills += 1
                self.log.info(f"Target down ({state}) after {time.time() - start:.0f}s - kills: {self.kills}")
                if self.cfg.loot.value:
                    time.sleep(self.cfg.loot_wait.choose())
                    self.pick_up_loot()
                    self.use_items()
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
            if not self.hover_click(inner, self.attack_hover, tries=2):
                self.log.debug("Not attackable here")
                continue
            if self._wait_fight_start():
                return True
            self.log.info("Fight didn't start (someone else's, or unreachable); trying another")
        self.log.debug(f"Tried {tried} highlighted monsters, none attackable")
        return False

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

    def pick_up_loot(self):
        last = None  # tile of the last pick-up: the rest of the pile is under the character
        for _ in range(self.cfg.max_loot_per_kill.value):
            if self.terminate:
                return
            names = self._wanted_loot()
            if not names:
                return
            tiles = self.find_loot()
            if not tiles and last is not None:
                # the character stands on the pile now and hides its outline: try the same spot
                tiles, last = [last], None
            if not tiles:
                return
            before = self._free_slots()
            taken = next((t for t in tiles[:3] if self._take(t, names)), None)
            if taken is None:
                return
            last = taken
            # wait until it lands in the inventory (walk there + pick up)
            deadline = time.time() + float(self.cfg.pickup_timeout.value)
            while time.time() < deadline and not self.terminate:
                time.sleep(random.uniform(0.4, 0.7))
                if self._free_slots() < before:
                    self.looted += 1
                    self.log.info(f"Picked up loot ({self.looted} so far)")
                    break
            else:
                self.log.info("Pick-up didn't happen (someone else took it?)")
            time.sleep(random.uniform(0.15, 0.5))

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
        self.client.move_to(inner.get_point_within(), rand_move_chance=0)
        # the cursor is on the tile now: open the menu there
        click(-1, -1, click_type=ClickType.RIGHT)
        time.sleep(random.uniform(0.25, 0.45))
        if self.menu_pick(hovers):
            return True
        # nothing wanted there: the game closes the menu when the mouse moves away from it
        x, y = self.client.mouse_position()
        self.client.move_to((max(10, x + random.choice((-1, 1)) * random.randint(140, 200)),
                             max(10, y + random.randint(-40, 40))), rand_move_chance=0)
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
        if tools.text_similarity(text, verb) < HOVER_SIM:
            return False
        rest = text.split(" ", 1)[1] if " " in text else text
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
            self.client.move_to(rect.get_point_within(), rand_move_chance=0)
            time.sleep(random.uniform(0.1, 0.22))
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
                    self.client.move_to(target.get_point_within(), rand_move_chance=0)
                    click(-1, -1)
                    return True
        self.log.debug(f"Menu {lines}: nothing wanted")
        return False

    def use_items(self):
        """Left-click every `loot_use` item in the inventory (bury bones, eat food...)."""
        names = list(self.cfg.loot_use.value)
        if not names:
            return
        for _ in range(28):
            if self.terminate:
                return
            try:
                items = self.client.get_inv_items(names, min_confidence=0.9)
            except Exception as e:
                self.log.debug(f"Inventory check failed: {e}")
                return
            if not items:
                self.log.debug(f"No {names} in the inventory")
                return
            m = items[0]
            # mouse-over of an inventory item: "Bury Bones", "Eat Trout"...
            wanted = [f"{v} {n}" for n in names for v in ("Bury", "Eat", "Drink", "Use")]
            if not self.hover_click(m.scale_px(-6), wanted, tries=2):
                self.log.debug("Inventory item's mouse-over didn't match; not using it")
                return
            self.log.info("Used an item")
            time.sleep(self.cfg.use_delay.choose())

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
