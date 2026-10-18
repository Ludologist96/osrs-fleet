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
