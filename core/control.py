import os
import time
from functools import wraps
from bots.core.cfg_types import BreakCfgParam
from core.logger import get_logger
import threading


class SingletonMeta(type):
    """A thread-safe implementation of a Singleton metaclass."""
    _instances = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            instance = super().__call__(*args, **kwargs)
            cls._instances[cls] = instance
        return cls._instances[cls]

class ScriptControl(metaclass=SingletonMeta):
    def __init__(self):
        self._terminate = False
        self._pause = False
        self.break_until: float = 0
        self.break_config: BreakCfgParam = None
        # After a break ends, no new break for this long (seconds).
        self.break_cooldown_seconds: float = float(os.environ.get("OSRS_BREAK_COOLDOWN", 180))
        # Long breaks (AFK long enough to get logged out): own chance/duration and
        # a long cooldown counted from the end of the previous long break.
        self.long_break_config: BreakCfgParam = None
        self.long_break_cooldown_seconds: float = float(os.environ.get("OSRS_LONG_BREAK_COOLDOWN", 90 * 60))
        self.long_break_end: float = 0
        # Called (once, before the next guarded action) after a long break, e.g. to log in again.
        self.after_long_break = None
        # Called once when a long break starts (e.g. log out), with clicks allowed.
        self.before_long_break = None
        self._relogin_needed = False
        self._relogging = False
        self._relogin_lock = threading.RLock()
        # Called once at the start of some short breaks (e.g. look through the
        # side-panel tabs), with this chance per short break.
        self.on_short_break = None
        self.on_short_break_chance: float = 0.0
        self._break_hook_pending = False
        self._break_hooking = False
        self._tls = threading.local()  # lets the hook's own clicks pass the guard
        self.log = get_logger("ScriptControl")
        self._listener: threading.Thread = None
        
        
        self.start_listener()
        
        

    
    def start_listener(self):
        """Start a thread to listen for termination and pause requests.

        Uses keyboard.hook so we can differentiate physical PageUp/PageDown keys
        from numpad 9/3 (which report as PageUp/PageDown when NumLock is off).
        We only act on PageUp/PageDown when the event is NOT from keypad. This
        prevents accidental termination/pause when using numpad navigation.
        """
        if self._listener is None or not self._listener.is_alive():
            self._listener = threading.Thread(target=self._listen_for_control, daemon=True)
            self._listener.start()


    def propose_break(self):
        """Propose break based on configuration."""
        if self.break_config:
            # break_until is when the last break ended (0 = none yet)
            now = time.time()
            if now < self.break_until:
                return  # already on a break
            lb = self.long_break_config
            if (lb and now >= self.long_break_end + self.long_break_cooldown_seconds
                    and lb.should_break()):
                sec = int(lb.break_duration.choose())
                self.initialize_break(sec)
                self.long_break_end = self.break_until
                self._relogin_needed = True
                if self.before_long_break:
                    self.log.info(f"Long break: logging out for {sec // 60} min {sec % 60} s.")
                    self._tls.bypass = True  # the hook's clicks must not wait for the break
                    try:
                        self.before_long_break()
                    except ScriptTerminationException:
                        raise
                    except Exception:
                        self.log.warning("Couldn't log out for the long break (staying AFK)", exc_info=True)
                    finally:
                        self._tls.bypass = False
                else:
                    self.log.info(f"Long break: going AFK for {sec // 60} min {sec % 60} s.")
                return
            if now < self.break_until + self.break_cooldown_seconds:
                return
            if self.break_config.should_break():
                sec = int(self.break_config.break_duration.choose())
                self.initialize_break(
                    sec
                )
                self.log.info(f"Sleeping for {sec} seconds.")
                import random
                if self.on_short_break and random.random() < self.on_short_break_chance:
                    self._break_hook_pending = True
        else:
            self.log.warning("Break proposed but no break configuration set.")
    def _listen_for_control(self):
        """Thread function to listen for control signals.

        Distinguishes keypad vs non-keypad PageUp/PageDown using event.is_keypad.
        Terminate: Physical PageUp (not keypad) key down.
        Pause toggle: Physical PageDown (not keypad) key down.

        Numpad 9 / 3 (NumLock off -> PageUp/PageDown) are ignored so they don't
        unintentionally terminate or pause the script.
        """
        import sys
        if sys.platform.startswith('linux'):
            # On the fleet VM there is no physical keyboard per bot and the
            # `keyboard` package needs root. Stop/pause from the web UI instead.
            self.log.info("Linux: PageUp/PageDown hotkeys disabled; use the web UI to stop/pause.")
            return
        try:
            import keyboard  # type: ignore
        except ImportError:
            self.log.error("keyboard module not available; control hotkeys disabled.")
            return

        # Debounce to avoid rapid toggles if OS sends repeats
        last_pause_toggle = 0.0
        toggle_cooldown = 0.4  # seconds

        def handler(e):
            nonlocal last_pause_toggle
            try:
                # We only act on key down events
                if getattr(e, 'event_type', None) != 'down':
                    return
                name = (e.name or '').lower()
                is_keypad = getattr(e, 'is_keypad', False)
                is_pageup = name in ('page up', 'pageup')
                is_pagedown = name in ('page down', 'pagedown')

                # Is pageup and is not from numpad (Numpad 9)
                if is_pageup and not is_keypad:
                    self.terminate = True
                # Is pagedown and is not from numpad (Numpad 3)
                elif is_pagedown and not is_keypad:
                    now = time.time()
                    if now - last_pause_toggle >= toggle_cooldown:
                        self.pause = not self.pause
                        last_pause_toggle = now
                else:
                    # Optional future: map dedicated keypad combo if desired
                    pass
            except Exception as ex:  # Never let hook raise
                self.log.debug(f"Control hook error: {ex}")

        hook = keyboard.hook(handler)
        # Keep thread alive until termination requested
        while not self.terminate:
            time.sleep(0.25)
        keyboard.unhook(hook)
        self.log.info("Control listener thread exiting.")

    @property
    def terminate(self):
        return self._terminate

    @terminate.setter
    def terminate(self, value: bool):
        if self._terminate != value:
            self.log.info(f"Terminate set to {value}")
        self._terminate = value

    @property
    def pause(self):
        return self._pause
    
    def reset(self):
        """Reset control flags to default states."""
        self.log.info("Resetting ScriptControl state.")
        self._terminate = False
        self._pause = False
        self.break_until = 0
        self.long_break_end = 0
        self._relogin_needed = False
        self._break_hook_pending = False
        self._break_hooking = False
        
        # Ensure listener thread calls are responsive
        self.start_listener()

    @pause.setter
    def pause(self, value: bool):
        if self._pause != value:
            self.log.info(f"Pause {'enabled' if value else 'disabled'}")
        self._pause = value

    def initialize_break(self, seconds: int):
        """Set the break duration without causing the caller to sleep."""
        self.break_until = time.time() + int(seconds)

    def _after_long_break(self):
        # One thread runs the hook; other threads wait for it to finish.
        # RLock: the hook's own guarded calls (clicks) pass straight through.
        with self._relogin_lock:
            if not self._relogin_needed:
                return
            if self.after_long_break:
                self.log.info("Long break over: getting back into the game")
                self._relogging = True
                self._relogin_needed = False
                try:
                    self.after_long_break()
                except Exception:
                    self.log.error("Couldn't get back into the game after the long break", exc_info=True)
                finally:
                    self._relogging = False
            self._relogin_needed = False

    def _run_break_hook(self):
        with self._relogin_lock:
            if not self._break_hook_pending:
                return
            self._break_hooking = True
            self._break_hook_pending = False
        self._tls.bypass = True
        try:
            self.on_short_break()
        except ScriptTerminationException:
            raise
        except Exception:
            self.log.warning("Break activity failed", exc_info=True)
        finally:
            self._tls.bypass = False
            self._break_hooking = False

    def guard(self, func):
        """
        Decorator to enforce termination and break logic.
        Raises RuntimeError if termination is requested.
        Waits if a break is active.
        """
        @wraps(func)
        def wrapper(*args, **kwargs):
            if getattr(self._tls, "bypass", False):
                return func(*args, **kwargs)  # inside the break hook
            while time.time() < self.break_until or self.pause or self._break_hooking:
                if self.terminate:
                    raise ScriptTerminationException()
                if self._break_hook_pending and not self.pause:
                    self._run_break_hook()
                    continue
                time.sleep(1)
            if self.terminate:
                raise ScriptTerminationException()
            if self._relogin_needed or self._relogging:
                self._after_long_break()
            return func(*args, **kwargs)
        return wrapper


class ScriptTerminationException(Exception):
    """Exception raised when script termination is requested."""
    def __init__(self, message="Script termination requested."):
        self.message = message
        super().__init__(self.message)
        
    def __str__(self):
        return self.message