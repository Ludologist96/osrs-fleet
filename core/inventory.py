"""
Inventory slots by position (RuneLite fixed layout), independent of item icons.

Slot (col, row) top-left on the game canvas = ORIGIN + (col*42, row*36), 36x32 px.
An empty slot is plain, even brown; an item has outlines and colour, so its
brightness varies a lot. Lets bots see "inventory full" whatever the items are.
"""

from __future__ import annotations

from PIL import Image

from core.region_match import MatchResult

ORIGIN = (563, 213)
STEP = (42, 36)
SLOT = (36, 32)
ITEM_STDDEV = 14  # brightness spread above this = something in the slot


def slots(sc: Image.Image) -> list[tuple[MatchResult, float]]:
    """All 28 slots (row by row) as (rect, brightness spread)."""
    gray = sc.convert("L")
    out = []
    for row in range(7):
        for col in range(4):
            x, y = ORIGIN[0] + col * STEP[0], ORIGIN[1] + row * STEP[1]
            px = list(gray.crop((x + 4, y + 4, x + SLOT[0] - 4, y + SLOT[1] - 4)).getdata())
            mean = sum(px) / len(px)
            sd = (sum((v - mean) ** 2 for v in px) / len(px)) ** 0.5
            out.append((MatchResult(x, y, x + SLOT[0], y + SLOT[1]), sd))
    return out


def used_slots(sc: Image.Image) -> list[MatchResult]:
    return [r for r, sd in slots(sc) if sd > ITEM_STDDEV]


def snapshot(sc: Image.Image):
    """Grayscale copy of the 28 slots, to compare later with changed_slots()."""
    x0, y0 = ORIGIN
    x1 = x0 + 3 * STEP[0] + SLOT[0]
    y1 = y0 + 6 * STEP[1] + SLOT[1]
    return sc.convert("L").crop((x0, y0, x1, y1))


def changed_slots(before, sc: Image.Image, min_px: int = 6, diff: int = 40) -> list[int]:
    """Slots (0-27) whose pixels changed since snapshot `before`: a new item, a gone item,
    or a stack whose number changed (stackables like feathers don't fill a new slot)."""
    now = snapshot(sc)
    if before is None or now.size != before.size:
        return []
    a, b = before.load(), now.load()
    out = []
    for row in range(7):
        for col in range(4):
            x, y = col * STEP[0], row * STEP[1]
            n = 0
            for yy in range(y, y + SLOT[1], 1):
                for xx in range(x, x + SLOT[0], 1):
                    if abs(a[xx, yy] - b[xx, yy]) > diff:
                        n += 1
                        if n >= min_px:
                            break
                if n >= min_px:
                    break
            if n >= min_px:
                out.append(row * 4 + col)
    return out
