from bots.core import BotConfigMixin
from bots.core.cfg_types import StringListParam, BooleanParam, StringParam, IntParam, FloatParam, RGBParam, RangeParam, BreakCfgParam, RGBListParam, RouteParam, WaypointParam, ItemParam
from core.bot import Bot
from core.bank import BankInterface

from core import tools, inventory
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
    chop_click_delay: RangeParam = RangeParam(0.2, 0.5)
    inventory_check_delay: RangeParam = RangeParam(1.5, 3.0)
    # Wait until the player stops walking after clicking a tree. Needs RuneLite's
    # player position overlay; without it every click wastes ~5 s retrying.
    wait_while_walking: BooleanParam = BooleanParam(False)
    
    break_cfg: BreakCfgParam = BreakCfgParam(
        RangeParam(10, 30),  # break duration range in seconds
        FloatParam(0.01)     # break chance
    )

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
    ])
    # After clicking a tree, wait up to this long (seconds) for chopping to start,
    # e.g. while the character walks there, before clicking anything else.
    chop_start_timeout: FloatParam = FloatParam(10.0)
    drop_items: BooleanParam = BooleanParam(False)  # True = drop logs, False = bank logs
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
    
    
class BotExecutor(Bot):
    name: str = "Woodcutter Bot"
    description: str = "A bot that chops trees and banks or drops logs when inventory is full"
    tier: str = "B"
    instructions: str = """
    This bot will chop trees of the specified type and either drop or bank the logs when the inventory is full.
    Banking function will drop reliability since the movement orchestrator is not perfect.
    Dropping should be more reliable but not profitable.
    """
    
    
    def __init__(self, config: BotConfig, user=''):
        super().__init__(user, break_cfg=config.break_cfg)
        self.cfg: BotConfig = config
        self.log = get_logger('WoodcutterBot')
        self.consecutive_failures = 0
        self.tree_index = 0  # Used to cycle through tree tiles
        self.tree_waits = 0  # drop mode: waits in a row with no marked tree
        
        if not self.cfg.drop_items.value and not self.cfg.bank_to_trees.value:
            self.log.warning("Banking enabled but no route specified. Please set bank_to_trees in the config.")
            
        if not self.cfg.drop_items.value:
            self.bank = BankInterface(self.client, self.client.item_db)
        
    def start(self):
        self.log.info(f"Starting Woodcutter Bot for {self.cfg.log_type.name}")
        
        while not self.terminate:
            try:
                # Check if inventory is full
                if self.check_inventory_full():
                    if self.cfg.drop_items.value:
                        self.log.info("Inventory is full. Dropping logs...")
                        self.drop_logs()
                    else:
                        self.log.info("Inventory is full. Banking logs...")
                        # Travel to bank
                        self.log.info("Traveling to bank...")
                        try:
                            self.mover.execute_route(self.cfg.bank_to_trees.reverse())
                        except Exception as e:
                            self.log.error(f"Failed to travel to bank: {e}")
                            # retry once
                            self.mover.execute_route(self.cfg.bank_to_trees.reverse())
                            
                        # Bank items
                        if not self.bank_logs():
                            self.log.error("Failed to bank logs. Retrying...")
                            continue
                            
                        # Return to trees
                        self.log.info("Returning to trees...")
                        try:
                            self.mover.execute_route(self.cfg.bank_to_trees)
                        except Exception as e:
                            self.log.error(f"Failed to return to trees: {e}")
                            # retry once
                            self.mover.execute_route(self.cfg.bank_to_trees)
                
                # Check if we're woodcutting, if not, click on tree
                if not self.client.is_woodcutting:
                    try:
                        self.log.info("Not woodcutting. Clicking tree...")
                        self.chop_tree()
                        self.tree_waits = 0
                    except Exception as e:
                        if self.terminate:
                            break
                        if self.cfg.drop_items.value:
                            # Marked trees are stumps (their marker disappears): wait for respawn.
                            self.tree_waits += 1
                            if self.tree_waits > self.cfg.max_tree_waits.value:
                                self.log.error(f"No marked tree for {self.tree_waits} tries in a row. Stopping.")
                                return
                            wait = self.cfg.tree_respawn_wait.choose()
                            self.log.info(f"No marked tree available ({e}); waiting {wait:.1f}s "
                                          f"({self.tree_waits}/{self.cfg.max_tree_waits.value})")
                            time.sleep(wait)
                            self.control.propose_break()
                            continue
                        self.log.warning(f"Did we die or something? walking to trees: {e}")
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
                self.consecutive_failures += 1
                self.log.error(f"Error in woodcutting process: {e}")
                
                if self.consecutive_failures > self.cfg.max_retries.value:
                    self.log.critical(f"Failed {self.consecutive_failures} times in a row. Exiting.")
                    return
                else:
                    self.log.warning(f"Retry attempt {self.consecutive_failures}/{self.cfg.max_retries.value}")
                    time.sleep(3)  # Wait a bit before retrying
    
    def chop_tree(self):
        """Click a marked tree. Tries every tree colour once, starting with the next one
        in the cycle, so a stump (its marker is gone) costs no extra waiting."""
        tree_tiles = self.cfg.tree_tiles.value

        if not tree_tiles:
            self.log.error("No tree tile colors specified")
            return False

        errors = []
        clicked = False
        for i in range(len(tree_tiles)):
            current_tree = tree_tiles[(self.tree_index + i) % len(tree_tiles)]
            try:
                clicked = self._click_tree_of_color(current_tree)
            except ScriptTerminationException:
                raise
            except Exception as e:
                errors.append(f"{current_tree.to_hex()}: {e}")
                continue
            if clicked:
                self.tree_index += i + 1
                time.sleep(self.cfg.chop_click_delay.choose())
                self._wait_for_chop_start()
                break
            errors.append(f"{current_tree.to_hex()}: no tree showing '{self.cfg.tree_hover.value}'")
        if not clicked:
            raise RuntimeError("no marked tree found (" + "; ".join(errors) + ")")

        if not self.cfg.wait_while_walking.value:
            return

        # Wait until character stops moving
        start_time = time.time()
        timeout = 15  # Timeout after 15 seconds
        
        while time.time() - start_time < timeout:
            if not self.client.is_moving():
                break
            time.sleep(0.2)
    
    def _wait_for_chop_start(self) -> None:
        """Don't click another tree while the character is still walking to this one:
        wait until the Woodcutting overlay says we're chopping (or a timeout)."""
        deadline = time.time() + float(self.cfg.chop_start_timeout.value)
        while time.time() < deadline and not self.terminate:
            if self.client.is_woodcutting:
                return
            time.sleep(random.uniform(0.4, 0.8))
        self.log.debug("Chopping didn't start before the timeout")

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
            try:
                self.client.smart_click_match(match, [self.cfg.tree_hover.value],
                                              retry_hover=3, center_point=True)
                return True
            except RuntimeError as e:
                self.log.debug(f"Skipping marked tree ({e})")
                x1, y1, x2, y2 = match.bounding_box
                skip.append(MatchResult(x1 - 4, y1 - 4, x2 + 4, y2 + 4))
        return False

    def check_inventory_full(self):
        """Full = every inventory slot holds something (logs, gems, anything)."""
        try:
            self.client.click_toolplane(ToolplaneTab.INVENTORY)
            time.sleep(0.3)
            sc = self.client.get_screenshot()
            used = len(inventory.used_slots(sc))
            self.log.info(f"Inventory: {used}/28 slots used")
            if self.cfg.drop_items.value:
                return used >= 28
            # banking mode keeps the old rule (count of logs)
            logs = self.client.get_inv_items([self.cfg.log_type.name], min_confidence=0.9)
            return len(logs) >= self.cfg.inv_full_at.value or used >= 28
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
                    self.client.click(rect.scale_px(-6), rand_move_chance=0, after_click_settle_chance=0)
                    time.sleep(random.uniform(0.1, 0.3))
            finally:
                keyboard.release('shift')
            self.log.info("Inventory dropped")
        except Exception as e:
            raise RuntimeError(f"Failed to drop items: {e}")

    def bank_logs(self):
        """Bank all logs and prepare for the next woodcutting run"""
        self.log.info("Banking logs...")
        
        try:
            # Click on the bank tile
            self.client.smart_click_tile(
                self.cfg.bank_tile.value,
                ['bank', 'banker', 'booth', 'chest'],
                retry_hover=3,
                retry_match=2,
                filter_ui=True
            )
            
            # Wait for character to stop moving
            while self.client.is_moving():
                time.sleep(0.2)
            
            # Wait for bank interface to open
            timeout = 5
            start_time = time.time()
            while not self.bank.is_open:
                if time.time() - start_time > timeout:
                    self.log.warning("Timed out waiting for bank to open")
                    return False
                time.sleep(0.5)
            
            # Deposit all items
            self.bank.deposit_inv()
            time.sleep(random.uniform(0.5, 1.0))
            
            # Close bank
            self.bank.close()
            return True
            
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
