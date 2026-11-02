"""Player fatigue and per-account "personality" (Igor's wish, Nov 2026). Used by EVERY bot
through the shared habits (core/human.py), the mouse (core/input/mouse_control.py) and the
breaks (core/control.py) - a bot doesn't need to do anything for it.

The idea: a real player gets slower and sloppier the longer he plays, and recovers on
breaks. One number per running bot, `level()` in [0, 1]:

- starts low at login (a bit higher late at night), with a short warm-up at the start where
  the player is still a little slow (first few minutes);
- climbs while playing (per-account rate, faster at night), slower as it gets high;
- drops during short breaks and alt-tabs, mostly resets during a long break (logged out).

What it changes (every effect scaled by `fatigue_strength`, 0 = off):
- mouse moves get slower and their speed less steady, button holds a bit longer;
- misclicks, short extra pauses and alt-tabs get more frequent;
- "attention lapses": now and then a few seconds of doing nothing (more when tired);
- short and long breaks get more likely.

Per-account profile: a few numbers drawn once from the account name (the same account
always gets the same "player"): base speed, how fast it tires, how well it recovers, how
long it likes to play, when its "night" starts. Different accounts on one PC never behave
exactly alike.
"""

from __future__ import annotations

import hashlib
import os
import random
import threading
import time
from dataclasses import dataclass

from core.logger import get_logger

log = get_logger("Fatigue")


@dataclass
class Profile:
    account: str
    speed: float          # base mouse/reaction factor (<1 = quicker player)
    tire_per_hour: float  # fatigue gained per hour of play at level 0
    recover: float        # how well breaks bring it down (multiplier)
    session_mult: float   # multiplies session_max_minutes (how long it likes to play)
    lapse_base: float     # attention-lapse chance per check when fresh
    night_start: float    # local hour its "night" starts (tired faster, starts more tired)
    warmup_min: float     # minutes of warm-up after login

    def describe(self) -> str:
        return (f"speed x{self.speed:.2f}, tires {self.tire_per_hour:.2f}/h, recovery x{self.recover:.2f}, "
                f"sessions x{self.session_mult:.2f}, night from {self.night_start:.1f}h, "
                f"warm-up {self.warmup_min:.0f} min")


def make_profile(account: str) -> Profile:
    """Same account -> same numbers (seeded by the name)."""
    seed = int(hashlib.sha256(account.lower().encode()).hexdigest()[:12], 16)
    r = random.Random(seed)
    return Profile(
        account=account,
        speed=r.uniform(0.88, 1.14),
        tire_per_hour=r.uniform(0.16, 0.34),
        recover=r.uniform(0.75, 1.3),
        session_mult=r.uniform(0.75, 1.25),
        lapse_base=r.uniform(0.004, 0.012),
        night_start=r.uniform(22.5, 25.5) % 24,
        warmup_min=r.uniform(4, 10),
    )


def _local_hour() -> float:
    """Hour of the day where Igor is (the VM clock may be UTC)."""
    try:
        from zoneinfo import ZoneInfo
        from datetime import datetime
        now = datetime.now(ZoneInfo(os.environ.get("OSRS_TZ", "Europe/Belgrade")))
    except Exception:
        lt = time.localtime()
        return lt.tm_hour + lt.tm_min / 60
    return now.hour + now.minute / 60


class Fatigue:
    """One per process (one bot runs per slot app). Thread-safe enough: plain floats."""

    LOG_EVERY = 15 * 60  # s between "Fatigue: ..." log lines

    def __init__(self):
        self.profile: Profile | None = None
        self.strength = 0.0     # 0 = everything off
        self._level = 0.0
        self._t = time.time()
        self._session_start = time.time()
        self._resting_until = 0.0   # an alt-tab or break in progress (set by the habits)
        self._last_log = 0.0
        self._lock = threading.Lock()
        self._break_until_fn = None  # () -> time the current game break ends

    # ------------------------------------------------------------ setup
    def start(self, account: str, strength: float, break_until_fn=None) -> Profile:
        """Called when a bot starts (and after a relogin via `fresh_session`)."""
        self.profile = make_profile(account or "unknown")
        self.strength = max(0.0, float(strength))
        self._break_until_fn = break_until_fn
        self.fresh_session(reason="bot start")
        return self.profile

    def stop(self) -> None:
        """A new bot is starting: off until its human_init() starts it again (bots
        without the shared habits keep the plain mouse)."""
        self.profile = None
        self.strength = 0.0
        self._resting_until = 0.0

    def fresh_session(self, reason: str = "login") -> None:
        p = self.profile
        if not p:
            return
        with self._lock:
            night = self._night_factor()
            # a rested player starts near 0; at night already a bit tired
            self._level = min(0.5, random.uniform(0.0, 0.08) + 0.22 * night)
            self._t = self._session_start = time.time()
        log.info(f"Fatigue: fresh session ({reason}), level {self._level:.2f}"
                 + (f" (night {night:.1f})" if night > 0 else ""))

    # ------------------------------------------------------------ state
    def _night_factor(self) -> float:
        """0 by day, rising to 1 three hours into this account's night; the night lasts
        9 hours from night_start (to about 7-10 am)."""
        p = self.profile
        if not p:
            return 0.0
        since = (_local_hour() - p.night_start) % 24
        return min(1.0, since / 3.0) if since < 9 else 0.0

    def _resting(self, now: float) -> bool:
        if now < self._resting_until:
            return True
        try:
            return bool(self._break_until_fn and now < float(self._break_until_fn()))
        except Exception:
            return False

    def level(self) -> float:
        """Current fatigue 0..1 (updates itself from the time passed)."""
        p = self.profile
        if not p or self.strength <= 0:
            return 0.0
        with self._lock:
            now = time.time()
            dt = max(0.0, min(now - self._t, 600.0))  # a long gap: count at most 10 min
            self._t = now
            if self._resting(now):
                # breaks bring it down (about -0.1 per minute of rest, per profile)
                self._level -= dt / 60.0 * 0.10 * p.recover * (0.5 + self._level)
            else:
                rate = p.tire_per_hour * (1 + 0.35 * self._night_factor())
                self._level += dt / 3600.0 * rate * (1.15 - self._level)  # slows near the top
            self._level = min(1.0, max(0.0, self._level))
            lvl = self._level
        if now - self._last_log >= self.LOG_EVERY:
            self._last_log = now
            log.info(f"Fatigue: level {lvl:.2f} after {(now - self._session_start) / 60:.0f} min "
                     f"({self.label(lvl)}); warm-up {self.warmup():.2f}")
        return lvl

    @staticmethod
    def label(lvl: float) -> str:
        return "fresh" if lvl < 0.2 else "fine" if lvl < 0.4 else "tired" if lvl < 0.65 else "very tired"

    def warmup(self) -> float:
        """1 right after login, fading to 0 over the profile's warm-up minutes."""
        p = self.profile
        if not p or self.strength <= 0:
            return 0.0
        mins = (time.time() - self._session_start) / 60.0
        return max(0.0, 1.0 - mins / max(1.0, p.warmup_min))

    def rest(self, seconds: float) -> None:
        """An alt-tab / pause of `seconds` starts now: counts as rest."""
        self.level()  # bring the level up to now first
        self._resting_until = max(self._resting_until, time.time() + max(0.0, seconds))

    def long_rest(self) -> None:
        """Logged out for a long break: most of the fatigue is gone afterwards."""
        if not self.profile:
            return
        with self._lock:
            keep = max(0.0, 0.35 - 0.15 * self.profile.recover)
            self._level *= keep
        self.fresh_session(reason="after a long break")

    # ------------------------------------------------------------ effects
    def _s(self, x: float) -> float:
        return x * self.strength

    def mouse_factor(self) -> float:
        """Multiplies how long a mouse move takes."""
        if not self.profile or self.strength <= 0:
            return 1.0
        f = self.level()
        return self.profile.speed * (1 + self._s(0.40 * f + 0.15 * self.warmup()))

    def mouse_spread(self) -> float:
        """Multiplies the spread of the per-move speed (tired = less steady)."""
        return 1 + self._s(0.6 * self.level())

    def hold_factor(self) -> float:
        return 1 + self._s(0.18 * self.level())

    def react_factor(self) -> float:
        """Multiplies small reaction pauses (settle before a click, after a misclick)."""
        if not self.profile or self.strength <= 0:
            return 1.0
        return self.profile.speed * (1 + self._s(0.5 * self.level() + 0.2 * self.warmup()))

    def chance(self, base: float, gain: float) -> float:
        """A habit's chance raised with fatigue: base * (1 + gain*level), capped."""
        if base <= 0:
            return base
        return min(0.95, base * (1 + self._s(gain * self.level())))

    def lapse_seconds(self) -> float:
        """0, or the length of an attention lapse to take now (looked at the phone...)."""
        p = self.profile
        if not p or self.strength <= 0:
            return 0.0
        f = self.level()
        if random.random() >= p.lapse_base * (1 + self._s(5.0 * f)) * min(1.0, self.strength):
            return 0.0
        return min(20.0, random.lognormvariate(1.0 + 0.6 * f, 0.5))  # mostly 2-6 s, tired longer


_FATIGUE = Fatigue()


def get() -> Fatigue:
    return _FATIGUE
