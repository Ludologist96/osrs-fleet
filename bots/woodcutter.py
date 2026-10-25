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
import math
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
    fire_step_wait: RangeParam = RangeParam(0.3, 0.8)    # after a fire: a short look before the next log
    fire_tile: StringParam = StringParam("")           # "x,y" where the fire lines start (empty = learnt from the first fires)
    fire_lane_tiles: IntParam = IntParam(12)           # a line of fires this long: back to the fire spot, one row over
    xp_drop_match: FloatParam = FloatParam(0.75)       # firemaking XP drop icon match (= the fire is lit)
    bank_tile: RGBParam = RGBParam(0, 255, 0)  # colour the launcher highlights the bankers in (bank mode)
    bank_max_tiles: IntParam = IntParam(80)    # use the nearest known F2P bank when it's this close to the trees
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
        if not self.cfg.drop_items.value:
            self._close_bank()  # left open (a restart in the middle of a bank trip)
        # the run starts at the trees: remember where (World Location tile; minimap fallback)
        try:
            self.remember_home()
            # a fixed tree spot (home_tile) and the bot started elsewhere: walk there first
            if str(self.cfg.home_tile.value or "").strip():
                self.go_home(max_tiles=self.cfg.home_max_tiles.value, label="the trees")
        except ScriptTerminationException:
            self.log.info("Terminated while walking to the trees")
            return
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
                        self._go_trees(max_tiles=2)
                        if self.check_inventory_full():  # some logs couldn't be lit: drop them
                            self.set_activity("dropping")
                            self.drop_logs()
                    elif self.cfg.drop_items.value:
                        self.log.info("Inventory is full. Dropping logs...")
                        self.set_activity("dropping")
                        self.drop_logs()
                        self._go_trees(max_tiles=self.cfg.home_max_tiles.value)
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
                        self._note_tree_spot()
                        self.chopped_once = True
                        self.tree_waits = 0
                    except ScriptTerminationException:
                        raise
                    except Exception as e:
                        if self.terminate:
                            break
                        if not self.cfg.drop_items.value:
                            self._close_bank()
                        if True:  # drop and bank mode alike (bank mode used to walk the old route here)
                            # Marked trees are stumps (their marker disappears): wait for respawn.
                            self.tree_waits += 1
                            self.set_activity("waiting for trees")
                            if self.tree_waits > self.cfg.max_tree_waits.value:
                                self.log.error(f"No marked tree for {self.tree_waits} tries in a row. Stopping.")
                                return
                            # firemaking drifts away from the trees (one tile per fire): go back
                            if self.tree_waits >= 1 and self._go_trees(max_tiles=3):
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
    # ------------------------------------------------------------------ the tree spot
    def _note_tree_spot(self) -> None:
        """Where it stands when it clicks a tree = the tree spot (where it walks back to
        after the bank, or when no tree is in view). Learnt from chopping, so a run
        started somewhere else (e.g. in the bank) still finds its way to the trees."""
        t = self.my_tile()
        if t:
            if not getattr(self, "_tree_spot", None):
                self.log.info(f"Tree spot: {t[0]}, {t[1]}")
            self._tree_spot = t

    def _go_trees(self, max_tiles: float, near: float = 0.0) -> bool:
        spot = getattr(self, "_tree_spot", None)
        if not spot:
            return self.go_home(max_tiles=max_tiles, label="the trees")
        cur = self.my_tile()
        if not cur:
            return False
        dist = math.hypot(spot[0] - cur[0], spot[1] - cur[1])
        if dist <= max(1.0, max_tiles):
            return False
        self.log.info(f"Back to the trees: {dist:.0f} tiles away")
        prev = self.activity
        self.set_activity("walking")
        try:
            self.walk_to_tile(spot, tol=1.5, label="the trees", near=near)
        finally:
            self.set_activity(prev if prev not in (None, "walking") else "working")
        return True

    # F2P banks: a tile inside, near the bankers (the walk only needs to get the bankers on
    # screen; the bank click walks the rest). Nearest one to the trees is used.
    KNOWN_BANKS = {
        "Draynor": (3092, 3243), "Varrock West": (3185, 3438), "Varrock East": (3253, 3421),
        "Falador East": (3013, 3356), "Falador West": (2946, 3369), "Edgeville": (3094, 3491),
        "Al Kharid": (3269, 3167),
    }

    def _bank_target(self):
        """(name, tile) of the bank to use: the known F2P bank nearest to the trees, else
        the bank end of the saved route."""
        home = getattr(self, "_home_tile", None) or self.my_tile()
        if home:
            name, t = min(self.KNOWN_BANKS.items(),
                          key=lambda kv: math.hypot(kv[1][0] - home[0], kv[1][1] - home[1]))
            if math.hypot(t[0] - home[0], t[1] - home[1]) <= self.cfg.bank_max_tiles.value:
                return name, (t[0], t[1], 0)
        route = list(self.cfg.bank_to_trees.value or [])
        if route:
            wp = route[0].value if hasattr(route[0], "value") else route[0]
            x, y = (wp["x"], wp["y"]) if isinstance(wp, dict) else (wp.x, wp.y)
            return "route", (x, y, 0)
        return None, None

    def bank_trip(self) -> bool:
        """Walk to the nearest bank (world tiles, `walk_to_tile`), open it on a banker
        (NPC Indicators highlight "Banker" in the bank_tile colour; the launcher sets that),
        deposit everything but the keep items, walk back to the start spot. Tried twice."""
        name, bank = self._bank_target()
        if not bank:
            self.log.error("No bank known near the trees")
            return False
        for attempt in (1, 2):
            if self.terminate:
                return True
            try:
                self.set_activity("walking to bank")
                self.log.info(f"To the {name} bank ({bank[0]}, {bank[1]})")
                self.walk_to_tile(bank, tol=3.0, label=f"the {name} bank", near=3)
                self.set_activity("banking")
                if not self.bank_logs():
                    raise RuntimeError("couldn't bank the logs")
                self.set_activity("walking to trees")
                self._go_trees(max_tiles=2, near=4)
                return True
            except ScriptTerminationException:
                raise
            except Exception as e:
                self.log.error(f"Bank trip failed (attempt {attempt}/2): {e}", exc_info=True)
                time.sleep(random.uniform(1.5, 3.0))
        self._go_trees(max_tiles=2)
        return False

    # ------------------------------------------------------------------ the bank itself
    def _banker_blobs(self, sc):
        """Boxes of the highlighted bankers (NPC Indicators hull in the bank_tile colour)
        in the game view, nearest to the character first."""
        import cv2
        import numpy as np
        from core.camera import GAME_VIEW
        x1, y1, x2, y2 = 4, 4, 512, 334  # the game view (window coords)
        a = np.asarray(sc.convert("RGB").crop((x1, y1, x2, y2))).astype(int)
        r, g, b = self.cfg.bank_tile.value
        m = ((abs(a[:, :, 0] - r) <= 30) & (abs(a[:, :, 1] - g) <= 30) & (abs(a[:, :, 2] - b) <= 30)).astype(np.uint8)
        # the top-left overlays (tile panel...) never hold a banker
        m[:150, :160] = 0
        n, lab, st, cen = cv2.connectedComponentsWithStats(cv2.dilate(m, np.ones((5, 5), np.uint8)))
        px, py = self.PLAYER_PT
        boxes = []
        for k in range(1, n):
            x, y, w, h, area = st[k]
            if area < 60 or w < 10 or h < 15:
                continue
            boxes.append((math.hypot(x1 + x + w / 2 - px, y1 + y + h / 2 - py),
                          MatchResult(x1 + x + w // 4, y1 + y + h // 4, x1 + x + 3 * w // 4, y1 + y + 3 * h // 4)))
        return [b for _, b in sorted(boxes, key=lambda t: t[0])]

    def _menu_click(self, words) -> bool:
        """Read the open right-click menu line by line; click the first line naming one of
        `words`. Leaves the menu (closing it) when nothing matches."""
        from core import ocr
        from core.input.mouse_control import click
        menu = None
        for _ in range(3):  # the menu can take a frame or two to show
            sc = self.client.get_screenshot()
            try:
                menu = self.client.get_right_click_menu(sc)
                break
            except Exception as e:
                self.log.debug(f"No right-click menu yet: {e}")
                time.sleep(random.uniform(0.15, 0.25))
        if menu is None:
            return False
        header, line = 19, 15
        n = max(1, round((menu.height - header) / line))
        seen = []
        for i in range(n):
            y = menu.start_y + header + i * line
            row = MatchResult(menu.start_x + 3, y, menu.end_x - 3, y + line)
            img = tools.mask_above_color_value(row.crop_in(sc), 150)
            try:
                text = ocr.execute(img, font=ocr.FontChoice.RUNESCAPE_BOLD_12,
                                   psm=ocr.TessPsm.SINGLE_LINE, raise_on_blank=False).strip().lower()
            except Exception:
                text = ""
            seen.append(text)
            if any(w in text for w in words) and "talk" not in text:
                target = MatchResult(row.start_x + 4, y + 3, min(row.end_x - 4, row.start_x + 60), y + line - 3)
                self.client.move_to(target.get_point_within(), rand_move_chance=0)
                click(-1, -1)
                self.log.debug(f"Menu {seen}: clicked '{text}'")
                return True
        self.log.info(f"Menu {seen}: no bank option")
        # move clearly off the menu: it closes
        self.client.move_to((max(10, menu.start_x - random.randint(40, 80)), menu.start_y + random.randint(0, 40)))
        return False

    def _open_bank(self) -> bool:
        from core.input.mouse_control import ClickType
        for i in range(4):
            if self.terminate:
                return False
            if self.bank.is_open:
                return True
            boxes = self._banker_blobs(self.client.get_screenshot())
            if not boxes:
                if i < 2:  # still walking in / a player in front: look again first
                    time.sleep(random.uniform(0.5, 0.8))
                    continue
                self.log.info(f"No highlighted banker on screen ({i + 1}/4): looking around")
                self.camera.search(self.cfg.camera_search_time.value, i - 1)
                continue
            target = boxes[min(len(boxes) - 1, random.choice((0, 0, 0, 1)))]
            self.client.click(target, click_type=ClickType.RIGHT)
            time.sleep(random.uniform(0.15, 0.3))
            if not self._menu_click(["bank"]):
                continue
            end = time.time() + 10  # it walks to the banker first
            while time.time() < end and not self.terminate:
                time.sleep(0.4)
                if self.bank.is_open:
                    self.log.info("Bank open")
                    return True
            self.log.info("The bank didn't open")
        return False

    def _deposit_all_but_keep(self) -> int:
        """Click every inventory item that isn't a keep item (axe, tinderbox) with the
        bank's quantity on "All": one click deposits all of that kind. Returns the clicks."""
        try:
            self.bank.set_quantity_setting("All")
            time.sleep(random.uniform(0.3, 0.6))
        except Exception:
            self.log.debug("couldn't set the bank quantity to All", exc_info=True)
        clicks = 0
        menu_mode = False  # the quantity button isn't on All: right-click -> Deposit-All
        last_used = None
        for _ in range(30):
            if self.terminate:
                break
            sc = self.client.get_screenshot()
            used = inventory.used_slots(sc)
            if last_used is not None and not menu_mode and last_used - len(used) <= 1 and len(used) > 4:
                self.log.info("One item per click: using right-click Deposit-All")
                menu_mode = True
            last_used = len(used)
            keep = []
            try:
                keep = self.client.get_inv_items(list(self.cfg.keep_items.value), min_confidence=0.9,
                                                 verify_tab=False)
            except Exception:
                pass
            keep_slots = {self.inv_slot(k).bounding_box[:2] for k in keep}
            rest = [u for u in used if self.inv_slot(u).bounding_box[:2] not in keep_slots]
            if not rest:
                break
            pick = random.choice(rest[:4])
            if menu_mode:
                from core.input.mouse_control import ClickType
                self.client.click(self.inv_point(pick), click_type=ClickType.RIGHT)
                time.sleep(random.uniform(0.2, 0.35))
                if not self._menu_click(["deposit-all", "deposit-al", "-all"]):
                    menu_mode = False  # fall back to plain clicks
            else:
                self.click_inv(pick)
            clicks += 1
            time.sleep(random.uniform(0.5, 0.9))  # the game moves items on its tick
        return clicks

    def bank_logs(self):
        """Open the bank on a banker, deposit all but the keep items, leave it open (the
        walk back closes it)."""
        self.log.info("Banking logs...")
        try:
            n_logs = len(self.client.get_inv_items([self.cfg.log_type.name], min_confidence=0.9))
        except Exception:
            n_logs = 0
        if not self._open_bank():
            self.log.warning("Couldn't open the bank")
            return False
        self._deposit_all_but_keep()
        left = 0
        try:
            left = len(self.client.get_inv_items([self.cfg.log_type.name], min_confidence=0.9, verify_tab=False))
        except Exception:
            pass
        if n_logs:
            self.count("banked", max(0, n_logs - left))
        self.log.info(f"Banked {max(0, n_logs - left)} logs")
        self._last_used = None
        self._close_bank()
        return left == 0

    def _close_bank(self) -> None:
        """Close the bank window if it is open (it covers the tile panel and the trees:
        a bot left with an open bank - e.g. restarted mid-trip - saw nothing at all).
        The X button; else Escape; else a short minimap click (any walk closes it)."""
        bank = getattr(self, "bank", None)
        if bank is None:
            return
        for step in ("x", "esc", "walk"):
            try:
                if not bank.is_open:
                    return
                if step == "x":
                    from core.bank import BANK_CLOSE
                    btn = self.client.find_in_window(BANK_CLOSE, min_scale=1, max_scale=1)
                    if btn.confidence > 0.85:
                        self.client.click(btn)
                elif step == "esc":
                    keyboard.press_and_release("esc")
                else:
                    self.minimap_step(1, label="Closing the bank")
                time.sleep(random.uniform(0.6, 1.0))
            except Exception:
                self.log.debug(f"bank close ({step}) failed", exc_info=True)
        if bank.is_open:
            self.log.warning("The bank window stays open")

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

    def _wait_selected(self, slot: MatchResult, want: bool, timeout: float) -> bool:
        """Poll until the slot's white "selected" outline is there (want=True) or gone."""
        end = time.time() + timeout
        while True:
            if self._selected(slot) == want:
                return True
            if time.time() >= end:
                return False
            time.sleep(random.uniform(0.06, 0.1))

    def _light(self, tinder: MatchResult, log: MatchResult) -> str:
        """Tinderbox, then the log - every step checked on the screen, no mouse-over OCR
        (it read "Use Tinderbox -> Oak logs" as 'hl', '_', '' and kept the bot stuck).
          tinderbox click -> its white outline must show (else click it again, 3 tries)
          log click       -> the log leaves its slot = the game put it on the ground
        Returns 'started', 'cant' (chat: no fire on this tile) or 'missed'."""
        sc = self.client.get_screenshot()
        log_slot = self.inv_slot(log)
        if not self._selected(tinder, sc):
            sel_log = next((m for m in self._inv(self.cfg.log_type.name)
                            if self._selected(self.inv_slot(m), sc)), None)
            if sel_log is not None:
                # a log is selected: clicking the tinderbox uses it on the log = lights it
                self.log.debug("A log was selected: using it on the tinderbox")
                log_slot = self.inv_slot(sel_log)
                self.click_inv(tinder)
                self._mouse_off_inventory()
                return "started" if self._wait_gone(log_slot, 1.2) else "missed"
            for i in range(3):
                self.click_inv(tinder)
                if self._wait_selected(tinder, True, 0.6):
                    break
                self.log.info(f"The tinderbox didn't get selected: clicking it again ({i + 1}/3)")
            else:
                self._tinder = None  # maybe it isn't where we think: look again
                return "missed"
        time.sleep(self.cfg.fire_click_gap.choose())
        try:
            chat_before = self._chat_box()
        except Exception:
            chat_before = None
        for i in range(2):
            self.click_inv(log_slot)
            # the cursor on the slot looks like an item: move it off before looking
            self._mouse_off_inventory()
            # the game answers on its next tick (0.6 s) - through the proxy sometimes later:
            # clicking again too soon selects the log instead (seen: deselected after 0.9 s)
            if self._wait_gone(log_slot, 1.8, while_selected=tinder):
                return "started"
            if self._selected(tinder):
                self.log.info("The log click didn't land (tinderbox still selected): clicking it again")
                continue
            break
        # the tinderbox let go but the log is still here: the tile doesn't allow a fire
        # (the chat says so), or the click went elsewhere
        if self._wait_gone(log_slot, 0.6):
            return "started"
        try:
            ev, _ = self._chat_event(chat_before)
        except Exception:
            ev = None
        if ev == "cant":
            self.log.info("Chat: can't light a fire here")
            return "cant"
        if self._selected(tinder):
            self.click_inv(tinder)  # put it down for a clean next try
        return "missed"

    def _mouse_off_inventory(self) -> None:
        """Mouse into the game view (where it rests while the fire is lit)."""
        from core.camera import GAME_VIEW
        x1, y1, x2, y2 = GAME_VIEW
        self.client.move_to((random.randint(x1 + 20, x2 - 20), random.randint(y1 + 20, y2 - 20)))

    def _wait_gone(self, slot: MatchResult, timeout: float, while_selected: MatchResult | None = None) -> bool:
        """Poll until the slot is empty. With `while_selected`, give up early once that
        item is no longer selected (the click was used up without lighting)."""
        end = time.time() + timeout
        unselected_at = None
        while time.time() < end:
            time.sleep(random.uniform(0.08, 0.13))
            if self._slot_empty(slot):
                return True
            if while_selected is not None and not self._selected(while_selected):
                unselected_at = unselected_at or time.time()
                if time.time() - unselected_at > 0.4:
                    return False
        return False

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

    # ------------------------------------------------------------ "the fire is lit" signals
    def _xp_drops(self, sc=None) -> list[int]:
        """y of every firemaking XP drop (flame icon) rising on the right of the game view.
        A drop shows ~2 s and moves up ~65 px/s; the XP bar's icon at the top is skipped."""
        import cv2
        import numpy as np
        if getattr(self, "_xp_tpl", None) is None:
            self._xp_tpl = cv2.cvtColor(np.asarray(Image.open("data/ui/xp-drop-firemaking.png").convert("RGB")),
                                        cv2.COLOR_RGB2GRAY).astype(np.float32)
        sc = sc or self.client.get_screenshot()
        x1, y1, x2, y2 = self.XP_DROP_AREA
        a = cv2.cvtColor(np.asarray(sc.convert("RGB").crop((x1, y1, x2, y2))), cv2.COLOR_RGB2GRAY).astype(np.float32)
        r = cv2.matchTemplate(a, self._xp_tpl, cv2.TM_CCOEFF_NORMED)
        ys = []
        thr = float(self.cfg.xp_drop_match.value)
        while True:
            _, mx, _, (lx, ly) = cv2.minMaxLoc(r)
            if mx < thr or len(ys) >= 4:
                break
            ys.append(y1 + ly)
            r[max(0, ly - 12):ly + 12, :] = -1  # next drop (they're ~25 px apart at least)
        return ys

    XP_DROP_AREA = (420, 35, 545, 330)  # window coords: right part of the game view, under the XP bar

    def _new_drop(self, before: list[int], sc=None) -> bool:
        """A drop that wasn't there before: lower on the screen than every old one (new
        drops start at the bottom and rise)."""
        now = self._xp_drops(sc)
        if not now:
            return False
        if not before:
            return True
        return max(now) > max(before) + 10

    def _wait_fire(self, drops_before: list[int]) -> str:
        """The log is on the ground and the character kneels. Clicking anything now stops
        it. Lit = a firemaking XP drop appears, or the character steps off the fire (its
        tile changes / the minimap moves). Returns 'lit' or 'failed'."""
        t0 = time.time()
        tile0 = self.my_tile()
        ref = self._minimap_gray()
        tabbed = False
        while not self.terminate and time.time() - t0 < self.cfg.fire_timeout_max.value:
            time.sleep(random.uniform(0.2, 0.35))
            sc = self.client.get_screenshot()
            if self._new_drop(drops_before, sc):
                self.log.debug(f"Fire lit after {time.time() - t0:.1f}s (XP drop)")
                return "lit"
            t = self.my_tile(sc)
            if tile0 and t and t[:2] != tile0[:2] and time.time() - t0 < 1.2:
                tile0 = t  # too soon for a fire: it was still walking - watch from here
            elif tile0 and t and t[:2] != tile0[:2]:
                self.log.debug(f"Fire lit after {time.time() - t0:.1f}s (stepped {tile0[:2]} -> {t[:2]})")
                return "lit"
            if not tile0:
                px, diff = self._shift(ref, self._minimap_gray())
                if px >= self.cfg.fire_step_px.value or diff >= self.cfg.fire_step_diff.value:
                    self.log.debug(f"Fire lit after {time.time() - t0:.1f}s (minimap {px:.1f}px)")
                    return "lit"
            if not tabbed and time.time() - t0 >= random.uniform(1.0, 2.0):
                tabbed = True
                if self.maybe_alt_tab(lambda: not self._stepped(ref), "fire lighting"):
                    drops_before = []  # an XP drop seen now may be ours; the tile check decides
                    t = self.my_tile()
                    if tile0 and t and t[:2] != tile0[:2]:
                        return "lit"
        self.log.debug(f"No fire after {time.time() - t0:.0f}s")
        return "failed"

    # ------------------------------------------------------------ where the fires go
    def _parse_tile(self, text) -> tuple[int, int] | None:
        txt = str(text or "").replace(" ", "")
        if not txt:
            return None
        try:
            x, y = (int(v) for v in txt.split(",")[:2])
            return x, y
        except ValueError:
            self.log.warning(f"Tile setting '{txt}' is not 'x,y': ignored")
            return None

    FIRE_ROWS = (0, 1, -1, 2, -2, 3, -3)

    def _fire_lane_start(self):
        """Where the next line of fires starts: the fire spot, on the current row."""
        fx, fy = self._fire_spot
        dy = self.FIRE_ROWS[self._fire_row % len(self.FIRE_ROWS)]
        return fx, fy + dy, 0

    def _next_row(self) -> bool:
        """Move on to the next row that hasn't failed twice. False (and the fire spot is
        dropped, to look for a new one) when every row keeps failing."""
        fails = getattr(self, "_row_fails", {})
        for _ in range(len(self.FIRE_ROWS)):
            self._fire_row += 1
            dy = self.FIRE_ROWS[self._fire_row % len(self.FIRE_ROWS)]
            if fails.get(dy, 0) < 2:
                return True
        self.log.warning(f"Every row at the fire spot {self._fire_spot} is blocked: looking for a new spot")
        self._bad_spots = getattr(self, "_bad_spots", set()) | {self._fire_spot}
        self._fire_spot = None
        self._scout = None
        self._row_fails = {}
        return False

    def _to_fire_spot(self, why: str) -> None:
        if not getattr(self, "_fire_spot", None):
            return
        target = self._fire_lane_start()
        cur = self.my_tile()
        if cur and abs(cur[0] - target[0]) <= 1 and abs(cur[1] - target[1]) <= 1:
            return
        self.log.info(f"To the fire spot ({why}): {target[0]}, {target[1]}")
        prev = self.activity
        self.set_activity("walking")
        try:
            # near enough is fine: the line starts wherever it stands (a 1-tile minimap
            # click often lands next to the target - that once took 35 s of tiny clicks)
            self.walk_to_tile(target, tol=1.2, label="the fire spot", max_clicks=5)
        finally:
            self.set_activity(prev or "firemaking")

    def _settle(self, timeout: float = 4.0) -> None:
        """Wait until the character stands still (a walk or step finished): a tile change
        while it still walks would look like "the fire is lit"."""
        t = self.my_tile()
        if t:
            self._wait_stopped(t, timeout)

    def _scout_next(self) -> bool:
        """No fire spot yet and the fire can't be lit here: walk to the next spot on open
        ground around the trees (rings 4-9 tiles out, random order). False when every
        candidate was tried."""
        home = getattr(self, "_home_tile", None) or self.my_tile()
        if not home:
            return False
        if getattr(self, "_scout", None) is None:
            # fires push the character west, so a spot needs open ground to its west
            spots = []
            for r in (6, 4, 8):
                ring = [(home[0] + dx * r, home[1] + dy * r)
                        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1))]
                random.shuffle(ring)
                spots += ring
            bad = getattr(self, "_bad_spots", set())
            self._scout = [p for p in spots
                           if all(abs(p[0] - b[0]) + abs(p[1] - b[1]) > 2 for b in bad)]
        while self._scout:
            tx, ty = self._scout.pop(0)
            self.log.info(f"Looking for a fire spot: trying {tx}, {ty}")
            if self.walk_to_tile((tx, ty, 0), tol=1.0, label="a possible fire spot", max_clicks=4):
                return True
        self.log.warning("No fire spot found around the trees")
        return False

    def burn_logs(self) -> int:
        """Light every log in the inventory, one after another, in lines starting at the
        fire spot (a `fire_tile` setting, or the tile where the first fires of the run lit
        fine). Each fire moves the character one tile; after `fire_lane_tiles` it walks
        back to the fire spot one row over."""
        name = self.cfg.log_type.name
        burned = 0
        if not hasattr(self, "_fire_spot"):
            self._fire_spot = self._parse_tile(self.cfg.fire_tile.value)
            self._fire_row = 0
            self._row_fails = {}
            # how many fires fit in a line before something blocks it (learnt)
            self._lane_len = int(self.cfg.fire_lane_tiles.value)
            if self._fire_spot:
                self.log.info(f"Fire spot from the settings: {self._fire_spot}")
        self.set_activity("firemaking")
        self._to_fire_spot("inventory full")
        self._settle()
        lane_start = self.my_tile()
        row_fires = 0      # fires lit on this line so far
        clean_streak = 0   # fires lit in a row without a step aside (to learn a fire spot)
        streak_start = None
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
            self.set_activity("firemaking")
            # a long line: back to the fire spot, next row
            if self._fire_spot and row_fires >= self._lane_len:
                self._next_row()
                self._to_fire_spot(f"line of {row_fires} fires done")
                self._settle()
                lane_start = self.my_tile()
                row_fires = 0
            lit = False
            moves = 0
            misses = 0
            here = self.my_tile()  # the tile this log is lit from (before any step aside)
            while not self.terminate:
                log = random.choice(logs[:3])  # not always the first one
                drops = self._xp_drops()
                res = self._light(self._tinder, log)
                if res == "started":
                    self.micro_idle()
                    t_fire = time.time()
                    if self._wait_fire(drops) == "lit":
                        lit = True
                        self.log.debug(f"Lit after {time.time() - t_fire:.1f}s")
                        break
                    logs = self._inv(name)
                    if not logs:
                        break  # the log lies on the ground unlit; nothing left to light
                    self.log.info("No fire: using the tinderbox again")
                    continue
                if res == "missed":
                    misses += 1
                    if misses <= 3:
                        time.sleep(random.uniform(0.3, 0.7))
                        logs = self._inv(name) or logs
                        continue
                    misses = 0  # missed 3 times here: maybe the tile is the problem
                # 'cant' (or many misses): a fire / object is on this tile
                clean_streak = 0
                self.set_activity("walking")
                if not self._fire_spot:
                    # no fire spot yet: try open ground around the trees, spot by spot
                    if not self._scout_next():
                        break
                    moves = 0
                elif moves < 6:
                    # the line is blocked (trees, old fires): next row, not a random step
                    # onto the fires just lit
                    moves += 1
                    dy = self.FIRE_ROWS[self._fire_row % len(self.FIRE_ROWS)]
                    if row_fires == 0:
                        self._row_fails[dy] = self._row_fails.get(dy, 0) + 1
                    else:
                        # next lines stop before the block: the usual line length seen
                        # (median of the last few, at least 4 - one short line is no rule)
                        self._lane_seen = (getattr(self, "_lane_seen", []) + [row_fires])[-5:]
                        srt = sorted(self._lane_seen)
                        self._lane_len = max(4, min(int(self.cfg.fire_lane_tiles.value), srt[len(srt) // 2]))
                    self.log.info(f"Can't light a fire here (line of {row_fires}): next row")
                    if self._next_row():
                        self._to_fire_spot("line blocked")
                    elif not self._scout_next():
                        self.set_activity("firemaking")
                        break
                    lane_start = self.my_tile()
                    row_fires = 0
                else:
                    self.set_activity("firemaking")
                    break
                self._settle()
                self.set_activity("firemaking")
                here = self.my_tile()
                logs = self._inv(name) or logs
            if not lit:
                self.log.warning("Gave up lighting this log")
                self._tinder = None  # check where the tinderbox is next time
                break
            burned += 1
            row_fires += 1
            clean_streak = clean_streak + 1 if moves == 0 else 1
            if clean_streak == 1:
                streak_start = here
            self.count("burned")
            self.log.info(f"Fire lit ({self.counts.get('burned', 0)} so far)")
            if not self._fire_spot and clean_streak >= 5 and streak_start:
                # five fires in a line lit fine from there: that's the fire spot
                self._fire_spot = (streak_start[0], streak_start[1])
                self._fire_row = 0
                self._row_fails = {}
                self._lane_len = int(self.cfg.fire_lane_tiles.value)
                lane_start, row_fires = streak_start, clean_streak
                self.log.info(f"Fire spot learnt: {self._fire_spot} (5 fires in a line lit from there)")
            # the character steps off the fire now; a log click during that step is often
            # ignored by the game (tinderbox stays selected): let it finish first
            self._settle(3.0)
            time.sleep(self.cfg.fire_step_wait.choose())
            self.control.propose_break()
        self._fire_row += 1  # next inventory: the next row (old fires may still burn)
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

# For direct execution
if __name__ == "__main__":
    config = BotConfig()
    # Override default values if needed
    # config.log_type.value = "Oak logs"
    
    bot = BotExecutor(config)
    bot.start()
