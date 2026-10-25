"""Where the character stands, read from the World Location plugin (RuneLite Plugin Hub,
"world-location" by Skretzo) "Grid Info" panel in the top-left of the game view:

    Tile        3166, 3416, 0
    Chunk ID    809387
    Region ID   12597

The digits are drawn in white in RuneLite's small font, pixel-exact, so they are read by
comparing each glyph with fixed bitmaps (taken from a fleet screenshot, Oct 2026) - no
Tesseract. The region ID / chunk ID lines double as a checksum of the tile line.

The launcher installs and turns on the plugin for the bots (bot_rl_settings).
"""
from __future__ import annotations

import numpy as np

# '#' = white pixel; rows joined by '/'; trimmed to the glyph's own box
_GLYPHS = {
    ',': '##/.#/.#/#.',
    '0': '..##../.#..#./#..#.#/#..#.#/#..#.#/#.#..#/#.#..#/#.#..#/.#..#./..##..',
    '1': '..#../.##../#.#../..#../..#../..#../..#../..#../..#../#####',
    '2': '.###../#...#./.....#/.....#/....#./...#../..#.../.#..../#...../######',
    '3': '.###./#...#/....#/....#/.###./....#/....#/....#/#...#/.###.',
    '4': '#...../#...../#...../#...../#..#../#..#../#..#../######/...#../...#..',
    '5': '#####/#..../#..../###../...#./....#/....#/....#/#...#/.###.',
    '6': '..##../.#..#./#...../#...../#.##../##..#./#....#/#....#/.#..#./..##..',
    '7': '#####/....#/...#./...#./..#../..#../.#.../.#.../#..../#....',
    '8': '..##../.#..#./#....#/.#..#./..##../.#..#./#....#/#....#/.#..#./..##..',
    '9': '.####./#....#/#....#/#....#/.#...#/..####/.....#/.....#/.....#/.....#',
}
_TPL = {ch: np.array([[c == '#' for c in row] for row in s.split('/')], dtype=bool)
        for ch, s in _GLYPHS.items()}

SEARCH = (0, 0, 420, 330)  # window area where the top-left overlays sit (they stack)
WHITE_MIN = 200            # text pixels: every channel >= this (shadow is black)
WORD_GAP = 10              # px: the label and the numbers are ~25 px apart, digits 1-5


def _classify(g: np.ndarray) -> str | None:
    """One glyph (bool array trimmed to its box) -> character, or None."""
    h, w = g.shape
    if h <= 4 and w <= 3:
        return ','
    best, best_d = None, 4  # at most 3 wrong pixels
    for ch, t in _TPL.items():
        if ch == ',' or t.shape != g.shape:
            continue
        d = int((t != g).sum())
        if d < best_d:
            best, best_d = ch, d
    return best


def _bands(w: np.ndarray) -> list[tuple[int, int]]:
    """Rows that hold text, as (top, bottom) runs 8-14 px tall."""
    rows = w.sum(axis=1) >= 3
    out, y = [], 0
    while y < len(rows):
        if rows[y]:
            e = y
            while e < len(rows) and rows[e]:
                e += 1
            if 8 <= e - y <= 14:
                out.append((y, e))
            y = e
        else:
            y += 1
    return out


def _number_text(b: np.ndarray) -> str | None:
    """The right-most word of a text band (the numbers), as text; None if unreadable."""
    cols = b.any(axis=0)
    xs = np.nonzero(cols)[0]
    if not len(xs):
        return None
    # glyph runs from the right edge, stopping at the big gap before the label
    runs, x = [], xs[-1]
    while x >= 0:
        if cols[x]:
            e = x
            while x >= 0 and cols[x]:
                x -= 1
            runs.append((x + 1, e + 1))
        else:
            gap_start = x
            while x >= 0 and not cols[x]:
                x -= 1
            if gap_start - x >= WORD_GAP:
                break
    text = ''
    for s, e in reversed(runs):
        g = b[:, s:e]
        r = np.nonzero(g.any(axis=1))[0]
        ch = _classify(g[r[0]:r[-1] + 1])
        if ch is None:
            return None
        text += ch
    return text


def read_tile(sc) -> tuple[int, int, int] | None:
    """(x, y, plane) of the character from a window screenshot, or None when the panel
    isn't there / can't be read / fails its checksum."""
    a = np.asarray(sc.convert('RGB').crop(SEARCH), dtype=np.uint8)
    w = a.min(axis=2) >= WHITE_MIN
    bands = _bands(w)
    texts = [_number_text(w[y0:y1]) for y0, y1 in bands]
    for i, t in enumerate(texts):
        if not t or t.count(',') != 2:
            continue
        try:
            x, y, z = (int(p) for p in t.split(','))
        except ValueError:
            continue
        if not (1000 <= x <= 4500 and 1000 <= y <= 13000 and 0 <= z <= 3):
            continue
        chunk = ((x >> 3) << 11) | (y >> 3)
        region = ((x >> 6) << 8) | (y >> 6)
        nxt = [n for n in texts[i + 1:i + 3] if n and n.isdigit()]
        if str(chunk) in nxt or str(region) in nxt:
            return x, y, z
    return None


# ---------------------------------------------------------------- compass (camera turn)
# The compass above the minimap turns with the camera exactly like the minimap. Matching
# it against a north-up picture (data/ui/compass-north.png, 40x40 around its centre) at
# every angle gives the turn - no clicks needed.
COMPASS_FROM_GLOBE = (-151, -98)  # compass centre - world-map orb top-left (measured)
# the character always sits at the minimap's centre: world-map orb top-left + this (measured
# from where walk clicks really took the character, Oct 2026: within ~2 px)
MINIMAP_FROM_GLOBE = (-70.5, -33.0)
_REF = None


def _ref():
    global _REF
    if _REF is None:
        from PIL import Image
        _REF = np.asarray(Image.open('data/ui/compass-north.png').convert('L'), dtype=np.float32)
    return _REF


def compass_yaw(sc, centre) -> tuple[float, float]:
    """(turn in degrees clockwise: 0 = north up, 90 = north points right, match score).
    `centre` = the compass centre in window coords."""
    import cv2
    ref = _ref()
    cx, cy = int(round(centre[0])), int(round(centre[1]))
    pad = 3  # tolerate a centre a few px off
    crop = np.asarray(sc.convert('L').crop((cx - 20 - pad, cy - 20 - pad, cx + 20 + pad, cy + 20 + pad)),
                      dtype=np.float32)
    h = 13  # half-size of the matched square (the dial face, radius ~15)

    def score(a):
        m = cv2.getRotationMatrix2D((19.5, 19.5), a, 1.0)
        rot = cv2.warpAffine(ref, m, (40, 40), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        tpl = rot[20 - h:20 + h, 20 - h:20 + h]
        return float(cv2.matchTemplate(crop, tpl, cv2.TM_CCOEFF_NORMED).max())

    best_a, best_s = 0.0, -2.0
    for a in range(0, 360, 4):
        s = score(a)
        if s > best_s:
            best_a, best_s = float(a), s
    for a in np.arange(best_a - 3, best_a + 3.01, 1.0):
        s = score(a)
        if s > best_s:
            best_a, best_s = float(a), s
    # cv2 turns counter-clockwise for positive angles: the compass turned clockwise by -a
    return (-best_a) % 360.0, best_s
