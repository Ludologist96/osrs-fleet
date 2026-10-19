from core.osrs_client import RuneLiteClient
from core.item_db import ItemLookup
from core.bank import BankInterface
from core.control import ScriptControl
from bots.core.cfg_types import BreakCfgParam
from core.movement import MovementOrchestrator
from core.api import BotAPI
from core.logger import get_logger
from core import cv_debug
from core import instance
import os

class Bot:
    def __init__(self, user='', break_cfg: BreakCfgParam = None, long_break_cfg: BreakCfgParam = None,
                 break_ui_browse_chance: float = 0.0):
        self.log = get_logger(getattr(self, 'name', 'Bot'))
        self.control = ScriptControl()
        # Clear script control state on start
        self.control.reset()
        self.client = RuneLiteClient(user)
        self.itemdb = ItemLookup()
        self.bank = BankInterface(self.client, self.itemdb)
        self.mover = MovementOrchestrator(self.client)
        

        if break_cfg:
            self.control.break_config = break_cfg
        # Long break (AFK 10-15 min): the game logs the character out meanwhile,
        # so log in again before the bot's next action.
        self.control.long_break_config = long_break_cfg
        self.control.after_long_break = self._log_back_in
        # ...and log out when it starts (a player who stops for half an hour logs out).
        self.control.before_long_break = self._log_out
        # Some short breaks: look through skills/quests/equipment... tabs, then back.
        self.control.on_short_break = self._browse_tabs
        self.control.on_short_break_chance = float(break_ui_browse_chance)
        
        self.api = BotAPI(self.client)
        # CV debug keeps copies of screenshots and PNG-encodes them (~hundreds of MB and
        # CPU per bot). On the fleet nobody watches it, so it stays off unless
        # OSRS_CV_DEBUG=1 (fleet.conf CV_DEBUG=1) or the web UI's CV debug switch turns it on.
        debug_port = instance.port(5555)  # shifted per fleet slot
        want_debug = os.environ.get("OSRS_CV_DEBUG", "0" if instance.IS_FLEET else "1") == "1"
        if want_debug and not cv_debug._enabled:
            cv_debug.enable(port=debug_port)
            self.log.info(f"CV Debug enabled on port {debug_port}")
        
        # Store debug port in API for endpoint use
        self.api._debug_port = debug_port
        
        self.api.start(port=instance.port(5432))

        # Every bot starts on the inventory tab.
        self._open_inventory()
        
        
    def _log_back_in(self):
        from core import login
        result = login.login()
        if result.get("state") != "game":
            raise RuntimeError(f"still not in game: {result}")
        self.log.info("Back in the game")
        self._open_inventory()

    def _log_out(self):
        """Logout tab -> the red "Click here to logout" button. Verified by the game view
        disappearing (login screen)."""
        import random
        import time
        import numpy as np
        import cv2
        from core import login
        from core.osrs_client import ToolplaneTab
        from core.region_match import MatchResult
        from PIL import Image
        from core import tools
        for attempt in range(3):
            # the door icon at the bottom of the side panel (click it directly: the
            # tab-state check can think it's already open)
            door = getattr(self.client.toolplane, "logout", None)
            try:
                found = tools.find_subimage(self.client.get_screenshot(), Image.open("data/ui/logout.webp"),
                                            min_scale=1, max_scale=1)
                if found.confidence >= 0.8:
                    door = found
            except Exception:
                pass
            if door is None:
                raise RuntimeError("logout tab icon not found")
            self.log.debug(f"Logout tab icon at {door.bounding_box}")
            self.client.click(door.scale_px(-3).get_point_within())
            time.sleep(random.uniform(0.8, 1.4))
            sc = self.client.get_screenshot()
            # search the right part of the window (side panel)
            tp = MatchResult(sc.width // 2, 0, sc.width, sc.height)
            arr = np.asarray(tp.crop_in(sc).convert("RGB"), dtype=np.int16)
            r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
            red = ((r >= 110) & (g <= 60) & (b <= 60) & (r - g >= 70)).astype(np.uint8)
            num, _, stats, _ = cv2.connectedComponentsWithStats(red, connectivity=8)
            if num <= 1 or stats[1:, cv2.CC_STAT_AREA].max() < 800:
                self.log.warning("Logout button not found")
                continue
            i = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
            x, y, w, h = (int(v) for v in stats[i][:4])
            button = MatchResult(tp.start_x + x + 8, tp.start_y + y + 5,
                                 tp.start_x + x + w - 8, tp.start_y + y + h - 5)
            self.client.click(button.get_point_within())
            for _ in range(10):
                time.sleep(1)
                if login.state().get("state") != "game":
                    self.log.info("Logged out")
                    return
        raise RuntimeError("couldn't log out")

    def _open_inventory(self):
        from core.osrs_client import ToolplaneTab
        try:
            self.client.click_toolplane(ToolplaneTab.INVENTORY)
        except Exception:
            self.log.warning("Couldn't open the inventory tab", exc_info=True)

    def _browse_tabs(self):
        from core import idle
        idle.browse_tabs(self.client, self.control, self.log)

    @property
    def terminate(self) -> bool:
        return self.control.terminate

    @terminate.setter
    def terminate(self, value: bool):
        self.control.terminate = value