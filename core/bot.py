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
        # Some short breaks: look through skills/quests/equipment... tabs, then back.
        self.control.on_short_break = self._browse_tabs
        self.control.on_short_break_chance = float(break_ui_browse_chance)
        
        self.api = BotAPI(self.client)
        # Always enable CV debug for bot monitoring
        debug_port = instance.port(5555)  # shifted per fleet slot
        if not cv_debug._enabled:
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