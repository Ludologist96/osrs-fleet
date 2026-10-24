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

        # Every bot starts on the inventory tab in the home camera view (zoomed out about
        # halfway, top-down). The bot manager calls _start_view() when the bot starts, so
        # a subclass can first replace self.camera with its own settings.
        from core.camera import Camera
        self.camera = Camera(self.client)
        # Stopping a bot (stop button, timed stop) logs the character out afterwards.
        self.logout_on_stop = True
        # What the bot is doing right now (shown in the launcher / Telegram): working,
        # fighting, looting, banking, dropping, resting, roaming, alt tab...
        # Breaks and logins are added by the bot manager from ScriptControl.
        self.activity = "starting"
        # Things done this run, e.g. {"logs": 120, "kills": 40} (report at the end).
        self.counts: dict = {}
        
        
    def _log_back_in(self):
        from core import login
        result = login.login()
        if result.get("state") != "game":
            raise RuntimeError(f"still not in game: {result}")
        self.log.info("Back in the game")
        self._start_view()

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
            tp = MatchResult(int(sc.width * 0.65), 0, sc.width, sc.height)
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

    def logout_after_stop(self):
        """Called by the bot manager after a stopped bot's loop has ended. Clicks normally
        refuse to run once terminate is set, so let them through for the logout."""
        from core import login
        if not self.logout_on_stop:
            return
        self.control._tls.bypass = True
        try:
            if login.state().get("state") != "game":
                return
            self.log.info("Bot stopped: logging out")
            self._log_out()
        except Exception:
            self.log.warning("Couldn't log out after the stop", exc_info=True)
        finally:
            self.control._tls.bypass = False

    # ------------------------------------------------------------------ watchdog
    WATCHDOG_EVERY = 30.0   # s between screen checks
    RELOGIN_TRIES = 5   # the login server sometimes refuses for a few minutes

    def watchdog(self, force: bool = False) -> bool:
        """Look at the screen every so often: still in the game? If it got logged out
        (disconnect, idle logout) log back in and carry on. Planned long breaks are left
        alone (the break itself logs out and back in). Returns False when it couldn't get
        back in (the caller should stop; exit_reason is "login_failed")."""
        import time
        from core import login
        now = time.time()
        if not force and now - getattr(self, "_watchdog_last", 0) < self.WATCHDOG_EVERY:
            return True
        self._watchdog_last = now
        c = self.control
        if c.terminate or c._relogin_needed or c._relogging or now < c.long_break_end or now < c.break_until:
            return True
        try:
            self.client.ensure_window()  # RuneLite restarted: use its new window
            st = login.state()
        except Exception as e:
            self.log.debug(f"Watchdog: couldn't read the screen: {e}")
            return True
        if st.get("state") == "game":
            self.watchdog_in_game()
            return True
        self.log.warning(f"Watchdog: not in the game (disconnected or logged out; "
                         f"confidence {st.get('in_game_confidence')}) - logging back in")
        for attempt in range(1, self.RELOGIN_TRIES + 1):
            if c.terminate:
                return True
            try:
                self._log_back_in()
                self.log.info(f"Watchdog: back in the game (attempt {attempt})")
                self.relogins = getattr(self, "relogins", 0) + 1
                return True
            except Exception as e:
                self.log.warning(f"Watchdog: login attempt {attempt} failed: {e}")
                time.sleep(15 * attempt)  # 15, 30, 45, 60 s
        self.log.error("Watchdog: couldn't get back into the game. Stopping.")
        self.exit_reason = "login_failed"
        return False

    def recover_window(self, error: Exception | None = None, timeout: float = 180.0) -> bool:
        """After an error: if the RuneLite window is gone (client crashed or restarted -
        a new one takes up to a minute to open), wait for it, then log back in.
        Returns True when it handled such a case (the caller shouldn't count the error)."""
        import time
        if self.client.ensure_window() and not (error and "is not open" in str(error)):
            return False
        self.log.warning("RuneLite window not there: waiting for the client to come back")
        deadline = time.time() + timeout
        while time.time() < deadline and not self.control.terminate:
            time.sleep(5)
            if self.client.ensure_window():
                time.sleep(5)  # let it finish drawing the login screen
                self.watchdog(force=True)
                return True
        self.log.error(f"RuneLite didn't come back within {timeout / 60:.0f} min")
        return False

    def watchdog_in_game(self):
        """Extra checks while in the game; bots override (e.g. close a stray menu)."""

    def save_debug_shot(self, tag: str) -> None:
        """Keep a screenshot of an odd moment: data/screenshots/watchdog/slotN-<tag>-<time>.png"""
        import time
        from core import instance
        try:
            os.makedirs("data/screenshots/watchdog", exist_ok=True)
            path = (f"data/screenshots/watchdog/slot{getattr(instance, 'SLOT', 0)}-{tag}-"
                    f"{time.strftime('%Y%m%d-%H%M%S')}.png")
            self.client.get_screenshot().save(path)
            self.log.info(f"Saved screenshot {path}")
        except Exception as e:
            self.log.debug(f"Couldn't save a screenshot: {e}")

    def _start_view(self):
        self._open_inventory()
        try:
            self.camera.top_down()
        except Exception:
            self.log.warning("Couldn't set the top-down camera", exc_info=True)

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