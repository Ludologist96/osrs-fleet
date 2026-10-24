"""
human_mouse.py  –  v1.1
"""
from __future__ import annotations
if __name__ == "__main__":
    import os,sys
    sys.path.append(
        os.path.abspath(
            os.path.join(
                os.path.dirname(__file__),
                "../.."
            )
        )
    )
import ctypes, math, random, sys, time
import pyautogui, keyboard
from core.logger import get_logger
from core.tools import MatchResult          # your class
from core.control import ScriptControl
from enum import Enum
from typing import Tuple

control = ScriptControl()
log = get_logger("MouseControl")

# ── multi-monitor-safe cursor I/O ───────────────────────────
# Background:
#  - pyautogui.moveTo() on Windows uses mouse_event() + MOUSEEVENTF_ABSOLUTE,
#    which normalizes 0..65535 coords against the *primary* monitor only.
#    Any target past the primary monitor's bounds is silently clamped to
#    its edge — breaking bots on multi-monitor setups.
#  - Worse, when the Python process is DPI-Unaware (the default), GetCursorPos
#    (which pyautogui.position() uses) returns *DPI-virtualized* coordinates
#    that can also clamp to the primary monitor. That's the actual cause of
#    the "Mouse off target by ... got Point(x=3439, ...)" warnings we saw:
#    the cursor may have moved correctly, but the read came back clamped.
#
# The fix uses the "Physical" Win32 APIs — they always operate in raw,
# non-virtualized pixel coordinates across the entire virtual desktop,
# regardless of the process's DPI awareness:
#   GetPhysicalCursorPos / SetPhysicalCursorPos
#
# We also keep a SendInput(VIRTUALDESK) fallback for environments where the
# Physical APIs aren't available (RDP sessions sometimes block them).
if sys.platform == "win32":
    from ctypes import wintypes

    _user32 = ctypes.windll.user32

    # Best-effort: also opt into per-monitor DPI awareness. This doesn't gate
    # the Physical APIs (they work either way) but it makes pyautogui.position()
    # and pygetwindow rectangles consistent if anything else in the process
    # reads them. Logged once for diagnostics.
    _dpi_status = "unchanged"
    try:
        if _user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            _dpi_status = "per-monitor-v2"
        else:
            raise OSError("SetProcessDpiAwarenessContext returned 0")
    except Exception:
        try:
            hr = ctypes.windll.shcore.SetProcessDpiAwareness(2)
            _dpi_status = "per-monitor" if hr == 0 else f"shcore-hr={hr}"
        except Exception as exc:
            _dpi_status = f"failed ({exc})"

    # SendInput plumbing (used only as fallback for the Physical APIs).
    _INPUT_MOUSE = 0
    _MOUSEEVENTF_MOVE = 0x0001
    _MOUSEEVENTF_ABSOLUTE = 0x8000
    _MOUSEEVENTF_VIRTUALDESK = 0x4000
    _SM_XVIRTUALSCREEN = 76
    _SM_YVIRTUALSCREEN = 77
    _SM_CXVIRTUALSCREEN = 78
    _SM_CYVIRTUALSCREEN = 79

    class _MOUSEINPUT(ctypes.Structure):
        _fields_ = [
            ("dx", wintypes.LONG),
            ("dy", wintypes.LONG),
            ("mouseData", wintypes.DWORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ctypes.c_void_p),
        ]

    class _INPUT_UNION(ctypes.Union):
        _fields_ = [("mi", _MOUSEINPUT)]

    class _INPUT(ctypes.Structure):
        _anonymous_ = ("u",)
        _fields_ = [("type", wintypes.DWORD), ("u", _INPUT_UNION)]

    _user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(_INPUT), ctypes.c_int)
    _user32.SendInput.restype = wintypes.UINT
    _user32.GetPhysicalCursorPos.argtypes = (ctypes.POINTER(wintypes.POINT),)
    _user32.GetPhysicalCursorPos.restype = wintypes.BOOL
    _user32.SetPhysicalCursorPos.argtypes = (ctypes.c_int, ctypes.c_int)
    _user32.SetPhysicalCursorPos.restype = wintypes.BOOL

    def _send_input_move(x: int, y: int) -> bool:
        """Fallback move via SendInput with VIRTUALDESK normalization."""
        vs_x = _user32.GetSystemMetrics(_SM_XVIRTUALSCREEN)
        vs_y = _user32.GetSystemMetrics(_SM_YVIRTUALSCREEN)
        vs_w = _user32.GetSystemMetrics(_SM_CXVIRTUALSCREEN)
        vs_h = _user32.GetSystemMetrics(_SM_CYVIRTUALSCREEN)
        if vs_w <= 1 or vs_h <= 1:
            return bool(_user32.SetCursorPos(int(x), int(y)))

        nx = ((int(x) - vs_x) * 65535 + (vs_w - 1) // 2) // (vs_w - 1)
        ny = ((int(y) - vs_y) * 65535 + (vs_h - 1) // 2) // (vs_h - 1)

        mi = _MOUSEINPUT(
            dx=nx, dy=ny, mouseData=0,
            dwFlags=_MOUSEEVENTF_MOVE | _MOUSEEVENTF_ABSOLUTE | _MOUSEEVENTF_VIRTUALDESK,
            time=0, dwExtraInfo=None,
        )
        inp = _INPUT(type=_INPUT_MOUSE)
        inp.mi = mi
        return _user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT)) == 1

    def _set_cursor(x: int, y: int) -> None:
        """Move the OS cursor to absolute (x, y) on the virtual desktop.
        Uses SetPhysicalCursorPos (DPI-virtualization-immune); falls back to
        SendInput(VIRTUALDESK), then to SetCursorPos."""
        ix, iy = int(x), int(y)
        if _user32.SetPhysicalCursorPos(ix, iy):
            return
        if _send_input_move(ix, iy):
            return
        _user32.SetCursorPos(ix, iy)

    def _get_cursor() -> Tuple[int, int]:
        """Read OS cursor position in physical (non-virtualized) coords."""
        pt = wintypes.POINT()
        if _user32.GetPhysicalCursorPos(ctypes.byref(pt)):
            return (pt.x, pt.y)
        # Fallback for sessions where the Physical API is blocked.
        if _user32.GetCursorPos(ctypes.byref(pt)):
            return (pt.x, pt.y)
        return pyautogui.position()

    log.info(
        f"Cursor I/O initialized (DPI: {_dpi_status}, "
        f"virtual desktop: "
        f"{_user32.GetSystemMetrics(_SM_XVIRTUALSCREEN)},"
        f"{_user32.GetSystemMetrics(_SM_YVIRTUALSCREEN)} "
        f"{_user32.GetSystemMetrics(_SM_CXVIRTUALSCREEN)}x"
        f"{_user32.GetSystemMetrics(_SM_CYVIRTUALSCREEN)})"
    )
else:
    def _set_cursor(x: int, y: int) -> None:
        pyautogui.moveTo(int(x), int(y), _pause=0)

    def _get_cursor() -> Tuple[int, int]:
        return tuple(pyautogui.position())

class ClickType(Enum):
    LEFT = 1
    RIGHT = 2
    MIDDLE = 3

# ── global knobs ───────────────────────────────────────────
#user32              = ctypes.windll.user32
terminate           = False          # Esc listener toggles this
movement_multiplier = 0.45           # lower = faster (was 0.5)
is_simulation = False

# ── helpers ────────────────────────────────────────────────
def _euclidean(p1, p2):    return math.hypot(p2[0]-p1[0], p2[1]-p1[1])
def _lerp(a,b,t):          return a + (b-a)*t
def _bezier(p0,p1,p2,t):
    return (_lerp(_lerp(p0[0],p1[0],t), _lerp(p1[0],p2[0],t), t),
            _lerp(_lerp(p0[1],p1[1],t), _lerp(p1[1],p2[1],t), t))
def _smooth_steps(total, n):
    return [total*(3*(i/n)**2 - 2*(i/n)**3) for i in range(1,n+1)]
def _block(on=True):  pass     #user32.BlockInput(bool(on))

def _get_direction(p1: Tuple[int, int],
                  p2: Tuple[int, int]):
    dx = p2[0] - p1[0]
    dy = p2[1] - p1[1]
    angle_rad = math.atan2(dy, dx)         # range (-π, π]
    angle_deg = math.degrees(angle_rad)    # range (-180, 180]
    return (angle_deg + 360) % 360         # → range [0, 360)
# ───────────────────────────────────────────────────────────────
#  Angle helpers  (screen-coords convention: 0° = →, 90° = ↓)
# ───────────────────────────────────────────────────────────────
def _norm(a: float) -> float:
    """Normalise angle to [0, 360)."""
    return a % 360

def _angle_diff(a: float, b: float) -> float:
    """
    Smallest signed difference a→b (deg, –180‥+180].
    Positive ⇒ b is clockwise from a.
    """
    d = (b - a + 180) % 360 - 180
    return d if d != -180 else 180

def _polar_to_xy(angle_deg: float, r: float) -> Tuple[float, float]:
    """Convert polar (screen coords) → Δx, Δy (y grows downward)."""
    rad = math.radians(angle_deg)
    return r * math.cos(rad), r * math.sin(rad)


def _constrain_travel(p1: Tuple[float, float],
                     p2: Tuple[float, float],
                     tp: Tuple[float, float],
                     max_variance: float = 45
                     ) -> Tuple[float, float]:
    """
    Constrain the step p1→p2 so its heading is no farther than
    `max_variance` degrees from the direction toward the long-term
    target point `tp`.

    Parameters
    ----------
    p1 : (x, y)
        Current position.
    p2 : (x, y)
        Proposed next position.
    tp : (x, y)
        Final target point we ultimately want to reach.
    max_variance : float, default 45
        Allowed deviation (±) from the `p1→tp` heading.

    Returns
    -------
    (x, y)
        New next position, keeping the same step length as p1→p2
        but adjusted to satisfy the angle constraint.
    """
    dx, dy = p2[0] - p1[0], p2[1] - p1[1]
    dist   = math.hypot(dx, dy)
    if dist == 0:
        return p2                       # no movement → nothing to adjust

    cur_dir = _norm(math.degrees(math.atan2(dy, dx)))
    tgt_dir = _norm(math.degrees(math.atan2(tp[1] - p1[1], tp[0] - p1[0])))
    delta   = _angle_diff(tgt_dir, cur_dir)

    # Inside the cone? keep original p2
    if abs(delta) <= max_variance:
        return p2

    # Clamp to the closest boundary of the cone centred on target heading
    new_dir = tgt_dir + (max_variance if delta > 0 else -max_variance)
    new_dx, new_dy = _polar_to_xy(_norm(new_dir), dist)
    return p1[0] + new_dx, p1[1] + new_dy

# ── click helpers (unchanged API) ──────────────────────────
@control.guard
def hold_time() -> float:
    """How long a person keeps a mouse button down for a click: mostly 60-130 ms,
    sometimes quicker or slower (log-normal), never a 0 ms machine click."""
    return min(0.25, max(0.035, random.lognormvariate(math.log(0.085), 0.3)))


def press(click_type: "ClickType" = None) -> None:
    """One click at the current cursor position with a human hold time.
    (pyautogui.click() presses and releases in the same instant.)"""
    click_type = click_type or ClickType.LEFT
    button = {ClickType.LEFT: "left", ClickType.RIGHT: "right",
              ClickType.MIDDLE: "middle"}.get(click_type, "left")
    pyautogui.mouseDown(button=button, _pause=False)
    try:
        time.sleep(hold_time())
    finally:
        pyautogui.mouseUp(button=button, _pause=False)


def click(
        x=-1, y=-1, 
        click_type=ClickType.LEFT,
    click_cnt=1, min_click_interval=.3,
    verify: bool = True,
    verify_tolerance: int = 3,
    verify_corrections: int = 2):
    def _do_click():
        time.sleep(random.uniform(.05, .15))  # settle before pressing
        press(click_type)

    _block(True)
    try:
        is_already_there = _get_cursor() == (x, y)
        if x >= 0 and y >= 0 and not is_already_there:
            move_to(x, y)

        # Optional verification & correction before first click
        if verify and x >= 0 and y >= 0:
            _verify_position((x, y), tolerance=verify_tolerance, corrections=verify_corrections)

        _do_click()
        for idx in range(click_cnt-1):
            time.sleep(random.uniform(min_click_interval, min_click_interval*1.4))
            if verify and x >= 0 and y >= 0:
                _verify_position((x, y), tolerance=verify_tolerance, corrections=verify_corrections)
            _do_click()
    finally:
        _block(False)

    
    
    

    

def move_to_match(match: MatchResult, **kw):
    _block(True)
    try:  move_to(*match.get_point_within(), **kw)
    finally:  _block(False)

def click_in_match(
        match: MatchResult, click_cnt=1, 
        min_click_interval=.3, click_type=ClickType.LEFT
    ):
    
    x, y = match.get_point_within()
    click(x, y, click_type, click_cnt, min_click_interval)



# ────────────────────────────────────────────────────────────────
#  Human-like MOVE TO  (overshoot + distance-weighted wobble)
# ────────────────────────────────────────────────────────────────
@control.guard
def move_to(
    tx: int,
    ty: int,
    overshoot_prob: float = .40,
    wobble_prob:   float = .8,
    pause_prob:    float = .18,
    curve_prob:    float = .6,      # kept for callers; every move is a curve now
    overshoot_ratio=(.04, .1),
    wobble_px=(-1, -1),
    curve_ratio=(.01, .25),         # kept for callers
    pause_max_ms=250,
    speed: float | None = None,
    max_direction_change=30,        # kept for callers
    verify_at_end: bool = True,
    verify_tolerance: int = 3,
    verify_corrections: int = 2
):
    """Human-like cursor travel along cubic Bezier curves.

    Every move is ONE smooth curve from the cursor to the target (a gentle arc, sometimes
    an S), never a straight line or joined segments with corners. With overshoot_prob the
    curve ends a little past the target and a second, short curve comes back. The speed
    eases in and out, varies per move, and a little hand tremor is added on the way."""
    if terminate:
        return

    sx, sy = _get_cursor()
    dist0 = _euclidean((sx, sy), (tx, ty))
    if dist0 < 1:
        return

    # one speed for this whole move (some moves quick, some lazy)
    move_speed_factor = min(1.8, max(0.6, random.lognormvariate(0, 0.28)))
    tremor = random.uniform(0.6, 2.2) if wobble_px == (-1, -1) else float(sum(wobble_px)) / 4

    legs = []
    if random.random() < overshoot_prob and dist0 > 40:
        ux, uy = (tx - sx) / dist0, (ty - sy) / dist0
        o_dist = min(40.0, dist0 * random.uniform(*overshoot_ratio))
        side = random.uniform(-0.4, 0.4) * o_dist            # a bit sideways too
        over = (tx + ux * o_dist - uy * side, ty + uy * o_dist + ux * side)
        legs.append(((sx, sy), over, True))
        legs.append((over, (tx, ty), False))
    else:
        legs.append(((sx, sy), (tx, ty), True))

    _block(True)
    try:
        for leg_idx, (p0, p3, main) in enumerate(legs):
            seg = _euclidean(p0, p3)
            if seg < 1:
                continue
            c1, c2 = _curve_controls(p0, p3, main)

            # timing: same baseline as before, eased in and out
            if speed is not None:
                dur = seg / speed
            else:
                dur = max(0.05, min((seg / 700) * movement_multiplier, 0.5))
            dur = max(0.1 if main else 0.06, dur) * move_speed_factor
            steps = max(8, int(seg / 6), int(dur * 60))
            t_stamps = _smooth_steps(dur, steps)
            start = time.perf_counter()
            nx, ny = -(p3[1] - p0[1]) / seg, (p3[0] - p0[0]) / seg  # unit normal
            phase = random.uniform(0, 6.283)
            for i, tgt_t in enumerate(t_stamps, 1):
                if terminate:
                    return
                frac = i / steps
                x, y = _bezier3(p0, c1, c2, p3, frac)
                # hand tremor: small, smooth, fading out near the end of the move
                if wobble_prob > 0 and i < steps:
                    amp = tremor * (1 - frac) ** 1.5
                    w = amp * math.sin(phase + frac * random.uniform(9, 14))
                    x, y = x + nx * w, y + ny * w
                _set_cursor(int(round(x)), int(round(y)))
                if is_simulation:
                    continue
                # occasional micro-pause around the middle of the main curve
                if (pause_prob > 0 and leg_idx == 0 and .45 < frac < .55
                        and random.random() < .10):
                    time.sleep(random.uniform(.03, pause_max_ms / 1000))
                sleep_time = max(0, tgt_t - (time.perf_counter() - start))
                time.sleep(min(sleep_time, 0.1))
            if leg_idx < len(legs) - 1 and not is_simulation:
                time.sleep(random.uniform(0.02, 0.09))  # notice the overshoot, come back
    finally:
        try:
            if verify_at_end:
                _verify_position((tx, ty), tolerance=verify_tolerance, corrections=verify_corrections)
        except Exception as e:
            log.error(f"Mouse position verification raised unexpected error: {e}")
        _block(False)


def _bezier3(p0, p1, p2, p3, t):
    u = 1 - t
    a, b, c, d = u * u * u, 3 * u * u * t, 3 * u * t * t, t * t * t
    return (a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0],
            a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1])


def _curve_controls(p0, p3, main: bool = True):
    """Two control points for a natural arc between p0 and p3: bent to one side by
    5-25% of the distance (short moves bend less), sometimes an S-curve."""
    dx, dy = p3[0] - p0[0], p3[1] - p0[1]
    dist = math.hypot(dx, dy) or 1.0
    nx, ny = -dy / dist, dx / dist
    if main:
        bend = dist * (random.uniform(0.05, 0.25) if dist > 60 else random.uniform(0.04, 0.15))
    else:
        bend = dist * random.uniform(0.05, 0.3)       # the small way back after an overshoot
    side = random.choice((-1, 1))
    b1 = bend * side * random.uniform(0.7, 1.3)
    b2 = bend * side * random.uniform(0.5, 1.2)
    if main and random.random() < 0.2:
        b2 = -b2 * random.uniform(0.4, 0.8)          # S-curve
    t1, t2 = random.uniform(0.2, 0.4), random.uniform(0.6, 0.8)
    c1 = (p0[0] + dx * t1 + nx * b1, p0[1] + dy * t1 + ny * b1)
    c2 = (p0[0] + dx * t2 + nx * b2, p0[1] + dy * t2 + ny * b2)
    return c1, c2


def _small_curve(target: tuple[int, int], dur: float = 0.06) -> None:
    """A tiny curved correction move (instead of jumping the cursor)."""
    p0 = _get_cursor()
    seg = _euclidean(p0, target)
    if seg < 1:
        return
    c1, c2 = _curve_controls(p0, target, main=False)
    steps = max(4, int(seg / 3))
    for i in range(1, steps + 1):
        x, y = _bezier3(p0, c1, c2, target, i / steps)
        _set_cursor(int(round(x)), int(round(y)))
        time.sleep(dur / steps)


def _verify_position(target: tuple[int,int], tolerance: int = 3, corrections: int = 2) -> bool:
    """Ensure the physical cursor is within tolerance of target.

    Attempts lightweight corrective moves if outside tolerance.
    Returns True if within tolerance after any corrections, else False.
    """
    try:
        curr = _get_cursor()
    except Exception as e:
        log.error(f"Unable to read mouse position for verification: {e}")
        return False

    dist = _euclidean(curr, target)
    if dist <= tolerance:
        #log.debug(f"Mouse on target {target} (Δ={dist:.1f}px ≤ {tolerance})")
        return True

    for attempt in range(1, corrections+1):
        log.warning(f"Mouse off target by {dist:.1f}px (expected {target}, got {curr}); correcting (attempt {attempt}/{corrections})")
        try:
            # small correction along a short curve (no jump), then exactly on target
            _small_curve(target, random.uniform(0.03, 0.08))
            _set_cursor(target[0], target[1])
            time.sleep(random.uniform(0.008, 0.02))
        except Exception as e:
            log.error(f"Correction attempt {attempt} failed: {e}")
            break
        try:
            curr = _get_cursor()
        except Exception as e:
            log.error(f"Failed to read mouse after correction: {e}")
            break
        dist = _euclidean(curr, target)
        if dist <= tolerance:
            log.info(f"Mouse corrected to target {target} after {attempt} attempt(s) (Δ={dist:.1f}px)")
            return True

    # Final state
    log.error(f"Mouse failed to reach target {target}; final position {curr} (Δ={dist:.1f}px > {tolerance})")
    return False

# ────────────────────────────────────────────────────────────────
#  RANDOM DOUBLE-CLICK  (unchanged)
# ────────────────────────────────────────────────────────────────
def random_double_click(x, y, variance=5, **move_kw):
    if terminate:
        return
    _block(True)
    try:
        pyautogui.mouseUp()
        tx = x + random.randint(-variance, variance)
        ty = y + random.randint(-variance, variance)
        move_to(tx, ty, **move_kw)     # primary travel
        press()
        time.sleep(random.uniform(.12, .35))
        move_to(tx, ty, overshoot_prob=0)  # settle
        press()
    finally:
        _block(False)

# ────────────────────────────────────────────────────────────────
#  LIGHTWEIGHT VISUAL SIMULATOR  (run with  `--sim`)
# ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse, sys
    parser = argparse.ArgumentParser()
    parser.add_argument("--sim", action="store_true", help="run visual path demo")
    args = parser.parse_args()

    if not args.sim:
        sys.exit(0)

    is_simulation = True

    # --- sim deps kept optional so production imports stay lean -----
    from PIL import Image, ImageDraw, ImageColor
    import numpy as np

    W = H = 1000
    STARTS = [
        (int(W//20), int(W//20)),
        (H-int(H//20), int(W//20)),
        (int(H//20), W-int(W//20)),
        (H-int(H//20), W-int(W//20)),
        
        (int(H//20), int(W//2)),
        (H-int(H//20), int(W//2)),
        (int(W/2), int(W//20)),
        (int(W/2), H-int(W//20))
    ]
    TARGET = (W // 2, H // 2)

    def simulate(sim_cnt=1):
        global pyautogui
        img = Image.new("RGB", (W, H), (30, 30, 30))
        draw = ImageDraw.Draw(img)
        draw.rectangle([TARGET[0] - 7, TARGET[1] - 7, TARGET[0] + 7, TARGET[1] + 7],
                    outline="white", width=2)
        
        # stub-pyautogui for off-screen drawing
        class _StubAG:
            _pos = (0,0)
            _color = (255,0,0)
            @classmethod
            def position(cls):
                return tuple(cls._pos)
            @classmethod
            def moveTo(cls, x, y, _pause=0):
                draw.line([cls._pos, (x, y)], fill=cls._color, width=1)
                #draw.rectangle([(x-1,y-1),(x+1,y+1)],"blue")
                cls._pos = [x, y]
        pyautogui = _StubAG  # type: ignore
        for start in STARTS:
            
            draw.rectangle([start[0] - 10, start[1] - 10, start[0] + 10, start[1] + 10],
                    fill="cyan")
            for seed in range(sim_cnt):
                pyautogui._pos = start
                # random.seed(seed); np.random.seed(seed)

                move_to(
                    *TARGET,
                    pause_prob=0,
                    overshoot_prob=.4
                )

        img.show()          # opens default viewer; close it to end sim
    
    simulate(1)
    # simulate(10)
    # simulate(100)
    # simulate(1000)