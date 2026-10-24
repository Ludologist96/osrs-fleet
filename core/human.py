"""
Player-like habits shared by the woodcutter and the slayer bot (Igor's TODO, Oct 2026):

- alt-tab: shortly after a successful tree / attack click, now and then look at another
  window (the RuneLite window loses the focus) for a few seconds, sometimes longer,
  then come back and look at what the character is doing;
- walk-away: after a finished cycle, now and then take a few steps via the minimap;
- home area: remember the minimap at the start, walk back when the bot wandered off;
- micro-idle: a short extra pause after a click;
- misclick: rarely click a little next to the target, then click the target again;
- a forced camera fidget when none happened for a while;
- breaks start "on cooldown" when a bot starts, a long break is forced after
  session_max_minutes, a short one after N actions without a break.

Bots use this as a mixin next to core.bot.Bot. Every setting comes from the bot's
config (fields named below); a missing field simply turns that habit off.
"""

from __future__ import annotations

import math
import random
import time

from core.control import ScriptTerminationException


def _v(cfg, name: str, default=None):
    p = getattr(cfg, name, None)
    if p is None:
        return default
    return getattr(p, "value", p)


class HumanMixin:
    """Needs self.cfg, self.client, self.control, self.log, self.camera (core.bot.Bot)."""

    # ------------------------------------------------------------ setup
    def human_init(self) -> None:
        now = time.time()
        self.last_alt_tab = now        # start "on cooldown"
        self.last_walk_away = now
        self.actions_since_fidget = 0
        self.actions_since_break = 0
        self._break_seen_until = 0.0
        c = self.control
        # treat the short and long break cooldowns as already running
        c.break_until = now
        c.long_break_end = now
        c.session_start = now
        c.session_max_seconds = 60.0 * float(_v(self.cfg, "session_max_minutes", 0) or 0)
        self.log.info("Breaks, alt-tab and walk-away start on cooldown "
                      f"(long break forced after {c.session_max_seconds / 60:.0f} min of play)")

    # ------------------------------------------------------------ small things
    def sleep_checked(self, seconds: float) -> None:
        """Sleep in short steps so a stop takes effect at once."""
        end = time.time() + seconds
        while time.time() < end:
            if self.control.terminate:
                raise ScriptTerminationException()
            time.sleep(min(0.25, max(0.0, end - time.time())))

    def micro_idle(self) -> None:
        """After a successful click, sometimes a short extra pause (looking at the screen)."""
        if random.random() < float(_v(self.cfg, "micro_idle_chance", 0) or 0):
            lo, hi = _v(self.cfg, "micro_idle", (0.25, 0.9))
            time.sleep(random.uniform(lo, hi))

    def note_action(self) -> None:
        """One successful main action (tree chopped / monster killed): counts for the
        forced camera fidget and the forced short break."""
        self.actions_since_fidget += 1
        c = self.control
        if c.break_until > self._break_seen_until and time.time() >= c.break_until:
            # a break happened (and ended) since the last action
            self._break_seen_until = c.break_until
            self.actions_since_break = 0
        self.actions_since_break += 1

    def maybe_camera_fidget(self) -> bool:
        """camera_chance per action; if camera_force_every actions passed without one, force it."""
        chance = float(_v(self.cfg, "camera_chance", 0) or 0)
        every = int(_v(self.cfg, "camera_force_every", 0) or 0)
        forced = every and self.actions_since_fidget >= every
        if not forced and random.random() >= chance:
            return False
        self.camera.random_move(_v(self.cfg, "camera_rotate_time", (0.3, 1.2)),
                                float(_v(self.cfg, "camera_zoom_chance", 0.5)))
        if forced:
            self.log.info(f"Camera fidget (none for {self.actions_since_fidget} actions)")
        self.actions_since_fidget = 0
        return True

    def maybe_forced_break(self, limit_field: str) -> None:
        """No break for `limit` actions: take a short one now."""
        limit = int(_v(self.cfg, limit_field, 0) or 0)
        if not limit or self.actions_since_break < limit:
            return
        c = self.control
        if time.time() < c.break_until:
            return
        cfg = c.break_config
        lo, hi = cfg.break_duration.value if cfg else (12, 40)
        sec = int(random.uniform(lo, hi))
        self.log.info(f"{self.actions_since_break} actions without a break: short break of {sec}s")
        c.initialize_break(sec)
        if c.on_short_break and random.random() < c.on_short_break_chance:
            c._break_hook_pending = True
        self.actions_since_break = 0

    # ------------------------------------------------------------ alt-tab
    def maybe_alt_tab(self, still_busy, what: str = "action") -> bool:
        """Call 1-2 s after a successful main click. With alt_tab_chance (once the
        cooldown is over) the RuneLite window loses the focus for a while: mouse out of
        the window, click on the desktop, wait, mouse back in, look at the screen.
        `still_busy()` is asked after coming back (just for the log).
        Returns True when it alt-tabbed."""
        chance = float(_v(self.cfg, "alt_tab_chance", 0) or 0)
        cooldown = float(_v(self.cfg, "alt_tab_cooldown", 60) or 0)
        now = time.time()
        if not chance or now - self.last_alt_tab < cooldown:
            return False
        if time.time() < self.control.break_until or self.control.pause:
            return False
        if random.random() >= chance:
            self.last_alt_tab = now  # rolled: wait the cooldown before rolling again
            return False
        if random.random() < float(_v(self.cfg, "alt_tab_medium_chance", 0.22)):
            secs = random.uniform(*_v(self.cfg, "alt_tab_medium", (25.0, 90.0)))
            kind = "medium"
        else:
            secs = random.uniform(*_v(self.cfg, "alt_tab_short", (4.0, 18.0)))
            kind = "short"
        prev = getattr(self, "activity", "")
        self.set_activity("alt tab")
        self.log.info(f"Alt-tab: another window for {secs:.0f}s ({kind}) while the {what} goes on")
        try:
            self._leave_window()
            self.sleep_checked(secs)
            self._return_to_window()
            busy = None
            try:
                busy = still_busy()
            except ScriptTerminationException:
                raise
            except Exception:
                pass
            self.log.info(f"Back from alt-tab: the {what} is " +
                          ("still going" if busy else "over" if busy is False else "?"))
        finally:
            self.last_alt_tab = time.time()
            self.set_activity(prev or "working")
        return True

    def _leave_window(self) -> None:
        """Mouse out of the RuneLite window onto the desktop and click there: the game
        loses the focus (what it sees when a player alt-tabs)."""
        import pyautogui
        from core.input import mouse_control
        w = self.client.window
        sw, sh = pyautogui.size()
        left, top = int(w.left), int(w.top)
        right, bottom = left + int(w.width), top + int(w.height)
        free = []
        if left > 60:
            free.append((10, left - 25, top + 20, bottom - 20))
        if sw - right > 60:
            free.append((right + 25, sw - 10, top + 20, bottom - 20))
        if top > 60:
            free.append((left + 20, right - 20, 10, top - 25))
        if sh - bottom > 60:
            free.append((left + 20, right - 20, bottom + 25, sh - 10))
        if not free:
            self.log.debug("No desktop around the window: just moving the mouse away")
            self.client.move_off_window()
            return
        x1, x2, y1, y2 = random.choice(free)
        x, y = random.randint(x1, max(x1, x2)), random.randint(y1, max(y1, y2))
        mouse_control.move_to(x, y)
        time.sleep(random.uniform(0.05, 0.2))
        mouse_control.press()
        time.sleep(0.3)
        try:
            still = self.client.window._is_active() if hasattr(self.client.window, "_is_active") else None
        except Exception:
            still = None
        if still:
            # the window manager kept the focus on RuneLite: give it to the desktop
            try:
                win = self.client.window
                X = win.Xlib.X
                win.display.set_input_focus(X.PointerRoot, X.RevertToPointerRoot, X.CurrentTime)
                win.display.flush()
            except Exception:
                self.log.debug("Couldn't move the focus off RuneLite", exc_info=True)
        self.log.debug(f"Alt-tab: clicked the desktop at ({x},{y}); RuneLite focused: "
                       f"{self.client.window._is_active() if hasattr(self.client.window, '_is_active') else '?'}")

    def _return_to_window(self) -> None:
        """Back: focus RuneLite, mouse to a random spot in the game view, look a moment."""
        from core.camera import GAME_VIEW
        self.client.bring_to_focus()
        x1, y1, x2, y2 = GAME_VIEW
        self.client.move_to((random.randint(x1, x2), random.randint(y1, y2)))
        time.sleep(random.uniform(0.4, 1.1))

    # ------------------------------------------------------------ walk away
    def maybe_walk_away(self, prefer: bool = False) -> bool:
        """After a finished cycle: with walk_away_chance (x3 when `prefer`, e.g. all trees
        are stumps / nothing to attack), once the cooldown is over, take one short walk
        via the minimap (3-8 tiles in a random direction), then maybe a short pause."""
        chance = float(_v(self.cfg, "walk_away_chance", 0) or 0)
        cooldown = float(_v(self.cfg, "walk_away_cooldown", 300) or 0)
        if not chance or time.time() - self.last_walk_away < cooldown:
            return False
        if random.random() >= min(1.0, chance * (3 if prefer else 1)):
            return False
        self.last_walk_away = time.time()
        prev = getattr(self, "activity", "")
        self.set_activity("roaming")
        try:
            tiles = random.uniform(*_v(self.cfg, "walk_away_tiles", (3, 8)))
            self.minimap_step(tiles)
            lo, hi = _v(self.cfg, "walk_away_pause", (0.8, 2.2))
            if random.random() < 0.7:
                self.sleep_checked(random.uniform(lo, hi))
            # wait for the walk to end (~0.6 s a tile when walking, half when running)
            self.sleep_checked(tiles * random.uniform(0.35, 0.55))
        finally:
            self.set_activity(prev or "working")
        return True

    MINIMAP_PX_PER_TILE = 4.5  # default minimap zoom (seen: 5-14 px = 1-3 tiles)

    def minimap_step(self, tiles: float, toward: tuple[float, float] | None = None,
                     spread: float = 50.0, label: str = "Walk-away") -> tuple[int, int]:
        """Click the minimap `tiles` away from the player. `toward` = a minimap point: go
        roughly that way (+-`spread` degrees) instead of a random direction."""
        mm = self.client.minimap.map
        cx, cy = mm.get_center()
        r = min(mm.width, mm.height) / 2 - 8
        dist = min(r, tiles * self.MINIMAP_PX_PER_TILE)
        if toward is not None and (toward[0] - cx or toward[1] - cy):
            ang = math.atan2(toward[1] - cy, toward[0] - cx) + math.radians(random.uniform(-spread, spread))
        else:
            ang = random.uniform(0, 2 * math.pi)
        pt = (int(cx + dist * math.cos(ang)), int(cy + dist * math.sin(ang)))
        self.client.click(pt)
        self.log.info(f"{label}: {tiles:.0f} tiles via the minimap (clicked {pt})")
        return pt

    # ------------------------------------------------------------ home area
    # Remember the minimap around the start area and walk back when the bot wandered off
    # (firemaking steps, chasing monsters, loot). The minimap turns with the camera, so the
    # remembered patch is also tried rotated: works whatever way the camera faces now.
    HOME_R = 21      # px radius kept (the rotated 30x30 core always fits inside it)
    HOME_PATCH = 15  # px half-size of the patch matched (~7 tiles across)
    HOME_ANGLE_STEP = 6  # degrees between the tried rotations

    def _minimap_full(self):
        """(grey minimap image, its top-left in window coords, centre in window coords)."""
        import numpy as np
        sc = self.client.get_screenshot()
        mm = self.client.minimap.map
        x1, y1, x2, y2 = mm.bounding_box
        cx, cy = mm.get_center()
        return np.asarray(sc.convert("L").crop((x1, y1, x2, y2)), dtype=np.float32), (x1, y1), (cx, cy)

    def remember_home(self) -> bool:
        """The character stands in its work area: remember the minimap around it."""
        img, (x1, y1), (cx, cy) = self._minimap_full()
        r = self.HOME_R
        px, py = int(cx - x1), int(cy - y1)
        patch = img[py - r:py + r, px - r:px + r]
        if patch.shape != (2 * r, 2 * r):
            return False
        self._home_patch = patch.copy()
        return True

    def find_home(self, rotations: bool = True):
        """Where the remembered area is on the minimap now: ((x, y) window coords,
        px from the player), or None (nothing remembered / not on the minimap)."""
        import cv2
        home = getattr(self, "_home_patch", None)
        if home is None:
            return None
        img, (x1, y1), (cx, cy) = self._minimap_full()
        r, h = self.HOME_R, self.HOME_PATCH
        best = (-1.0, None)
        angles = range(0, 360, self.HOME_ANGLE_STEP) if rotations else (0,)
        for a in angles:
            if a:
                m = cv2.getRotationMatrix2D((r - 0.5, r - 0.5), a, 1.0)
                rot = cv2.warpAffine(home, m, (2 * r, 2 * r), flags=cv2.INTER_LINEAR)
            else:
                rot = home
            tpl = rot[r - h:r + h, r - h:r + h]
            res = cv2.matchTemplate(img, tpl, cv2.TM_CCOEFF_NORMED)
            _, score, _, loc = cv2.minMaxLoc(res)
            if score > best[0]:
                best = (score, loc)
        score, loc = best
        if loc is None or score < float(_v(self.cfg, "home_match", 0.45)):
            self.log.debug(f"Start area not found on the minimap (best match {score:.2f})")
            return None
        hx, hy = x1 + loc[0] + h, y1 + loc[1] + h
        return (hx, hy), math.hypot(hx - cx, hy - cy)

    def go_home(self, max_tiles: float = 1.0, rotations: bool = True) -> bool:
        """Walk back toward the remembered area if it is more than `max_tiles` away.
        Too far for one minimap click: click the minimap edge that way (look again later)."""
        found = self.find_home(rotations)
        if not found:
            return False
        (hx, hy), dist = found
        if dist < max(4.0, max_tiles * self.MINIMAP_PX_PER_TILE):
            return False
        self.log.info(f"Back to the start area: {dist / self.MINIMAP_PX_PER_TILE:.0f} tiles away")
        mm = self.client.minimap.map
        cx, cy = mm.get_center()
        rad = min(mm.width, mm.height) / 2 - 10
        if dist > rad:
            hx, hy = cx + (hx - cx) * rad / dist, cy + (hy - cy) * rad / dist
        self.set_activity("walking")
        self.client.click((int(hx + random.uniform(-2, 2)), int(hy + random.uniform(-2, 2))))
        self.sleep_checked(1.0 + min(dist, rad) / self.MINIMAP_PX_PER_TILE * 0.6 * random.uniform(0.8, 1.1))
        self.set_activity("working")
        return True

    # ------------------------------------------------------------ misclick
    def maybe_misclick(self, point: tuple[int, int], avoid=None) -> bool:
        """Rarely, right after a successful click: click 8-25 px next to it (the character
        walks there / stops), the caller then clicks its target again. `avoid(text)` -> True
        for mouse-over texts that must not be clicked (e.g. another monster)."""
        if random.random() >= float(_v(self.cfg, "misclick_chance", 0) or 0):
            return False
        from core.input import mouse_control
        for _ in range(4):
            d = random.uniform(8, 25)
            a = random.uniform(0, 2 * math.pi)
            x, y = int(point[0] + d * math.cos(a)), int(point[1] + d * math.sin(a))
            self.client.move_to((x, y))
            time.sleep(random.uniform(0.05, 0.12))
            if avoid:
                try:
                    texts = self.client.get_hover_texts()
                except Exception:
                    texts = []
                if any(avoid(t) for t in texts):
                    continue
            mouse_control.press()
            self.log.info(f"Misclick at ({x},{y}), {d:.0f}px off: clicking the target again")
            time.sleep(random.uniform(0.15, 0.45))
            return True
        return False

    # ------------------------------------------------------------ inventory clicks
    INV_MARGIN = 5      # px kept clear of the slot's edge
    INV_MIN_DIST = 4    # px: never (almost) the same pixel as one of the recent clicks

    def inv_slot(self, m):
        """The whole inventory slot (36x32) an item match lies in - aim there, not at the
        template's box."""
        from core import inventory
        from core.region_match import MatchResult
        cx, cy = m.get_center()
        col = max(0, min(3, round((cx - inventory.ORIGIN[0] - inventory.SLOT[0] / 2) / inventory.STEP[0])))
        row = max(0, min(6, round((cy - inventory.ORIGIN[1] - inventory.SLOT[1] / 2) / inventory.STEP[1])))
        x, y = inventory.ORIGIN[0] + col * inventory.STEP[0], inventory.ORIGIN[1] + row * inventory.STEP[1]
        return MatchResult(x, y, x + inventory.SLOT[0], y + inventory.SLOT[1])

    def inv_point(self, m) -> tuple[int, int]:
        """A random point in the item's slot, mostly near the middle, and never within a
        few px of the last clicks there (a player never hits the same pixel twice)."""
        slot = self.inv_slot(m)
        sx, sy, ex, ey = slot.bounding_box
        sx, sy, ex, ey = sx + self.INV_MARGIN, sy + self.INV_MARGIN, ex - self.INV_MARGIN, ey - self.INV_MARGIN
        cx, cy = (sx + ex) / 2, (sy + ey) / 2
        recent = getattr(self, "_inv_recent", None)
        if recent is None:
            recent = self._inv_recent = []
        pt = (int(cx), int(cy))
        for _ in range(40):
            pt = (int(round(min(ex, max(sx, random.gauss(cx, (ex - sx) / 4))))),
                  int(round(min(ey, max(sy, random.gauss(cy, (ey - sy) / 4))))))
            if all(abs(pt[0] - q[0]) + abs(pt[1] - q[1]) >= self.INV_MIN_DIST for q in recent):
                break
        recent.append(pt)
        del recent[:-8]
        return pt

    def click_inv(self, m, **kw) -> None:
        """Click an inventory item at a fresh random spot of its slot (speed varies per move)."""
        self.client.click(self.inv_point(m), **kw)

    def move_inv(self, m) -> None:
        self.client.move_to(self.inv_point(m))

    # ------------------------------------------------------------ quick / double clicks
    def quick_click(self, target, **kw) -> bool:
        """A click without the mouse-over check; with double_click_chance it clicks a
        second time fast on the same spot (like an impatient player). True = doubled."""
        double = random.random() < float(_v(self.cfg, "double_click_chance", 0) or 0)
        if double:
            interval = random.uniform(*_v(self.cfg, "double_click_gap", (0.08, 0.16)))
            self.client.click(target, click_cnt=2, min_click_interval=interval, **kw)
        else:
            self.client.click(target, **kw)
        return double

    def double_press(self) -> bool:
        """After a raw press(): with double_click_chance a second fast press, same spot."""
        if random.random() >= float(_v(self.cfg, "double_click_chance", 0) or 0):
            return False
        from core.input.mouse_control import press
        lo, hi = _v(self.cfg, "double_click_gap", (0.08, 0.16))
        time.sleep(random.uniform(lo, hi))
        press()
        return True

    # ------------------------------------------------------------ status
    def set_activity(self, what: str) -> None:
        self.activity = what

    def count(self, key: str, n: int = 1) -> None:
        self.counts[key] = self.counts.get(key, 0) + n
