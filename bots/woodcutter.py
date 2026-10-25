from bots.core import BotConfigMixin
from bots.core.cfg_types import StringListParam, BooleanParam, StringParam, IntParam, FloatParam, RGBParam, RangeParam, BreakCfgParam, RGBListParam, RouteParam, WaypointParam, ItemParam
from core.bot import Bot
from core.bank import BankInterface
from core.human import HumanMixin

from core import tools, inventory
from core.camera import Camera
from core.region_match import MatchResult
from core.osrs_client import ToolplaneTab
from core.control import ScriptControl, ScriptTerminationException

from PIL import Image
import random
import time
import pyautogui
from core.logger import get_logger
import sys
from core.input import keys as keyboard  # works on Windows and on fleet virtual displays

class BotConfig(BotConfigMixin): 
    # Configuration parameters

    # Tree configuration
    tree_tiles: RGBListParam = RGBListParam([
        RGBParam(255, 0, 255),  # Magenta by default
        RGBParam(255, 0, 200),  # Another shade
        #RGBParam(255, 0, 150),  # Yet another shade
    ])
    # Retry configuration
    max_retries: IntParam = IntParam(3)  # Maximum number of retries before giving up
    
    # Optional configuration
    chop_click_delay: RangeParam = RangeParam(0.25, 0.65)
    inventory_check_delay: RangeParam = RangeParam(1.6, 3.4)
    # Wait until the player stops walking after clicking a tree. Needs RuneLite's
    # player position overlay; without it every click wastes ~5 s retrying.
    wait_while_walking: BooleanParam = BooleanParam(False)
    
    break_cfg: BreakCfgParam = BreakCfgParam(
        RangeParam(12, 40),  # break duration range in seconds
        FloatParam(0.012)    # break chance
    )
    # Chance a short break is spent looking through the side-panel tabs
    # (skills, quests, equipment...) before going back to the inventory.
    break_ui_browse_chance: FloatParam = FloatParam(0.5)
    # Long break: AFK long enough to get logged out (logs back in after),
    # at most once every 90 minutes.
    long_break_cfg: BreakCfgParam = BreakCfgParam(
        RangeParam(1500, 2000),  # 25-33 minutes, logged out
        FloatParam(0.014)
    )
    # Forced long break after this much play (minutes) without one.
    session_max_minutes: IntParam = IntParam(210)

    # --- player habits (core/human.py) ---
    # Alt-tab: 1-2 s after a tree click, sometimes look at another window for a while.
    alt_tab_chance: FloatParam = FloatParam(0.2)  # per roll: short 18.7% (doubled twice), medium 1.3%
    alt_tab_cooldown: FloatParam = FloatParam(60.0)        # s between two rolls
    alt_tab_short: RangeParam = RangeParam(4.0, 18.0)       # s
    alt_tab_medium: RangeParam = RangeParam(25.0, 90.0)     # s
    alt_tab_medium_chance: FloatParam = FloatParam(0.066)
    # Walk-away: after dropping/banking, sometimes a few steps via the minimap.
    walk_away_chance: FloatParam = FloatParam(0.0)        # off until pathfinding exists (it got the bots lost)
    walk_away_cooldown: FloatParam = FloatParam(300.0)     # s
    walk_away_tiles: RangeParam = RangeParam(3, 8)
    walk_away_pause: RangeParam = RangeParam(0.8, 2.2)
    # Rarely click a little next to the tree, then click the tree again.
    misclick_chance: FloatParam = FloatParam(0.025)
    # Sometimes click a tree without waiting for its mouse-over text (checked after).
    skip_hover_chance: FloatParam = FloatParam(0.40)
    skip_hover_check: RangeParam = RangeParam(0.9, 1.4)    # s until "is it chopping?"
    # A quick click is sometimes a fast double click.
    double_click_chance: FloatParam = FloatParam(0.40)
    double_click_gap: RangeParam = RangeParam(0.08, 0.16)  # s between the two clicks
    # After a click, sometimes a short extra pause.
    micro_idle_chance: FloatParam = FloatParam(0.07)
    micro_idle: RangeParam = RangeParam(0.25, 0.9)
    # Tree colours: sometimes a random order instead of cycling through them.
    color_shuffle_chance: FloatParam = FloatParam(0.20)
    # Before a click, sometimes move the mouse a bit away and back.
    pre_click_wiggle_chance: FloatParam = FloatParam(0.08)

    ###########################################
    # Willows at Draynor Village
    ###########################################
    log_type: ItemParam = ItemParam("Willow logs")  # Default log name
    # Mouse-over text a marked tree must show before the bot clicks it, so a marked
    # tree of the wrong type is skipped. "Chop down Tree" = normal trees only;
    # e.g. "Chop down Oak" for oaks, "Chop down Willow" for willows.
    tree_hover: StringParam = StringParam("Chop down Tree")
    trees_per_color: IntParam = IntParam(4)  # marked trees of one colour to try per round
    # Drop mode: never drop these (an axe carried in the inventory).
    keep_items: StringListParam = StringListParam([
        "Bronze axe", "Iron axe", "Steel axe", "Black axe", "Mithril axe", "Adamant axe", "Rune axe",
        "Tinderbox",
    ])
    # After clicking a tree, wait up to this long (seconds) for chopping to start,
    # e.g. while the character walks there, before clicking anything else.
    chop_start_timeout: FloatParam = FloatParam(11.0)
    drop_items: BooleanParam = BooleanParam(False)  # True = drop logs, False = bank logs
    # Firemaking: after each tree, light the logs right away (left-click the tinderbox, then
    # a log). The character steps aside after each fire; where a fire can't be lit (a fire
    # already there, a blocked tile) it walks a few tiles and tries again.
    burn_logs: BooleanParam = BooleanParam(False)
    tinderbox: ItemParam = ItemParam("Tinderbox")
    fire_timeout: FloatParam = FloatParam(6.0)         # s for the log to leave the inventory (else: can't light here)
    fire_timeout_max: FloatParam = FloatParam(60.0)    # s kneeling until the fire catches (low level: long)
    fire_step_px: FloatParam = FloatParam(1.0)         # minimap move (px) = the character stepped off the fire
    fire_step_diff: FloatParam = FloatParam(8.0)       # ...or this much change of the minimap picture
    home_match: FloatParam = FloatParam(0.6)           # minimap match needed to walk back to the trees
    home_max_tiles: FloatParam = FloatParam(8.0)       # farther than this from the trees -> walk back
    home_tile: StringParam = StringParam("")           # "x,y" world tile of the trees (empty = where the bot starts)
    fire_moves: IntParam = IntParam(3)                 # moves to another spot before giving up on a log
    fire_move_tiles: RangeParam = RangeParam(1, 1)      # can't light here: step this far (1 tile is enough)
    fire_click_gap: RangeParam = RangeParam(0.15, 0.45)  # between tinderbox and log click
    fire_step_wait: RangeParam = RangeParam(0.7, 1.3)    # after a fire: the character steps aside
    bank_tile: RGBParam = RGBParam(0, 255, 0)  # Green by default, only used when banking
    bank_to_trees: RouteParam = RouteParam([
        # WaypointParam(3094, 3244, 0, 790933, 8),
        WaypointParam(3105, 3240, 0, 790932, 8),
        WaypointParam(3091, 3230, 0, 790932, 5)
    ])  # Empty default route, configure in UI
    inv_full_at: IntParam = IntParam(27)  # Default inventory capacity

    # Drop mode: when every marked tree is a stump, wait here for one to grow back
    # instead of walking the bank route.
    tree_respawn_wait: RangeParam = RangeParam(1.5, 4.0)
    max_tree_waits: IntParam = IntParam(40)  # stop after this many waits in a row
    # Trees cut without any break: take a short one (0 = off).
    max_trees_before_forced_break: IntParam = IntParam(0)

    # Camera: after a tree is cut, this chance to rotate / zoom the camera a bit
    camera_chance: FloatParam = FloatParam(0.10)
    camera_force_every: IntParam = IntParam(10)  # trees cut without a fidget: force one
    camera_rotate_time: RangeParam = RangeParam(0.3, 1.2)  # seconds holding an arrow key (~3 s = full turn)
    camera_zoom_chance: FloatParam = FloatParam(0.5)       # chance a fidget also zooms
    zoom_min: IntParam = IntParam(-4)  # wheel notches out from the starting zoom (limit)
    zoom_max: IntParam = IntParam(3)   # wheel notches in from the starting zoom (limit)
    start_zoom_in: IntParam = IntParam(14)  # home view: fully out, then this many notches in
    # No marked tree visible: turn the camera to look for one (from the 2nd miss in a row)
    camera_search: BooleanParam = BooleanParam(True)
    camera_search_time: RangeParam = RangeParam(0.6, 1.4)

    
    
    ###########################################
    # Oaks at east Varrock
    ###########################################
    # log_type: StringParam = StringParam("Oak logs")  # Default log name
    # drop_items: BooleanParam = BooleanParam(False)  # True = drop logs, False = bank logs
    # bank_tile: RGBParam = RGBParam(0, 255, 0)  # Green by default, only used when banking
    # bank_to_trees: RouteParam = RouteParam([
    #     WaypointParam(3253, 3428, 0, 838060, 5),
    #     WaypointParam(3275, 3428, 0, 838060, 5)
    # ])  # Empty default route, configure in UI
    # inv_full_at: IntParam = IntParam(28)  # Default inventory capacity
    
    
class BotExecutor(HumanMixin, Bot):
    name: str = "Woodcutter Bot"
    description: str = "A bot that chops trees and banks or drops logs when inventory is full"
    tier: str = "B"
    instructions: str = """
    This bot will chop trees of the specified type and either drop or bank the logs when the inventory is full.
    Banking function will drop reliability since the movement orchestrator is not perfect.
    Dropping should be more reliable but not profitable.
    """
    
    
    def __init__(self, config: BotConfig, user=''):
        super().__init__(user, break_cfg=config.break_cfg, long_break_cfg=config.long_break_cfg,
                         break_ui_browse_chance=config.break_ui_browse_chance.value)
        self.cfg: BotConfig = config
        self.log = get_logger('WoodcutterBot')
        self.consecutive_failures = 0
        self.tree_index = 0  # Used to cycle through tree tiles
        self.tree_waits = 0  # drop mode: waits in a row with no marked tree
        self.camera = Camera(self.client, self.cfg.zoom_min.value, self.cfg.zoom_max.value,
                             self.cfg.start_zoom_in.value)
        self.chopped_once = False
        # firemaking: no left/right camera turns, so the minimap keeps its orientation and
        # the bot can walk back to the trees by finding a remembered minimap patch
        if self.cfg.burn_logs.value:
            self.camera.allow_rotate = False
        self._last_used: int | None = None  # inventory slots used at the last look (log counter)
        
        if not self.cfg.drop_items.value and not self.cfg.bank_to_trees.value:
            self.log.warning("Banking enabled but no route specified. Please set bank_to_trees in the config.")
            
        if not self.cfg.drop_items.value:
            self.bank = BankInterface(self.client, self.client.item_db)
        
    def start(self):
        self.log.info(f"Starting Woodcutter Bot for {self.cfg.log_type.name} "
                      f"({'drop' if self.cfg.drop_items.value else 'bank'} mode)")
        self.human_init()
        self.set_activity("working")
        # the run starts at the trees: remember where (World Location tile; minimap fallback)
        try:
            self.remember_home()
        except Exception:
            self.log.warning("Couldn't remember the tree area yet", exc_info=True)
        
        while not self.terminate:
            try:
                if not self.watchdog():  # logged out / disconnected and couldn't get back in
                    break
                # Check if inventory is full
                if self.check_inventory_full():
                    if self.cfg.drop_items.value and self.cfg.burn_logs.value:
                        # firemaking: light all logs once the inventory is full, then back to the trees
                        self.log.info("Inventory is full. Lighting the logs...")
                        self.burn_logs()
                        self.go_home(max_tiles=2, label="the trees")
                        if self.check_inventory_full():  # some logs couldn't be lit: drop them
                            self.set_activity("dropping")
                            self.drop_logs()
                    elif self.cfg.drop_items.value:
                        self.log.info("Inventory is full. Dropping logs...")
                        self.set_activity("dropping")
                        self.drop_logs()
                        self.go_home(max_tiles=self.cfg.home_max_tiles.value, label="the trees")
                    else:
                        self.log.info("Inventory is full. Banking logs...")
                        if not self.bank_trip():
                            self.log.error("Banking failed twice in a row. Stopping.")
                            self.exit_reason = "bank_failed"
                            return
                    self.set_activity("working")
                    # a finished cycle: now and then a few steps elsewhere
                    self.maybe_walk_away()
                
                # Check if we're woodcutting, if not, click on tree
                if not self.client.is_woodcutting:
                    try:
                        self.log.info("Not woodcutting. Clicking tree...")
                        self.set_activity("working")
                        # a tree was just cut: sometimes fidget with the camera first
                        if self.chopped_once:
                            self.note_action()
                            self.maybe_camera_fidget()
                            self.maybe_forced_break("max_trees_before_forced_break")
                        self.chop_tree()
                        self.chopped_once = True
                        self.tree_waits = 0
                    except ScriptTerminationException:
                        raise
                    except Exception as e:
                        if self.terminate:
                            break
                        if self.cfg.drop_items.value:
                            # Marked trees are stumps (their marker disappears): wait for respawn.
                            self.tree_waits += 1
                            self.set_activity("waiting for trees")
                            if self.tree_waits > self.cfg.max_tree_waits.value:
                                self.log.error(f"No marked tree for {self.tree_waits} tries in a row. Stopping.")
                                return
                            # firemaking drifts away from the trees (one tile per fire): go back
                            if self.tree_waits >= 2 and self.go_home(max_tiles=3, label="the trees"):
                                self.tree_waits = 0
                                continue
                            # all stumps: a good moment to wander a few steps
                            if self.tree_waits >= 2 and self.maybe_walk_away(prefer=True):
                                continue
                            if self.cfg.camera_search.value and self.tree_waits >= 2:
                                self.camera.search(self.cfg.camera_search_time.value, self.tree_waits - 1)
                            wait = self.cfg.tree_respawn_wait.choose()
                            self.log.info(f"No marked tree available ({e}); waiting {wait:.1f}s "
                                          f"({self.tree_waits}/{self.cfg.max_tree_waits.value})")
                            time.sleep(wait)
                            self.control.propose_break()
                            continue
                        if self.cfg.camera_search.value:
                            # maybe the trees are just out of view: look around once first
                            self.camera.search(self.cfg.camera_search_time.value, 1)
                            try:
                                self.chop_tree()
                                continue
                            except ScriptTerminationException:
                                raise
                            except Exception:
                                pass
                        self.log.warning(f"Did we die or something? walking to trees: {e}")
                        self.set_activity("walking")
                        self.mover.execute_route(self.cfg.bank_to_trees)
                        self.chop_tree()
                
                # Wait a bit before checking status again
                time.sleep(self.cfg.inventory_check_delay.choose())
                
                # Reset consecutive failures counter on successful cycle
                self.consecutive_failures = 0

                # Check if we should propose a break
                self.control.propose_break()
                
            except ScriptTerminationException:
                break
            except Exception as e:
                if self.terminate:
                    break
                if self.recover_window(e):  # RuneLite restarted: back in, carry on
                    self.consecutive_failures = 0
                    continue
                self.consecutive_failures += 1
                self.log.error(f"Error in woodcutting process: {e}")
                
                if self.consecutive_failures > self.cfg.max_retries.value:
                    self.log.critical(f"Failed {self.consecutive_failures} times in a row. Exiting.")
                    return
                else:
                    self.log.warning(f"Retry attempt {self.consecutive_failures}/{self.cfg.max_retries.value}")
                    time.sleep(3)  # Wait a bit before retrying

    # ------------------------------------------------------------------ banking
    def bank_trip(self) -> bool:
        """Walk to the bank, deposit, walk back. The whole trip is tried once more if any
        part of it fails."""
        for attempt in (1, 2):
            if self.terminate:
                return True
            try:
                self.set_activity("walking to bank")
                self.log.info("Traveling to bank...")
                self.mover.execute_route(self.cfg.bank_to_trees.reverse())
                self.set_activity("banking")
                if not self.bank_logs():
                    raise RuntimeError("couldn't bank the logs")
                self.set_activity("walking to trees")
                self.log.info("Returning to trees...")
                self.mover.execute_route(self.cfg.bank_to_trees)
                return True
            except ScriptTerminationException:
                raise
            except Exception as e:
                self.log.error(f"Bank trip failed (attempt {attempt}/2): {e}")
                time.sleep(random.uniform(1.5, 3.0))
        return False

    # ------------------------------------------------------------------ chopping
    def _color_order(self) -> list:
        """Tree colours to try: usually cycling (start after the last one used),
        sometimes a random order."""
        tiles = list(self.cfg.tree_tiles.value)
        if random.random() < self.cfg.color_shuffle_chance.value:
            random.shuffle(tiles)
            return [(None, c) for c in tiles]
        return [((self.tree_index + i) % len(tiles), tiles[(self.tree_index + i) % len(tiles)])
                for i in range(len(tiles))]

    def chop_tree(self):
        """Click a marked tree. Tries every tree colour once, so a stump (its marker is
        gone) costs no extra waiting."""
        tree_tiles = self.cfg.tree_tiles.value

        if not tree_tiles:
            self.log.error("No tree tile colors specified")
            return False

        errors = []
        clicked = False
        for idx, current_tree in self._color_order():
            try:
                clicked = self._click_tree_of_color(current_tree)
            except ScriptTerminationException:
                raise
            except Exception as e:
                errors.append(f"{current_tree.to_hex()}: {e}")
                continue
            if clicked:
                if idx is not None:
                    self.tree_index = idx + 1
                break
            errors.append(f"{current_tree.to_hex()}: no tree showing '{self.cfg.tree_hover.value}'")
        if not clicked:
            raise RuntimeError("no marked tree found (" + "; ".join(errors) + ")")

        if not self.cfg.wait_while_walking.value:
            return

        # Wait until character stops moving
        start_time = time.time()
        timeout = 15  # Timeout after 15 seconds
        
        while time.time() - start_time < timeout and not self.terminate:
            if not self.client.is_moving():
                break
            time.sleep(0.2)
    
    def _wait_for_chop_start(self, timeout: float | None = None) -> bool:
        """Don't click another tree while the character is still walking to this one:
        wait until the Woodcutting overlay says we're chopping (or a timeout)."""
        deadline = time.time() + float(timeout if timeout is not None else self.cfg.chop_start_timeout.value)
        while time.time() < deadline and not self.terminate:
            if self.client.is_woodcutting:
                return True
            time.sleep(random.uniform(0.4, 0.8))
        self.log.debug("Chopping didn't start before the timeout")
        return False

    def _wiggle(self, near: tuple[int, int]) -> None:
        """Mouse a little away from the target and back (a player's hand isn't still)."""
        if random.random() >= self.cfg.pre_click_wiggle_chance.value:
            return
        import math
        d, a = random.uniform(25, 60), random.uniform(0, 2 * math.pi)
        self.client.move_to((int(near[0] + d * math.cos(a)), int(near[1] + d * math.sin(a))))
        time.sleep(random.uniform(0.08, 0.3))

    def _instant_click(self, target: MatchResult) -> bool:
        """Click the tree without reading its mouse-over first, then check that chopping
        started. False = it didn't (walking, wrong spot, wrong tree): caller verifies."""
        pt = target.get_point_within()
        self._wiggle(pt)
        self.quick_click(pt)
        self.log.debug(f"Clicked a tree without the mouse-over check at {pt}")
        time.sleep(self.cfg.skip_hover_check.choose())
        if self.client.is_woodcutting:
            return True
        return False

    def _after_click(self, target: MatchResult) -> None:
        """A tree was clicked: maybe a misclick + re-click, wait until chopping starts,
        maybe a short pause, maybe alt-tab while it chops."""
        t_click = time.time()
        if self.maybe_misclick(target.get_center()):
            self.client.smart_click_match(target, [self.cfg.tree_hover.value], retry_hover=3)
            t_click = time.time()
        time.sleep(self.cfg.chop_click_delay.choose())
        started = self._wait_for_chop_start()
        self.micro_idle()
        if started:
            wait = t_click + random.uniform(1.0, 2.0) - time.time()
            if wait > 0:
                time.sleep(wait)
            self.maybe_alt_tab(lambda: self.client.is_woodcutting, "chopping")

    def _click_tree_of_color(self, color: RGBParam) -> bool:
        """Click a marked tree of this colour whose mouse-over text matches tree_hover.
        Tries the biggest marked tree first; if it is the wrong kind (e.g. an oak
        at low level), hides it and tries the next one."""
        skip: list[MatchResult] = []
        for _ in range(self.cfg.trees_per_color.value):
            sc = self.client.get_screenshot()
            for m in skip:
                sc = m.remove_from(sc)
            match = tools.find_color_box(sc, color.value, tol=40)  # raises when none left
            inner = match  # the clickbox outline (a polygon): aim inside it
            if random.random() < self.cfg.skip_hover_chance.value:
                if self._instant_click(inner):
                    self._after_click(inner)
                    return True
                self.log.debug("No chopping after the quick click: checking the mouse-over")
            try:
                self._wiggle(match.get_center())
                self.client.smart_click_match(match, [self.cfg.tree_hover.value],
                                              retry_hover=3, center_point=False)
                self._after_click(match)
                return True
            except RuntimeError as e:
                self.log.debug(f"Skipping marked tree ({e})")
                x1, y1, x2, y2 = match.bounding_box
                skip.append(MatchResult(x1 - 4, y1 - 4, x2 + 4, y2 + 4))
        return False

    # ------------------------------------------------------------------ inventory
    # ------------------------------------------------------------------ firemaking
    def _inv(self, name: str) -> list[MatchResult]:
        try:
            return self.client.get_inv_items([name], min_confidence=0.9)
        except ScriptTerminationException:
            raise
        except Exception:
            return []

    def _hover_has(self, *words: str) -> bool:
        """The mouse-over text names all these words (OCR-tolerant: a word may lose a letter)."""
        from difflib import SequenceMatcher
        texts = [t.lower() for t in self.client.get_hover_texts() if t]
        def has(t, w):
            if w in t:
                return True
            # OCR misreads letters ("Tinderbox" -> "timdarbax", "Logs" -> "lags")
            return any(SequenceMatcher(None, tok, w).ratio() >= 0.55 for tok in t.replace(">", " ").split())
        ok = any(all(has(t, w.lower()) for w in words) for t in texts)
        if not ok:
            self.log.debug(f"Mouse-over {texts} doesn't name {words}")
        return ok

    SELECTED_WHITE = 15  # white px in a slot: a selected item has a white outline (seen 39-67; else 0)

    def _selected(self, slot: MatchResult, sc=None) -> bool:
        """The item in this inventory slot is selected ("Use ... ->"): the game draws a white
        outline around it. Checked on the screen, not via the (often cut) mouse-over OCR."""
        import numpy as np
        sc = sc or self.client.get_screenshot()
        x1, y1, x2, y2 = slot.bounding_box
        a = np.asarray(sc.convert("RGB").crop((x1, y1, x2, y2)))
        return int((a.min(axis=2) >= 240).sum()) >= self.SELECTED_WHITE

    def _press_and_check(self, slot: MatchResult, quick: bool) -> bool:
        """Click an inventory slot (quick, or after the mouse is on it) and return whether
        the item is selected afterwards."""
        from core.input.mouse_control import press
        if quick:
            self.click_inv(slot)
        else:
            press()
        time.sleep(random.uniform(0.05, 0.11))
        return self._selected(slot)

    def _use_tinderbox_on(self, tinder: MatchResult, log: MatchResult, careful: bool = False) -> bool:
        """Tinderbox, then the log. Every step is checked on the screen: after the tinderbox
        click it must have the white "selected" outline, otherwise it is clicked again.
        Quick clicks (skip_hover_chance) skip the mouse-over read, normal ones read it
        first; never when `careful`. No double clicks: a second click would undo the select."""
        from core.input.mouse_control import press
        sc = self.client.get_screenshot()
        # leftover selection from an earlier try
        if self._selected(tinder, sc):
            self.log.debug("The tinderbox was still selected")
        else:
            sel_log = next((m for m in self._inv(self.cfg.log_type.name)
                            if self._selected(self.inv_slot(m), sc)), None)
            if sel_log is not None:
                # a log is selected: clicking the tinderbox uses it on the log = lights it
                self.log.debug("A log was selected: using it on the tinderbox")
                self.click_inv(tinder)
                return True
            selected = False
            for i in range(2):
                quick = not careful and i == 0 and random.random() < self.cfg.skip_hover_chance.value
                if not quick:
                    self.move_inv(tinder)
                    time.sleep(random.uniform(0.06, 0.14))
                    if not self._hover_has("tinderbox"):
                        if self._inv(self.cfg.tinderbox.name):
                            self._tinder = None  # it moved: look for it again
                        return False
                if self._press_and_check(tinder, quick):
                    selected = True
                    break
                self.log.info("The tinderbox click didn't select it: clicking it again")
            if not selected:
                return False
        time.sleep(self.cfg.fire_click_gap.choose())
        quick = not careful and random.random() < self.cfg.skip_hover_chance.value
        if quick:
            self.click_inv(log)
        else:
            self.move_inv(log)
            time.sleep(random.uniform(0.06, 0.14))
            # "Use Tinderbox -> Logs": OCR often keeps only a part, any mention of logs will do
            if not self._hover_has("log"):
                self.click_inv(tinder)  # put the tinderbox down, try again
                return False
            press()
        time.sleep(random.uniform(0.05, 0.11))
        if self._selected(tinder):
            # the log click didn't land: still selected - one more go at the log
            self.log.info("The log click didn't land: clicking the log again")
            self.click_inv(log)
        return True

    def _slot_empty(self, slot: MatchResult) -> bool:
        used = inventory.used_slots(self.client.get_screenshot())
        return not any(abs(r.start_x - slot.start_x) < 4 and abs(r.start_y - slot.start_y) < 4 for r in used)

    def _minimap_gray(self):
        """The minimap as a grey float image (for measuring how far the view moved)."""
        import numpy as np
        sc = self.client.get_screenshot()
        mm = self.client.minimap.map
        x1, y1, x2, y2 = mm.bounding_box
        # the middle of the minimap: no compass/orbs at the edges
        w, h = x2 - x1, y2 - y1
        box = (x1 + w // 5, y1 + h // 5, x2 - w // 5, y2 - h // 5)
        return np.asarray(sc.convert("L").crop(box), dtype=np.float32)

    @staticmethod
    def _shift(a, b) -> tuple[float, float]:
        """(px the minimap moved, mean pixel difference). Measured while lighting: kneeling
        0.0 px / diff < 1; the step off the fire 1.2-1.6 px / diff ~30."""
        import cv2
        import numpy as np
        if a is None or b is None or a.shape != b.shape:
            return 0.0, 0.0
        win = cv2.createHanningWindow(a.shape[::-1], cv2.CV_32F)
        (dx, dy), resp = cv2.phaseCorrelate(a, b, win)
        px = float(np.hypot(dx, dy)) if resp > 0.05 else 0.0
        return px, float(np.abs(a - b).mean())

    def _stepped(self, ref) -> bool:
        px, diff = self._shift(ref, self._minimap_gray())
        return px >= self.cfg.fire_step_px.value or diff >= self.cfg.fire_step_diff.value

    # ------------------------------------------------------------ chat (newest line)
    CANT_LIGHT = ("light a fire here", "cant light", "can't light")
    FIRE_CAUGHT = ("fire catches", "begin to burn")
    LIGHTING = ("attempt to light",)

    def _chat_box(self, sc=None):
        """Grey image of the chat messages (to notice a new message cheaply)."""
        import numpy as np
        sc = sc or self.client.get_screenshot()
        c = self.client.sectors.chat
        return np.asarray(sc.convert("L").crop((c.start_x + 6, c.start_y + 4, c.end_x - 17, c.end_y - 22)),
                          dtype=np.float32)

    def _chat_newest(self, sc=None) -> str:
        """OCR of the newest chat message line (just above the typing line), lower case."""
        from core import ocr
        sc = sc or self.client.get_screenshot()
        c = self.client.sectors.chat
        line = sc.crop((c.start_x + 6, c.end_y - 37, c.end_x - 17, c.end_y - 22))
        line = line.resize((line.width * 2, line.height * 2))
        try:
            return ocr.execute(line, font=ocr.FontChoice.RUNESCAPE_PLAIN_12, psm=ocr.TessPsm.SINGLE_LINE,
                               raise_on_blank=False, preprocess=True).lower().replace("’", "'")
        except Exception:
            self.log.debug("chat OCR failed", exc_info=True)
            return ""

    @staticmethod
    def _says(text: str, phrases) -> bool:
        from difflib import SequenceMatcher
        t = text.replace("'", "")
        for p in phrases:
            p2 = p.replace("'", "")
            if p2 in t:
                return True
            n = len(p2)
            if any(SequenceMatcher(None, t[i:i + n], p2).ratio() >= 0.8 for i in range(0, max(1, len(t) - n + 1))):
                return True
        return False

    def _chat_event(self, before):
        """(event, chat image now): 'cant' / 'caught' / 'lighting' when the chat got a new
        message saying so, else None. `before` = the chat image last looked at."""
        import numpy as np
        sc = self.client.get_screenshot()
        now = self._chat_box(sc)
        if before is None or now.shape != before.shape or float(np.abs(now - before).mean()) < 0.4:
            return None, now
        text = self._chat_newest(sc)
        self.log.debug(f"Chat: {text!r}")
        if self._says(text, self.CANT_LIGHT):
            return "cant", now
        if self._says(text, self.FIRE_CAUGHT):
            return "caught", now
        if self._says(text, self.LIGHTING):
            return "lighting", now
        return None, now

    def _wait_lit(self, slot: MatchResult, chat_before=None) -> str:
        """After the log click. The game puts the log on the ground at once - its slot is
        empty long before the fire burns - and the character kneels until the fire catches,
        then steps off it (one tile). Clicking anything before that stops the lighting.
        Signals: the chat ("You can't light a fire here." / "You attempt to light the logs." /
        "The fire catches..."), the log leaving its slot, the minimap moving (the step).
        Returns 'lit', 'cant' (chat: no fire possible on this tile), 'blocked' (nothing
        happened - usually a missed click) or 'failed'."""
        from core.camera import GAME_VIEW
        # the mouse off the inventory (natural, and the cursor hid the log)
        x1, y1, x2, y2 = GAME_VIEW
        self.client.move_to((random.randint(x1, x2), random.randint(y1, y2)))
        t0 = time.time()
        started = False
        ref = None
        tabbed = False
        chat = chat_before
        while not self.terminate:
            elapsed = time.time() - t0
            limit = self.cfg.fire_timeout_max.value if started else self.cfg.fire_timeout.value
            if elapsed > limit:
                break
            time.sleep(random.uniform(0.25, 0.45))
            try:
                ev, chat = self._chat_event(chat)
            except Exception:
                ev = None
                self.log.debug("chat check failed", exc_info=True)
            if ev == "cant":
                self.log.info(f"Chat: can't light a fire here ({time.time() - t0:.1f}s after the click)")
                return "cant"
            if ev == "caught":
                self.log.debug(f"Fire caught after {time.time() - t0:.1f}s (chat)")
                return "lit"
            if not started:
                if ev == "lighting" or self._slot_empty(slot):
                    started = True
                    ref = self._minimap_gray()
                    self.log.debug(f"Lighting started ({time.time() - t0:.1f}s after the click)")
                continue
            px, diff = self._shift(ref, self._minimap_gray())
            if px >= self.cfg.fire_step_px.value or diff >= self.cfg.fire_step_diff.value:
                self.log.debug(f"Fire caught after {time.time() - t0:.1f}s (stepped off: minimap {px:.1f}px, diff {diff:.0f})")
                return "lit"
            if not tabbed and elapsed >= random.uniform(1.0, 2.0):
                tabbed = True
                if self.maybe_alt_tab(lambda: not self._stepped(ref), "fire lighting"):
                    chat = None  # the chat may have changed meanwhile: don't read old news
                    continue
        if not started:
            return "blocked"  # nothing happened: usually the click missed
        self.log.debug(f"No fire after {time.time() - t0:.0f}s")
        return "failed"

    def burn_logs(self) -> int:
        """Light every log in the inventory, one after another."""
        name = self.cfg.log_type.name
        burned = 0
        for _ in range(28):
            if self.terminate:
                break
            logs = self._inv(name)
            if not logs:
                break
            # the tinderbox stays in its slot: find it once per run
            if getattr(self, "_tinder", None) is None:
                found = self._inv(self.cfg.tinderbox.name)
                if not found:
                    self.log.error("No tinderbox in the inventory: can't light the logs")
                    return burned
                self._tinder = self.inv_slot(found[0])
                self.log.info(f"Tinderbox in inventory slot at {self._tinder.bounding_box[:2]}")
            tinder = [self._tinder]
            self.set_activity("firemaking")
            # each fire moves the character a tile: don't let the line of fires lead it away
            self.go_home(max_tiles=self.cfg.home_max_tiles.value, label="the trees")
            lit = False
            moves = 0
            careful = False
            for attempt in range(4 + int(self.cfg.fire_moves.value)):
                if self.terminate:
                    break
                log = random.choice(logs[:3])  # not always the first one
                try:
                    chat_before = self._chat_box()
                except Exception:
                    chat_before = None
                if not self._use_tinderbox_on(tinder[0], log, careful):
                    self.log.debug("Tinderbox/log mouse-over didn't match; trying again")
                    time.sleep(random.uniform(0.3, 0.7))
                    logs = self._inv(name) or logs
                    continue
                self.micro_idle()
                t_fire = time.time()
                res = self._wait_lit(self.inv_slot(log), chat_before)
                if res == "lit":
                    lit = True
                    self.log.debug(f"Lit after {time.time() - t_fire:.1f}s")
                    break
                if res == "failed":
                    logs = self._inv(name)
                    if not logs:
                        break  # the log lies on the ground unlit; nothing left to light
                    self.log.info("No fire: using the tinderbox again")
                    continue
                # blocked: nothing happened. Often a quick click just missed (the log got
                # selected instead): first try again right here, reading the mouse-over.
                if res == "blocked" and not careful:
                    careful = True
                    self.log.info("Lighting didn't start: trying again here (mouse-over checked)")
                    logs = self._inv(name) or logs
                    continue
                careful = False
                # a fire is already here / the tile doesn't allow one: one step aside
                if moves >= int(self.cfg.fire_moves.value):
                    break
                moves += 1
                self.log.info(f"Can't light a fire here: one step aside "
                              f"({moves}/{int(self.cfg.fire_moves.value)})")
                self.set_activity("walking")
                self.step_aside()
                self.set_activity("firemaking")
                logs = self._inv(name) or logs
            if not lit:
                self.log.warning("Gave up lighting this log")
                self._tinder = None  # check where the tinderbox is next time
                break
            burned += 1
            self.count("burned")
            self.log.info(f"Fire lit ({self.counts.get('burned', 0)} so far)")
            time.sleep(self.cfg.fire_step_wait.choose())  # the character steps off the fire
            self.control.propose_break()
        self._last_used = None
        self.set_activity("working")
        return burned

    def check_inventory_full(self):
        """Full = every inventory slot holds something (logs, gems, anything)."""
        try:
            sc = self.client.get_screenshot()
            if self.client.toolplane.get_active_tab(sc) != ToolplaneTab.INVENTORY.value:
                self.client.click_toolplane(ToolplaneTab.INVENTORY)
                time.sleep(0.3)
                sc = self.client.get_screenshot()
            used = len(inventory.used_slots(sc))
            if self._last_used is not None and used > self._last_used:
                self.count("logs", used - self._last_used)
            self._last_used = used
            self.log.info(f"Inventory: {used}/28 slots used")
            if self.cfg.drop_items.value:
                return used >= 28
            # banking mode keeps the old rule (count of logs)
            logs = self.client.get_inv_items([self.cfg.log_type.name], min_confidence=0.9, verify_tab=False)
            return len(logs) >= self.cfg.inv_full_at.value or used >= 28
        except ScriptTerminationException:
            raise
        except Exception as e:
            self.log.warning(f"Error checking inventory: {e}")
            return False

    def drop_logs(self):
        """Drop everything in the inventory except keep_items (the axe), with shift-click."""
        try:
            self.client.click_toolplane(ToolplaneTab.INVENTORY)
            time.sleep(0.4)
            sc = self.client.get_screenshot()
            slots = inventory.used_slots(sc)
            keep = []
            if self.cfg.keep_items.value:
                try:
                    keep = self.client.get_inv_items(list(self.cfg.keep_items.value), min_confidence=0.9)
                except Exception:
                    keep = []
            keep_pts = [k.get_center() for k in keep]
            to_drop = [r for r in slots if not any(r.contains(*p) for p in keep_pts)]
            if not to_drop:
                self.log.warning("Nothing to drop")
                return
            # drop row by row like a player, sometimes going right-to-left
            rows: dict[int, list] = {}
            for r in to_drop:
                rows.setdefault(r.start_y, []).append(r)
            order = []
            for i, y in enumerate(sorted(rows)):
                row = sorted(rows[y], key=lambda r: r.start_x)
                if i % 2 and random.random() < 0.5:
                    row.reverse()
                order += row
            self.log.info(f"Dropping {len(order)} items (keeping {len(keep)})")
            try:
                keyboard.press('shift')
                for rect in order:
                    self.click_inv(rect)
                    time.sleep(random.uniform(0.1, 0.3))
            finally:
                keyboard.release('shift')
            self.count("dropped", len(order))
            self._last_used = None
            self.log.info("Inventory dropped")
        except ScriptTerminationException:
            raise
        except Exception as e:
            raise RuntimeError(f"Failed to drop items: {e}")

    def bank_logs(self):
        """Bank all logs and prepare for the next woodcutting run"""
        self.log.info("Banking logs...")
        
        try:
            try:
                n_logs = len(self.client.get_inv_items([self.cfg.log_type.name], min_confidence=0.9))
            except Exception:
                n_logs = 0
            # Click on the bank tile
            self.client.smart_click_tile(
                self.cfg.bank_tile.value,
                ['bank', 'banker', 'booth', 'chest'],
                retry_hover=3,
                retry_match=2,
                filter_ui=True
            )
            
            # Wait for character to stop moving (bounded)
            deadline = time.time() + 20
            while time.time() < deadline and not self.terminate and self.client.is_moving():
                time.sleep(0.2)
            
            # Wait for bank interface to open
            timeout = 5
            start_time = time.time()
            while not self.bank.is_open:
                if self.terminate:
                    return False
                if time.time() - start_time > timeout:
                    self.log.warning("Timed out waiting for bank to open")
                    return False
                time.sleep(0.5)
            
            # Deposit all items
            self.bank.deposit_inv()
            time.sleep(random.uniform(0.5, 1.0))
            
            # Close bank
            self.bank.close()
            if n_logs:
                self.count("banked", n_logs)
            self._last_used = None
            return True
            
        except ScriptTerminationException:
            raise
        except Exception as e:
            self.log.error(f"Error banking logs: {e}")
            return False

# For direct execution
if __name__ == "__main__":
    config = BotConfig()
    # Override default values if needed
    # config.log_type.value = "Oak logs"
    
    bot = BotExecutor(config)
    bot.start()
