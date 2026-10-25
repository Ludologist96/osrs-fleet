"""Words on the game screen with their boxes (Tesseract, RuneScape fonts), in RuneLite
window coordinates. Used to find buttons and settings by their text (All Settings, the
settings search results) instead of fixed pixel positions."""
from __future__ import annotations

import pytesseract
from PIL import Image

from core.ocr import tess
from core.ocr.enums import FontChoice

SCALE = 3  # tess._preprocess upscales 3x


def words(sc: Image.Image, box=None, psm: int = 11, min_conf: float = 30.0) -> list[dict]:
    """[{text, x1, y1, x2, y2, conf, line}] for every word Tesseract reads in `box`
    (window coords; whole screenshot when None)."""
    x0, y0 = 0, 0
    img = sc.convert("RGB")
    if box:
        x0, y0 = int(box[0]), int(box[1])
        img = img.crop(tuple(int(v) for v in box))
    pre = tess._preprocess(img)
    lang = f"{FontChoice.RUNESCAPE.value}+{FontChoice.RUNESCAPE_BOLD.value}+{FontChoice.RUNESCAPE_SMALL.value}"
    d = pytesseract.image_to_data(pre, lang=lang, config=f"--psm {psm}",
                                  output_type=pytesseract.Output.DICT, timeout=10)
    out = []
    for i, t in enumerate(d["text"]):
        t = (t or "").strip()
        try:
            conf = float(d["conf"][i])
        except (TypeError, ValueError):
            conf = -1.0
        if not t or conf < min_conf:
            continue
        x, y, w, h = d["left"][i], d["top"][i], d["width"][i], d["height"][i]
        out.append({"text": t, "conf": round(conf, 1),
                    "x1": x0 + x // SCALE, "y1": y0 + y // SCALE,
                    "x2": x0 + (x + w) // SCALE, "y2": y0 + (y + h) // SCALE,
                    "line": f'{d["block_num"][i]}.{d["par_num"][i]}.{d["line_num"][i]}'})
    return out


def lines(ws: list[dict]) -> list[dict]:
    """Words joined into lines: [{text, x1, y1, x2, y2, words}]."""
    by = {}
    for w in ws:
        by.setdefault(w["line"], []).append(w)
    out = []
    for group in by.values():
        group.sort(key=lambda w: w["x1"])
        out.append({"text": " ".join(w["text"] for w in group),
                    "x1": min(w["x1"] for w in group), "y1": min(w["y1"] for w in group),
                    "x2": max(w["x2"] for w in group), "y2": max(w["y2"] for w in group),
                    "words": group})
    out.sort(key=lambda l: (l["y1"], l["x1"]))
    return out


def find_line(sc: Image.Image, phrase: str, box=None, min_ratio: float = 0.75):
    """The line that best matches `phrase` (case-insensitive, fuzzy), or None:
    {text, x1, y1, x2, y2, ratio}."""
    from difflib import SequenceMatcher
    want = phrase.lower()
    best, best_r = None, 0.0
    for ln in lines(words(sc, box)):
        t = ln["text"].lower()
        r = SequenceMatcher(None, t, want).ratio()
        if want in t:
            r = max(r, 0.95)
        if r > best_r:
            best, best_r = ln, r
    if best is None or best_r < min_ratio:
        return None
    best = dict(best)
    best["ratio"] = round(best_r, 3)
    return best
