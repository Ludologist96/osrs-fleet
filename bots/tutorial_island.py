"""
Tutorial Island bot - plays the tutorial from the character design screen to the mainland.

Igor names the character himself; the bot takes over from the appearance screen
("Setting your appearance") and stops once the character stands in Lumbridge.

How it knows what to do: the game itself says it. The tutorial's instruction box in
the chat area ("Fishing", "Woodcutting", "Smelting"... with a short text) is read with
OCR every step and matched against a list of rules (RULES below, texts from the OSRS
wiki transcript). Each rule is a small action:

  - talk to an instructor  -> NPC Indicators (the launcher highlights all tutorial NPCs
                              cyan), the click only lands when the mouse-over says
                              "Talk-to <name>";
  - click a flashing tab   -> tab icon template, else the tab that flashes (pixels
                              change between two looks);
  - use an object          -> the game's yellow hint arrow above it, then a mouse-over
                              check ("Chop down Tree", "Open Door", "Mine Tin rocks"...);
                              no arrow: a mouse-over search around the character;
  - use an item on another -> inventory click (white "selected" outline checked on the
                              screen, as in the woodcutter), then the target;
  - dialogue               -> "Click here to continue" = space, "Select an Option" =
                              the number key of the wanted line (option_prefs).

After each action it waits until the instruction text changes (or a timeout) and
tries again; the same text for too long = a debug screenshot, the view reset, and
finally a stop with exit_reason "stuck".
Humanlike input as in every bot (R11): curved mouse moves, mouse-over checks,
random spots in inventory slots, short varied pauses, rare camera fidgets.
"""
from __future__ import annotations

import math
import random
import re
import time

import cv2
import numpy as np
from PIL import Image

from bots.core import BotConfigMixin
from bots.core.cfg_types import (
    BooleanParam, BreakCfgParam, FloatParam, IntParam, RangeParam, RGBParam, RGBListParam,
    StringListParam,
)
from core import inventory, tools
from core.bot import Bot
from core.camera import Camera, GAME_VIEW
from core.control import ScriptTerminationException
from core.human import HumanMixin
from core.input import keys as keyboard
from core.input.mouse_control import ClickType, click, press
from core.logger import get_logger
from core.region_match import MatchResult
from core.screen_words import lines, words, find_line


class BotConfig(BotConfigMixin):
    # --- what it sees ---
    # NPC Indicators hull colour (the launcher highlights the tutorial NPCs in it).
    npc_colors: RGBListParam = RGBListParam([RGBParam(0, 255, 255)])
    color_tolerance: IntParam = IntParam(40)
    min_npc_pixels: IntParam = IntParam(25)
    # The tutorial's hint arrow: yellow (hue), strongly coloured.
    hint_color: RGBParam = RGBParam(255, 255, 0)
    hint_hue_tol: IntParam = IntParam(8)
    hint_min_pixels: IntParam = IntParam(150)      # in the game view (arrow ~250 px)
    hint_min_pixels_minimap: IntParam = IntParam(40)  # minimap arrow (NPC dots are ~4 px)
    # How far below the arrow's tip the mouse-over search goes (px).
    hint_search_depth: IntParam = IntParam(110)

    # --- dialogue: options picked in this order (lower case, part of the line) ---
    option_prefs: StringListParam = StringListParam([
        "experienced player", "yes.", "not planning", "i'm not", "not to do", "i'm fine", "fine, thanks",
        "move on", "nope", "yes",
    ])
    # never picked (ironman modes)
    option_never: StringListParam = StringListParam([
        "iron",  # every ironman line ("Yes, I do want to become an Ironman", "Tell me about...")
    ])

    # --- pacing ---
    step_wait: FloatParam = FloatParam(25.0)        # s to wait for the instruction to change
    action_pause: RangeParam = RangeParam(0.35, 0.9)  # after a click
    read_every: RangeParam = RangeParam(0.9, 1.6)   # s between two looks while waiting
    continue_pause: RangeParam = RangeParam(0.45, 1.3)  # before pressing space in a dialogue
    max_same: IntParam = IntParam(8)               # tries on one instruction before "stuck"
    max_unknown: IntParam = IntParam(25)           # looks with no instruction/dialogue before "stuck"
    fight_timeout: FloatParam = FloatParam(90.0)
    hover_search_points: IntParam = IntParam(70)   # mouse-over search around the character

    # --- habits (small, it's a short run) ---
    camera_chance: FloatParam = FloatParam(0.04)   # after a finished step
    camera_rotate_time: RangeParam = RangeParam(0.3, 1.0)
    camera_zoom_chance: FloatParam = FloatParam(0.4)
    start_zoom_in: IntParam = IntParam(15)
    zoom_min: IntParam = IntParam(-4)
    zoom_max: IntParam = IntParam(3)
    misclick_chance: FloatParam = FloatParam(0.02)
    micro_idle_chance: FloatParam = FloatParam(0.10)
    micro_idle: RangeParam = RangeParam(0.3, 1.2)
    double_click_chance: FloatParam = FloatParam(0.0)
    break_cfg: BreakCfgParam = BreakCfgParam(RangeParam(8, 25), FloatParam(0.004))
    break_ui_browse_chance: FloatParam = FloatParam(0.0)
    session_max_minutes: IntParam = IntParam(0)
    # Save a screenshot whenever a step is retried (for tuning; off once it runs well).
    debug_shots: BooleanParam = BooleanParam(True)


# Fixed layout, window coords (= canvas coords on the fleet).
CHAT_BOX = (0, 338, 520, 476)
# never clicked even when the fuzzy match says yes ("Cast Minigame Teleport" ~ "Cast Home Teleport")
HOVER_NEVER = ("minigame",)
SIDE_PANEL = (548, 205, 740, 465)
TAB_ROWS = ((527, 168, 765, 204), (527, 466, 765, 502))  # 7 tabs of 34 px (measured)
TAB_W = 34
# (column, row) of each tab in the fixed layout (row 0 = top, 1 = bottom)
TAB_POS = {"combat": (0, 0), "skills": (1, 0), "quests": (2, 0), "inventory": (3, 0), "equipment": (4, 0),
           "prayer": (5, 0), "spells": (6, 0), "account": (2, 1), "friends": (1, 1), "logout": (3, 1),
           "settings": (4, 1), "emotes": (5, 1), "music": (6, 1)}
VIEW = (4, 4, 512, 334)  # game view
OVERLAY_BOX = (4, 22, 330, 160)
HOVER_LINE = (4, 4, 360, 24)
MINIMAP_C, MINIMAP_R = (652, 81), 70  # round minimap (fixed layout, measured)  # the game's mouse-over text, top-left of the view  # some instructions show in a dark box top-left of the view
# tab name -> template (data/ui) and words in the instruction that point to it
TABS = {
    "settings": ("data/ui/settings.webp", ("spanner", "settings")),
    "quests": ("data/ui/quests.webp", ("quest journal", "left of your inventory", "quest")),
    "inventory": ("data/ui/inventory.webp", ("backpack",)),
    "skills": ("data/ui/stats.webp", ("bar graph", "skills menu")),
    "equipment": ("data/ui/equipment.webp", ("icon of a man", "worn")),
    "combat": ("data/ui/combat.webp", ("crossed swords", "combat interface")),
    "account": ("data/ui/account.webp", ("account management",)),
    "prayer": ("data/ui/prayer.webp", ("prayer",)),
    "friends": ("data/ui/friends.webp", ("face icon", "friends")),
    "spells": ("data/ui/spellbook.webp", ("magic",)),
    "music": ("data/ui/music.webp", ("music",)),
    "emotes": ("data/ui/emotes.webp", ("emote",)),
}
NPCS = ["Gielinor Guide", "Survival Expert", "Master Chef", "Quest Guide", "Mining Instructor",
        "Combat Instructor", "Account Guide", "Brother Brace", "Magic Instructor"]
# instruction words -> the NPC to talk to
NPC_WORDS = [("gielinor guide", "Gielinor Guide"), ("survival", "Survival Expert"), ("surviv", "Survival Expert"),
             ("chef", "Master Chef"), ("quest guide", "Quest Guide"), ("quests", "Quest Guide"),
             ("mining instructor", "Mining Instructor"), ("combat", "Combat Instructor"),
             ("account", "Account Guide"), ("monk", "Brother Brace"), ("brother brace", "Brother Brace"),
             ("prayer", "Brother Brace"), ("magic", "Magic Instructor"), ("mainland", "Magic Instructor")]
# Tutorial Island (surface and the caves) in world tiles; outside = on the mainland.
ISLAND = ((3040, 3040, 3170, 3145), (3040, 9480, 3170, 9545))
HOVER_SIM = 0.72
HINT_ARROW = np.array([[c == "#" for c in row] for row in (
    "...........................",
    "...........................",
    "..........#######..........",
    "..........#######..........",
    "..........#######..........",
    "..........#######..........",
    "..........#######..........",
    "..........#######..........",
    "..........#######..........",
    "..........#######..........",
    "..........#######..........",
    "..........#######..........",
    "..........#######..........",
    "..........#######..........",
    "..........#######..........",
    "...#####################...",
    "....###################....",
    ".....#################.....",
    "......###############......",
    ".......#############.......",
    "........###########........",
    ".........#########.........",
    "..........#######..........",
    "...........#####...........",
    "............###............",
    "...........................",
)], dtype=np.float32)  # the hint arrow sprite
BAR_GREEN, BAR_RED, BAR_TOL = (0, 146, 54), (102, 15, 16), 30


def hue_mask(img: Image.Image, rgb, hue_tol: int = 8, min_sat: int = 150, min_val: int = 150) -> np.ndarray:
    hsv = cv2.cvtColor(np.asarray(img.convert("RGB")), cv2.COLOR_RGB2HSV)
    target = cv2.cvtColor(np.uint8([[list(rgb)]]), cv2.COLOR_RGB2HSV)[0, 0, 0]
    dh = np.abs(hsv[:, :, 0].astype(np.int16) - int(target))
    dh = np.minimum(dh, 180 - dh)
    return (dh <= hue_tol) & (hsv[:, :, 1] >= min_sat) & (hsv[:, :, 2] >= min_val)


def text_matches(text: str, wanted: str) -> bool:
    """OCR-tolerant mouse-over match; the verb and the name are checked separately.
    Verb '*' = the name anywhere in the text (e.g. 'Use Raw shrimps -> Fire')."""
    from difflib import SequenceMatcher
    text = (text or "").lower().strip()
    if not text:
        return False
    verb, _, name = wanted.lower().partition(" ")
    if verb.startswith("climb-"):
        # up and down must not be mixed up (a whole-text match would accept either)
        if ("down" in verb) != ("down" in text or "dawn" in text or "d0wn" in text):
            return False
    if re.search(r"\b[o0]ak\b", text) and "oak" not in wanted.lower():
        return False  # oak trees on the island need level 15 woodcutting
    if verb != "*" and "*" not in name and len(text) >= 6 and \
            SequenceMatcher(None, text[:len(wanted) + 3], wanted.lower()).ratio() >= 0.8:
        return True  # whole text close enough ("Nat Fishing spot" = "Net Fishing spot")
    if verb != "*":
        first = text.split(" ", 1)[0]
        if tools.text_similarity(first, verb) < HOVER_SIM and not text.startswith(verb):
            return False
        rest = text.split(" ", 1)[1] if " " in text else ""
        if verb in ("climb-up", "climb-down", "talk-to", "chop"):
            rest = text  # these verbs have their own words; look at all of it
    else:
        rest = text
    if not name or name == "*":
        return True
    if len(name) <= 4:
        return name in rest
    sim = max(tools.text_similarity(rest, name),
              max((SequenceMatcher(None, rest[i:i + len(name)], name).ratio()
                   for i in range(0, max(1, len(rest) - len(name) + 1))), default=0.0))
    return sim >= HOVER_SIM


def _norm(x: str) -> str:
    """Lower case with the letters OCR mixes up made the same (I/l/1/|, 0/o)."""
    x = x.lower()
    x = re.sub(r"[il1|!]", "l", x)
    x = x.replace("0", "o").replace("{", "i").replace("rn", "m")
    return re.sub(r"[^a-z ]", "", x)


def has(text: str, *keys: str) -> bool:
    """Any of `keys` in `text`, tolerating OCR letter mistakes (keys of 5+ letters
    match a same-length piece of the text at 80%; shorter ones must be there exactly,
    or "range" would match "change")."""
    from difflib import SequenceMatcher
    tn = _norm(text)
    for k in keys:
        kn = _norm(k)
        if kn in tn:
            return True
        if len(kn) >= 7 and len(tn) >= len(kn) - 1:
            n = len(kn)
            if len(tn) < n:
                if SequenceMatcher(None, tn, kn).ratio() >= 0.8:
                    return True
                continue
            for i in range(0, len(tn) - n + 1):
                if tn[i] != kn[0] and tn[i + n - 1:i + n] != kn[-1:]:
                    continue
                if SequenceMatcher(None, tn[i:i + n], kn).ratio() >= 0.8:
                    return True
    return False


class BotExecutor(HumanMixin, Bot):
    name: str = "Tutorial Island"
    description: str = "Plays Tutorial Island from the appearance screen to Lumbridge"
    tier: str = "C"
    instructions: str = """
    Create the account, log it in and pick the character's name yourself.
    Start this bot on the appearance screen (or anywhere on the island): it reads the
    tutorial's instructions and does them, then stops in Lumbridge.
    Start it from the fleet launcher so RuneLite highlights the tutorial NPCs
    (NPC Indicators) and shows the tile (World Location) and the opponent's health.
    """

    def __init__(self, config: BotConfig, user: str = ""):
        super().__init__(user, break_cfg=config.break_cfg,
                         break_ui_browse_chance=config.break_ui_browse_chance.value)
        self.cfg: BotConfig = config
        self.log = get_logger("TutorialIsland")
        self.camera = Camera(self.client, self.cfg.zoom_min.value, self.cfg.zoom_max.value,
                             self.cfg.start_zoom_in.value)
        self.exit_reason: str | None = None
        self.last_text = ""
        self.same = 0
        self.unknown = 0
        self.steps = 0
        self.walks = 0
        self._walked = False
        self._tpl: dict[str, Image.Image] = {}
        self._mainland_asked = False

    # The usual start view opens the inventory, which doesn't exist yet on the island.
    def _start_view(self):
        try:
            self.camera.top_down()
        except Exception:
            self.log.warning("Couldn't set the camera", exc_info=True)

    def watchdog(self, force: bool = False) -> bool:
        # The logged-in check looks for the full side panel; on the island most tabs are
        # hidden, so it would think we were logged out and click the login screen.
        return True

    # ================================================================== main loop
    def start(self):
        self.log.info("Starting Tutorial Island")
        # an arrow key left held down (a bot stopped in the middle of a camera turn) keeps
        # the camera spinning and every click misses: let go of them first
        for k in ("left", "right", "up", "down"):
            try:
                keyboard.release(k)
            except Exception:
                pass
        self.human_init()
        try:
            while not self.terminate:
                if self._done():
                    self.log.info("On the mainland: Tutorial Island done.")
                    self.exit_reason = "done"
                    self.counts["done"] = 1
                    return
                try:
                    res = self._step()
                    self.errors = 0
                except ScriptTerminationException:
                    raise
                except Exception:
                    self.errors = getattr(self, "errors", 0) + 1
                    self.log.error(f"Step error ({self.errors}/5)", exc_info=True)
                    if self.errors >= 5:
                        raise
                    time.sleep(2)
                    continue
                if res == "stop":
                    return
                self.control.propose_break()
        except ScriptTerminationException:
            self.log.info("Terminated by user")
        except Exception:
            self.log.error("Tutorial bot crashed", exc_info=True)
            self.save_debug_shot("tutorial-crash")
            raise
        finally:
            self.counts["steps"] = self.steps
            self.log.info(f"Stopped after {self.steps} steps")

    def _step(self):
        sc = self.client.get_screenshot()
        text = self.read_chat(sc)
        low = text.lower()
        # 1) a dialogue (covers the instruction box)
        if self._dialogue(low, sc):
            self.unknown = 0
            return
        if len(re.sub(r"[^a-z]", "", low)) < 18:
            low = ""  # just the chat input line ("Name: *") or OCR crumbs
        if not low.strip():
            # the appearance screen has no instruction box yet
            if self.unknown in (2, 6) and self._appearance(sc):
                return
            self.unknown += 1
            if self.unknown % 5 == 0:
                self.log.info(f"No instruction or dialogue seen ({self.unknown}/{self.cfg.max_unknown.value})")
                self._shot("no-text")
                self._close_interface()
            if self.unknown > self.cfg.max_unknown.value:
                self.log.error("Nothing readable for too long. Stopping.")
                self.exit_reason = "stuck"
                return "stop"
            time.sleep(self.cfg.read_every.choose())
            return
        self.unknown = 0
        key = self._key(low)
        if key == self.last_text:
            if getattr(self, "_walked", False) and self.walks < 40:
                self.walks += 1  # still on the way there: not a failed try
            else:
                self.same += 1
        else:
            self.walks = 0
            if self.last_text:
                self.steps += 1
                self.counts["steps"] = self.steps
                self._between_steps()
            self.log.info(f"Instruction: {text[:160]!r}")
            self.last_text, self.same = key, 0
        if self.same >= self.cfg.max_same.value:
            self.log.error(f"Same instruction after {self.same} tries. Stopping. ({text[:120]!r})")
            self._shot("stuck")
            self.exit_reason = "stuck"
            return "stop"
        if self.same and self.cfg.debug_shots.value:
            self._shot(f"retry{self.same}")
        if self.same in (3, 6):
            self.log.info("Resetting the view before trying again")
            self._close_interface()
            try:
                self.camera.random_move((0.6, 1.4), 0.3)
            except Exception:
                self.log.debug("camera move failed", exc_info=True)
        name, handler = self._rule(low)
        self.set_activity(name)
        self.log.info(f"Step '{name}' (try {self.same + 1})")
        self._walked = False
        if self._selected_any():
            self.log.info("An item was left selected: cancelling it")
            self._deselect()
        try:
            handler(low)
        except ScriptTerminationException:
            raise
        except Exception:
            self.log.warning(f"Step '{name}' failed", exc_info=True)
        # after a walk only a short look (then walk on); after an action wait for the result
        self._wait_change(key, 4.0 if self._walked else self.cfg.step_wait.value)

    def _key(self, low: str) -> str:
        """The instruction without OCR noise (for 'did it change?')."""
        return re.sub(r"[^a-z]", "", low)[:90]

    def _wait_change(self, key: str, timeout: float):
        end = time.time() + timeout
        while time.time() < end and not self.terminate:
            self.sleep_checked(self.cfg.read_every.choose())
            low = self.read_chat().lower()
            if not low.strip():
                continue
            if self._key(low) != key or self._is_dialogue(low):
                return

    def _between_steps(self):
        self.micro_idle()
        if random.random() < self.cfg.camera_chance.value:
            try:
                self.camera.random_move(self.cfg.camera_rotate_time.value, self.cfg.camera_zoom_chance.value)
            except Exception:
                self.log.debug("camera fidget failed", exc_info=True)

    # ================================================================== reading
    def read_chat(self, sc: Image.Image | None = None) -> str:
        """The current instruction or dialogue. Two places: the chat box (parchment box,
        NPC dialogue: dark text) and, for some steps ("Moving around"), a dark box in the
        top-left of the game view with yellow/white text. A dialogue in the chat box wins;
        otherwise the overlay when it has text, else the chat box."""
        sc = sc or self.client.get_screenshot()
        self._from_overlay = False
        chat = self._ocr_region(sc, self._chat_box(), "chat")
        self._chat_lines_box = getattr(self, "_lines_chat", [])
        self._chat_lines = self._chat_lines_box
        # the parchment instruction box has a blue title; when it's there it is the current
        # step (the top-left box can stay on an older, general text)
        a = np.asarray(sc.convert("RGB").crop((10, 340, 510, 400)), dtype=np.int16)
        blue = int(((a[:, :, 2] > 180) & (a[:, :, 0] < 80) & (a[:, :, 1] < 80)).sum())
        self._blue_title = blue >= 80
        if self._is_dialogue(chat.lower()):
            return chat
        if blue >= 80 and len(re.sub(r"[^a-z]", "", chat.lower())) >= 30:
            return chat
        self._ocr_region(sc, OVERLAY_BOX, "overlay")
        # the World Location panel (Tile / Chunk ID / Region ID, white) sits in the same
        # corner when there is no instruction box: drop its lines and number-only lines
        keep = [l for l in getattr(self, "_lines_overlay", [])
                if not has(l["text"], "chunk", "region", "tile")
                and len(re.sub(r"[^a-zA-Z]", "", l["text"])) >= 4]
        over = " ".join(l["text"] for l in keep)
        if len(re.sub(r"[^a-z]", "", over.lower())) >= 20:
            self._chat_lines = keep
            self._from_overlay = True
            return over
        return chat

    def _ocr_region(self, sc, box, kind: str) -> str:
        """One Tesseract pass over the text pixels only (Tesseract on the whole coloured box
        took >10 s on the laptop; this ~1.5 s). An unchanged region returns the last text."""
        crop = np.asarray(sc.convert("RGB").crop(box), dtype=np.int16)
        r, g, b = crop[:, :, 0], crop[:, :, 1], crop[:, :, 2]
        if kind == "chat":
            # black / dark red / dark blue / blue text on the parchment (~200,180,140)
            ink = (np.maximum(np.maximum(r, g), b) < 120) | ((b > 140) & (r < 90) & (g < 90))
        else:
            # yellow / orange / white text on a dark box
            ink = ((r > 190) & (g > 110) & (b < 110)) | (np.minimum(np.minimum(r, g), b) > 205)
        sig = ink[::2, ::2].tobytes()
        cache = getattr(self, "_ocr_cache", None)
        if cache is None:
            cache = self._ocr_cache = {}
        if cache.get(kind, (None,))[0] == sig:
            return cache[kind][1]
        if ink.mean() < 0.002:
            cache[kind] = (sig, "")
            setattr(self, f"_lines_{kind}", [])
            return ""
        img = Image.fromarray(np.where(ink, 0, 255).astype(np.uint8))
        img = img.resize((img.width * 2, img.height * 2), Image.NEAREST)
        t0 = time.time()
        try:
            import pytesseract
            from core.ocr import tess  # noqa: F401  (sets the tessdata folder)
            d = pytesseract.image_to_data(img, lang="osrs", config="--psm 6",
                                          output_type=pytesseract.Output.DICT, timeout=20)
        except Exception as e:
            self.log.warning(f"OCR ({kind}) failed: {e}")
            return ""
        ws = []
        for i, t in enumerate(d["text"]):
            t = (t or "").strip()
            try:
                conf = float(d["conf"][i])
            except (TypeError, ValueError):
                conf = -1.0
            if not t or conf < 10:
                continue
            x, y, w, h = d["left"][i], d["top"][i], d["width"][i], d["height"][i]
            ws.append({"text": t, "conf": conf, "x1": box[0] + x // 2, "y1": box[1] + y // 2,
                       "x2": box[0] + (x + w) // 2, "y2": box[1] + (y + h) // 2,
                       "line": f'{d["block_num"][i]}.{d["par_num"][i]}.{d["line_num"][i]}'})
        ls = lines(ws)
        setattr(self, f"_lines_{kind}", ls)
        text = " ".join(l["text"] for l in ls)
        cache[kind] = (sig, text)
        self.log.debug(f"OCR {kind} {time.time() - t0:.1f}s: {text[:100]!r}")
        return text

    def _chat_box(self):
        try:
            c = self.client.sectors.chat
            if c and c.width > 300 and c.height > 80:
                return (c.start_x, c.start_y, c.end_x, c.end_y)
        except Exception:
            pass
        return CHAT_BOX

    CONTINUE_RE = re.compile(r"(click|here|tap) (here )?t[o0] c[o0]n?t|t[o0] c[o0]nt[il1]?nu|c[o0]nt[il1]?nue$")
    OPTION_RE = re.compile(r"select an? [o0]pt|select an?\b")

    STRONG_CONTINUE_RE = re.compile(r"(click|here|tap) (here )?t[o0] c[o0]")

    def _continue(self, low: str) -> bool:
        if getattr(self, "_from_overlay", False):
            return False  # dialogues are always in the chat box
        if not self.CONTINUE_RE.search(low.strip()):
            return False
        # an instruction can end "...speak with the magic instructor to continue": the
        # instruction box has a blue title at the top, a dialogue doesn't
        if getattr(self, "_blue_title", False) and not self.STRONG_CONTINUE_RE.search(low):
            return False
        return True

    def _options(self, low: str) -> bool:
        # the "Select an Option" header (dark red) is often lost by OCR; instructors' menus
        # all offer "Tell me about ... again" lines; the mainland menu has "Yes." / "No."
        if getattr(self, "_from_overlay", False):
            return False
        return bool(self.OPTION_RE.search(low)) or (has(low, "tell me about") and has(low, "again")) \
            or self._short_option_menu()

    def _short_option_menu(self) -> bool:
        ls = getattr(self, "_chat_lines_box", []) or []
        if any(self.CONTINUE_RE.search(l["text"].lower()) for l in ls):
            return False  # an NPC line ("...ask the Ironman tutor... Click here to continue")
        words = [re.sub(r"[^a-z]", "", l["text"].lower()) for l in ls]
        if any(w.endswith("yes") and len(w) <= 6 for w in words) and len(ls) <= 5:
            return True
        return any(has(l["text"], "not planning", "iron man", "ironman") for l in ls) and len(ls) <= 5

    def _is_dialogue(self, low: str) -> bool:
        return self._continue(low) or self._options(low)

    def _dialogue(self, low: str, sc) -> bool:
        if self._options(low):
            return self._choose_option()
        # "Click here to continue" is blue at the bottom of the chat box (OCR sometimes
        # loses the words; the instruction box only has its blue title at the top)
        a = np.asarray(sc.convert("RGB").crop((60, 445, 460, 472)), dtype=np.int16)
        blue_bottom = int(((a[:, :, 2] > 170) & (a[:, :, 0] < 70) & (a[:, :, 1] < 70)).sum())
        if blue_bottom >= 40 and not self._continue(low):
            self.log.debug(f"Blue 'continue' line seen ({blue_bottom} px)")
            low = low + " click here to continue"
        if self._continue(low):
            time.sleep(self.cfg.continue_pause.choose())
            keyboard.press_and_release("space")
            self.log.debug("Dialogue: space")
            time.sleep(random.uniform(0.3, 0.6))
            # some boxes ignore space: click the line then
            again = self.read_chat().lower()
            if self._continue(again) and self._key(again) == self._key(low):
                ln = next((l for l in getattr(self, "_chat_lines", []) if self._continue(l["text"].lower())), None)
                if ln:
                    self._click_box(ln)
            return True
        return False

    def _choose_option(self) -> bool:
        ls = getattr(self, "_chat_lines", [])
        idx = next((i for i, l in enumerate(ls) if self.OPTION_RE.search(l["text"].lower())), None)
        if idx is None:
            if not any(has(l["text"], "tell me about") for l in ls) and not self._short_option_menu():
                return False
            idx = -1  # no header read: every line is an option
        options = [l for l in ls[idx + 1:] if len(l["text"].strip()) > 1][:5]
        texts = [o["text"].lower() for o in options]
        never = [n.lower() for n in self.cfg.option_never.value]
        pick = None
        for pref in self.cfg.option_prefs.value:
            pref = pref.lower()
            for i, t in enumerate(texts):
                if pref in t and not any(n in t for n in never):
                    pick = i
                    break
            if pick is not None:
                break
        if pick is None and idx == -1 and not any(has(t, "tell me about") for t in texts):
            self.log.info(f"Options without a header and none I know: {[o['text'] for o in options]}")
            return False
        if pick is None:
            pick = next((i for i, t in enumerate(texts) if not any(n in t for n in never)), 0)
        self.log.info(f"Options {[o['text'] for o in options]}: choosing {pick + 1}")
        time.sleep(self.cfg.continue_pause.choose())
        if idx >= 0 and random.random() < 0.5:  # (without the header the number may be off)
            keyboard.press_and_release(str(pick + 1))
        else:
            self._click_box(options[pick])
        time.sleep(random.uniform(0.4, 0.8))
        # the menu stays up a moment: don't read it again as an instruction (that made the
        # bot talk to the instructor again and restart the mainland dialogue)
        before = self._key(" ".join(texts))
        end = time.time() + 4
        while time.time() < end:
            self.read_chat()
            now = self._key(" ".join(l["text"].lower() for l in getattr(self, "_chat_lines_box", [])))
            if now and tools.text_similarity(now, before) < 0.6:
                break
            time.sleep(random.uniform(0.3, 0.5))
        return True

    # ================================================================== rules
    def _rule(self, t: str):
        """Which step the instruction asks for. OCR mixes up letters ("Iogs", "treo",
        "{con"), so every keyword is looked for fuzzily (has())."""
        H = lambda *k: has(t, *k)
        R = [
            ("appearance", lambda: H("appearance") and H("character"), self.do_appearance),
            ("waiting", lambda: H("please wait", "sit back", "attempting to", "bar over your head"), self.do_wait),
            ("tab", lambda: (H("flashing") and not H("arrow")) or H("open up the magic"), self.do_tab),
            ("go on", lambda: H("want a recap"), self.do_path),
            ("magic: cast", lambda: H("wind strike", "magic casting", "now have some runes", "runes to cast", "on a chicken"),
             self.do_wind_strike),
            ("mainland", lambda: H("mainland"), self.do_mainland),
            ("fishing", lambda: H("fishing spot", "catch some shrimp"), self.do_fish),
            ("woodcutting", lambda: H("need some logs", "cut down", "cutting it down", "nearby tree", "chop"),
             self.do_chop),
            ("firemaking", lambda: H("tinderbox", "light a fire"), self.do_fire),
            ("cook shrimp", lambda: H("shrimp") and H("cook"), self.do_cook_shrimp),
            ("dough", lambda: H("dough") and H("flour", "mix"), self.do_dough),
            ("bake", lambda: H("range") and H("bread", "dough", "bake"), self.do_range),
            ("run", lambda: H("run or walk", "running is faster", "fancy a run"), self.do_run),
            ("smithing menu", lambda: H("smithing menu", "list of all the things"), self.do_dagger_menu),
            ("anvil", lambda: H("anvil") and H("hammer"), self.do_anvil),
            ("smelt", lambda: H("smelt") and H("furnace"), self.do_smelt),
            ("mine", lambda: H("mine", "mining") and H("tin", "copper") and not H("bronze bar"), self.do_mine),
            ("wield dagger", lambda: (H("equipment stats", "combined statistics") or (H("dagger") and H("wear", "wield")))
             and not H("unequip", "holding your dagger"), self.do_wield_dagger),
            ("equipment stats", lambda: H("worn inventory", "shield and helmet") and not H("unequip", "holding your dagger"),
             self.do_equipment_stats),
            ("sword and shield", lambda: H("unequip"), self.do_sword_shield),
            ("bow", lambda: H("bow") and H("arrows"), self.do_bow),
            ("attack rat", lambda: H("rat") and H("slay", "attack"), self.do_attack_rat),
            ("first kill", lambda: H("first kill", "made your first", "gate and talk"), self.do_after_kill),
            ("bank", lambda: H("this is your bank"), self.do_close_bank),
            ("bank booth", lambda: H("bank of gielinor", "front of the building"), self.do_bank_booth),
            ("poll booth", lambda: H("poll booth") and not H("door"), self.do_poll),
            ("ladder", lambda: H("ladder", "enter some caves", "go down to", "indicated ladder",
                                 "completed the tasks", "climb up"), self.do_ladder),
            ("door", lambda: H("door", "gate", "pass through", "continue through", "shown by the arrow"), self.do_path),
            ("walk to npc", lambda: H("follow the path", "find the"), self.do_talk),
            ("talk", lambda: True, self.do_talk),
        ]
        for name, cond, fn in R:
            try:
                if cond():
                    return name, fn
            except Exception:
                continue
        return "talk", self.do_talk

    # ================================================================== actions
    def do_wait(self, t):
        self.set_activity("waiting")
        self.sleep_checked(random.uniform(1.5, 3.0))

    def do_appearance(self, t):
        self._appearance(self.client.get_screenshot(), force=True)

    def _appearance(self, sc, force: bool = False) -> bool:
        """The character design screen: a few random looks, then Confirm."""
        try:
            ln = find_line(sc, "Confirm", VIEW, min_ratio=0.85)
        except Exception:
            ln = None
        if not ln:
            return False
        if not force and "confirm" not in ln["text"].lower():
            return False
        self.log.info("Appearance screen: confirming")
        time.sleep(random.uniform(0.6, 1.8))
        self._click_box(ln)
        time.sleep(random.uniform(1.0, 1.8))
        return True

    def do_tab(self, t):
        want = None
        for name in ("equipment", "combat", "quests", "skills", "settings", "account", "prayer",
                     "friends", "spells", "music", "emotes", "inventory"):
            if has(t, *TABS[name][1]):
                want = name
                break
        if "open up the magic" in t:
            want = "spells"
        self.log.info(f"Tab: {want or 'the flashing one'}")
        if want and self.click_tab(want):
            return
        self.click_flashing_tab()

    def do_talk(self, t):
        npc = None
        for w, n in NPC_WORDS:
            if w in t:
                npc = n
                break
        names = [npc] if npc else NPCS
        self.talk(names)

    def do_path(self, t):
        self._close_interface()  # e.g. the poll history window covers the view
        if has(t, "speak to", "talk to"):
            # "exit the door ... then speak to X": once X is in sight, talk (no walking)
            npc = next((n for w, n in NPC_WORDS if has(t, w)), None)
            if npc and self.find_npcs():
                wanted = [f"Talk-to {npc}"]
                for m in self.find_npcs()[:6]:
                    if self.hover_click(m.get_point_within(), wanted):
                        self.sleep_checked(random.uniform(1.5, 2.5))
                        return
        verbs = ["Open Door", "Open Gate"]
        if self.hint_interact(verbs):
            return
        if not self.walk_to_hint():
            if has(t, "speak to", "talk to") and self.walk_to_minimap_npc():
                return
            # no arrow at all: the nearest door/gate (red mark on the minimap)
            if self.same >= 1 and self.walk_to_minimap_door():
                self.hover_search(verbs)

    def do_ladder(self, t):
        # "go down to the caves" / "climb the ladder (up)" ; upstairs by mistake -> go down
        tile = self.my_tile()
        down = has(t, "go down", "downto", "caves") or (tile is not None and tile[1] < 9000)
        verbs = ["Climb-down Ladder", "Climb-down Staircase"] if down else ["Climb-up Ladder"]
        if tile is not None and tile[2] > 0 and tile[1] < 9000:
            # upstairs (a ladder in the quest house goes up too): the top of that ladder is
            # where the character stands - look for "Climb-down" in menus around it
            self.log.info(f"Upstairs (tile {tile}): looking for the way down around the character")
            if self.same % 2 == 1:
                # step aside first (the character may stand on the ladder's top and hide it)
                ang = random.uniform(0, 2 * math.pi)
                d = random.uniform(10, 16)
                self.client.click((int(MINIMAP_C[0] + d * math.cos(ang)), int(MINIMAP_C[1] + d * math.sin(ang))))
                self.log.info("Stepped aside via the minimap")
                self.sleep_checked(random.uniform(2.5, 3.5))
            # the arrow only shows where the ladder downstairs is: search the whole room
            if self.hover_search(verbs + ["Climb-down *"]):
                self.sleep_checked(random.uniform(2.0, 3.0))
            return
        if not self.hint_interact(verbs, search=True):
            self.walk_to_hint()

    def do_fish(self, t):
        if self.click_npc(["Net Fishing spot"]):
            self.sleep_checked(random.uniform(3, 5))

    def do_chop(self, t):
        if self.hint_interact(["Chop down Tree", "Chop Tree"], search=True):
            self.sleep_checked(random.uniform(3, 5))

    def do_fire(self, t):
        self.ensure_tab("inventory")
        if self.use_item_on_item("Tinderbox", "Logs"):
            self.sleep_checked(random.uniform(3, 5))

    def do_cook_shrimp(self, t):
        self.ensure_tab("inventory")
        if self.use_item_on("Raw shrimps", ["* Fire"]):
            self.sleep_checked(random.uniform(3, 5))

    def do_dough(self, t):
        self.ensure_tab("inventory")
        if not self._inv_item("Pot of flour"):
            self.talk(["Master Chef"])
            return
        self.use_item_on_item("Pot of flour", "Bucket of water")

    def do_range(self, t):
        self.ensure_tab("inventory")
        if self.use_item_on("Bread dough", ["* Range"]):
            self.sleep_checked(random.uniform(3, 5))

    def do_run(self, t):
        try:
            self.client.click(self.client.minimap.run.scale_px(-2).get_point_within())
        except Exception:
            self.log.warning("Run orb not found", exc_info=True)
        time.sleep(self.cfg.action_pause.choose())
        self.do_path(t)

    def do_mine(self, t):
        # the box says "mine tin, then copper" the whole time: go by the inventory
        self.ensure_tab("inventory")
        if self._inv_item("Bronze dagger", 0.97) is not None:
            self.log.info("Dagger made already: moving on")
            self.do_path(t)
            return
        if self._inv_item("Bronze bar", 0.97) is not None:
            self.log.info("Bronze bar in the inventory: smithing")
            self.do_anvil(t)
            return
        tin, copper = self._inv_item("Tin ore", 0.97) is not None, self._inv_item("Copper ore", 0.97) is not None
        if tin and copper:
            self.log.info("Both ores in the inventory: smelting")
            self.do_smelt(t)
            return
        ore = "copper" if tin else "tin"
        if self.hint_interact([f"Mine {ore.title()} rocks"], search=True):
            self.sleep_checked(random.uniform(3, 5))

    def do_smelt(self, t):
        self.ensure_tab("inventory")
        if self.use_item_on("Tin ore", ["* Furnace"]) or self.hint_interact(["Use Furnace", "Smelt Furnace"]):
            self.sleep_checked(random.uniform(3, 5))

    def do_anvil(self, t):
        self.ensure_tab("inventory")
        if not self._inv_item("Hammer"):
            self.talk(["Mining Instructor"])
            return
        if self.use_item_on("Bronze bar", ["* Anvil"]) or self.hint_interact(["Smith Anvil", "Use Anvil"]):
            time.sleep(random.uniform(1.2, 2.0))
            self.do_dagger_menu(t)

    def do_dagger_menu(self, t):
        sc = self.client.get_screenshot()
        ln = find_line(sc, "Dagger", VIEW, min_ratio=0.8)
        if not ln:
            self.log.info("Smithing menu: 'Dagger' not found")
            return
        # the item icon is above its name: click the name/icon area
        box = {"x1": ln["x1"] - 4, "y1": ln["y1"] - 22, "x2": ln["x2"] + 4, "y2": ln["y2"]}
        self._click_box(box)
        self.sleep_checked(random.uniform(3, 4.5))

    def do_equipment_stats(self, t):
        self.ensure_tab("equipment")
        m = self._find_tpl("data/ui/equipment_stats.webp", SIDE_PANEL, 0.7)
        if m is None:
            self.log.info("'View equipment stats' button not found")
            return
        self.client.click(m.scale_px(-2).get_point_within())
        time.sleep(random.uniform(1.0, 1.6))

    def do_wield_dagger(self, t):
        self._wield(["Bronze dagger"])
        time.sleep(random.uniform(0.8, 1.4))
        self._close_interface()

    def do_sword_shield(self, t):
        self._close_interface()
        self.ensure_tab("inventory")
        self._wield(["Bronze sword", "Wooden shield"])

    def do_bow(self, t):
        self.ensure_tab("inventory")
        self._wield(["Shortbow", "Bronze arrow"])
        self.attack_rat()

    def do_attack_rat(self, t):
        self.attack_rat()

    def do_after_kill(self, t):
        """Out of the rat pen through the gate, then talk to the instructor. Inside the pen
        a talk click only gives "I can't reach that"."""
        # talk first: if a dialogue opens we were outside already
        if self.talk(["Combat Instructor"]):
            end = time.time() + 5
            while time.time() < end:
                if self._is_dialogue(self.read_chat().lower()):
                    return
                time.sleep(0.6)
        if not getattr(self, "_gate_done", False):
            if self.gate_between_us_and_hint() or (self.walk_to_minimap_door() and self.hover_search(["Open Gate"])):
                self._gate_done = True  # went through: don't go back in
                self.sleep_checked(random.uniform(2.0, 3.0))
                self.talk(["Combat Instructor"])

    def walk_to_minimap_door(self) -> bool:
        """Doors and gates are short red lines on the minimap: walk to the nearest one."""
        sc = self.client.get_screenshot().convert("RGB")
        x0, y0 = MINIMAP_C[0] - MINIMAP_R, MINIMAP_C[1] - MINIMAP_R
        a = np.asarray(sc.crop((x0, y0, MINIMAP_C[0] + MINIMAP_R, MINIMAP_C[1] + MINIMAP_R)), dtype=np.int16)
        red = (a[:, :, 0] > 170) & (a[:, :, 1] < 70) & (a[:, :, 2] < 70)
        num, _, st, ce = cv2.connectedComponentsWithStats(red.astype(np.uint8), connectivity=8)
        best = None
        for i in range(1, num):
            area = int(st[i][4])
            if not 3 <= area <= 25:
                continue  # door lines are thin; the red hint arrow is a big blob
            px, py = x0 + float(ce[i][0]), y0 + float(ce[i][1])
            d = math.hypot(px - MINIMAP_C[0], py - MINIMAP_C[1])
            if d < MINIMAP_R - 4 and (best is None or d < best[0]):
                best = (d, (px, py))
        if best is None:
            self.log.info("No door/gate on the minimap")
            return False
        d, (px, py) = best
        self.log.info(f"Walking to the nearest door/gate on the minimap ({px:.0f},{py:.0f}, {d / 4:.0f} tiles)")
        # stop a tile short, on our side of it
        k = max(0.0, (d - 4) / d)
        self.client.click((int(MINIMAP_C[0] + (px - MINIMAP_C[0]) * k), int(MINIMAP_C[1] + (py - MINIMAP_C[1]) * k)))
        self.sleep_checked(random.uniform(4.0, 6.0))
        return True

    def grid_search(self, wanted: list[str], step: int = 28) -> bool:
        """Mouse-over search over the whole game view (nearest to the character first)."""
        px, py = self._player_point()
        pts = [(x + random.randint(-5, 5), y + random.randint(-5, 5))
               for y in range(VIEW[1] + 20, VIEW[3] - 10, step) for x in range(VIEW[0] + 14, VIEW[2] - 10, step)
               if not (x < OVERLAY_BOX[2] and y < 80)]
        pts.sort(key=lambda p: math.hypot(p[0] - px, p[1] - py))
        for pt in pts:
            if self.terminate:
                raise ScriptTerminationException()
            if self.hover_click(pt, wanted):
                return True
        self.log.info(f"Whole-view search: no {wanted}")
        return False

    def gate_between_us_and_hint(self) -> bool:
        """The rat pen's gate lies between the character and the instructor (who has the
        arrow): look along that line, a bit to each side, with the mouse (and menus)."""
        hint = self.find_hint(looks=3)
        if hint is None:
            return False
        px, py = self._player_point()
        hx, hy = (hint.start_x + hint.end_x) // 2, hint.end_y + 15
        L = max(1.0, math.hypot(hx - px, hy - py))
        nx, ny = -(hy - py) / L, (hx - px) / L
        pts = []
        for f in (0.35, 0.5, 0.65, 0.25, 0.8):
            for off in (0, -12, 12, -24, 24):
                pts.append((int(px + (hx - px) * f + nx * off), int(py + (hy - py) * f + ny * off)))
        self._menu_ok = True
        try:
            for pt in pts:
                if self.hover_click(pt, ["Open Gate"]):
                    return True
        finally:
            self._menu_ok = False
        return False

    def menu_grid_at_hint(self, wanted: list[str]) -> bool:
        """Right-click menus on a small grid around the hint arrow's tip (a gate/ladder right
        under the arrow whose mouse-over shows something else first)."""
        hint = self.find_hint(looks=3)
        if hint is None:
            return False
        cx, cy = (hint.start_x + hint.end_x) // 2, hint.end_y
        pts = [(cx + dx, cy + dy) for dy in range(-4, 44, 8) for dx in range(-18, 19, 9)]
        pts.sort(key=lambda p: math.hypot(p[0] - cx, (p[1] - cy - 12) * 1.5))
        for pt in pts[:24]:
            self.client.move_to((pt[0] + random.randint(-2, 2), min(VIEW[3] - 2, pt[1] + random.randint(-2, 2))))
            time.sleep(random.uniform(0.08, 0.15))
            if self.menu_pick(wanted):
                return True
        return False

    def do_bank_booth(self, t):
        if not self.hint_interact(["Use Bank booth", "Bank Bank booth"], search=True):
            self.walk_to_hint()

    def do_close_bank(self, t):
        self._close_interface()
        time.sleep(random.uniform(0.6, 1.2))
        self.do_poll(t)

    def do_poll(self, t):
        if self._close_interface():
            time.sleep(random.uniform(0.5, 1.0))
        if not self.hint_interact(["Use Poll booth"], search=True):
            self.walk_to_hint()

    def do_wind_strike(self, t):
        self.ensure_tab("spells")
        if not self.hover_scan_panel(["Cast Wind Strike"]):
            self.log.info("Wind Strike not found in the spellbook")
            return
        time.sleep(random.uniform(0.3, 0.6))
        if self.click_npc(["* Chicken"], verb_any=True):
            self.sleep_checked(random.uniform(3, 4))

    def do_mainland(self, t):
        m = self._find_tpl("data/ui/close-scroll-x.png", (412, 48, 468, 104), 0.96)
        if m is not None and not self._scroll_open():
            m = None
        if m is not None:  # the "quest complete" scroll
            self.log.info(f"Closing the quest scroll ({m.start_x},{m.start_y} conf {m.confidence:.2f})")
            self.client.click(m.scale_px(-1).get_point_within())
            time.sleep(random.uniform(0.6, 1.0))
        if has(t, "home") and has(t, "teleport", "spell", "lumbridge", "take you"):
            self.ensure_tab("spells")
            if self.hover_scan_panel(["Cast Lumbridge Home Teleport", "Cast Home Teleport"]):
                self.sleep_checked(random.uniform(14, 18))
                return
        self._mainland_asked = True
        self.talk(["Magic Instructor"])

    # ================================================================== done?
    def _done(self) -> bool:
        tile = self.my_tile()
        if tile is None:
            return False
        x, y, _ = tile
        on_island = any(x1 <= x <= x2 and y1 <= y <= y2 for x1, y1, x2, y2 in ISLAND)
        if not on_island:
            self.log.info(f"Tile {tile}: not on Tutorial Island")
        return not on_island

    # ================================================================== tabs
    def _tab_cells(self):
        for row in TAB_ROWS:
            x1, y1, x2, y2 = row
            for i in range((x2 - x1) // TAB_W):
                yield (x1 + i * TAB_W, y1, x1 + (i + 1) * TAB_W, y2)

    def _find_tpl(self, path: str, box, conf: float = 0.75) -> MatchResult | None:
        sc = self.client.get_screenshot()
        img = self._tpl.get(path)
        if img is None:
            img = self._tpl[path] = Image.open(path).convert("RGB")
        x1, y1, x2, y2 = box
        try:
            m = tools.find_subimage(sc.convert("RGB").crop(box), img, min_scale=0.9, max_scale=1.1)
        except Exception:
            self.log.debug(f"template {path} failed", exc_info=True)
            return None
        if m.confidence < conf:
            self.log.debug(f"template {path}: best {m.confidence:.2f}")
            return None
        return m.transform(x1, y1)

    def click_tab(self, name: str) -> bool:
        if name in TAB_POS:
            # fixed layout: every tab has its own place (measured: logout 646,484, settings 680,484)
            col, row = TAB_POS[name]
            x1 = TAB_ROWS[row][0] + col * TAB_W
            y1, y2 = TAB_ROWS[row][1], TAB_ROWS[row][3]
            self.client.click(MatchResult(x1 + 8, y1 + 7, x1 + TAB_W - 8, y2 - 7).get_point_within())
            self.log.info(f"Clicked the {name} tab (fixed place)")
            time.sleep(self.cfg.action_pause.choose())
            return True
        for box in TAB_ROWS:
            m = self._find_tpl(TABS[name][0], (box[0] - 2, box[1] - 2, box[2] + 2, box[3] + 2), 0.62)
            if m is not None:
                self.client.click(m.scale_px(-2).get_point_within())
                time.sleep(self.cfg.action_pause.choose())
                return True
        self.log.info(f"Tab icon '{name}' not found")
        return False

    def ensure_tab(self, name: str) -> None:
        """Open a tab if it isn't the open one (the open tab has a red background)."""
        for box in TAB_ROWS:
            m = self._find_tpl(TABS[name][0], (box[0] - 2, box[1] - 2, box[2] + 2, box[3] + 2), 0.72)
            if m is None:
                continue
            sc = self.client.get_screenshot()
            a = np.asarray(sc.convert("RGB").crop(m.scale_px(3).bounding_box), dtype=np.int16)
            red = ((a[:, :, 0] > 90) & (a[:, :, 0] > 2 * a[:, :, 1]) & (a[:, :, 0] > 2 * a[:, :, 2])).mean()
            if red > 0.15:
                return
            self.client.click(m.scale_px(-2).get_point_within())
            time.sleep(self.cfg.action_pause.choose())
            return

    def click_flashing_tab(self) -> bool:
        """The tab the tutorial wants flashes: the cell whose pixels change most."""
        frames = []
        for _ in range(10):
            frames.append(np.asarray(self.client.get_screenshot().convert("L"), dtype=np.int16))
            time.sleep(random.uniform(0.22, 0.3))
        best, best_v = None, 0.0
        for cell in self._tab_cells():
            x1, y1, x2, y2 = cell
            stack = np.stack([f[y1 + 3:y2 - 3, x1 + 3:x2 - 3] for f in frames])
            v = float(np.abs(np.diff(stack, axis=0)).mean())
            if v > best_v:
                best, best_v = cell, v
        if best is None or best_v < 3.0:
            self.log.info(f"No flashing tab seen (best change {best_v:.1f})")
            return False
        self.log.info(f"Flashing tab at {best} (change {best_v:.1f})")
        x1, y1, x2, y2 = best
        self.client.click(MatchResult(x1 + 7, y1 + 7, x2 - 7, y2 - 7).get_point_within())
        time.sleep(self.cfg.action_pause.choose())
        return True

    # ================================================================== inventory
    def _inv_item(self, name: str, conf: float = 0.9) -> MatchResult | None:
        try:
            ms = self.client.get_inv_items([name], min_confidence=conf, verify_tab=False)
        except Exception:
            self.log.debug(f"inventory search for {name} failed", exc_info=True)
            return None
        return ms[0] if ms else None

    def _selected(self, slot: MatchResult) -> bool:
        sc = self.client.get_screenshot()
        a = np.asarray(sc.convert("RGB").crop(slot.bounding_box))
        return int((a.min(axis=2) >= 240).sum()) >= 15

    def _select(self, name: str) -> MatchResult | None:
        m = self._inv_item(name)
        if m is None:
            self.log.info(f"{name} not in the inventory")
            return None
        slot = self.inv_slot(m)
        for _ in range(3):
            self.click_inv(m)
            time.sleep(random.uniform(0.15, 0.3))
            if self._selected(slot):
                return slot
        self.log.info(f"{name} didn't get selected")
        return None

    def use_item_on_item(self, a: str, b: str) -> bool:
        if self._select(a) is None:
            return False
        mb = self._inv_item(b)
        if mb is None:
            self.log.info(f"{b} not in the inventory")
            self._deselect()
            return False
        self.click_inv(mb)
        time.sleep(self.cfg.action_pause.choose())
        self._mouse_to_view()
        return True

    def use_item_on(self, item: str, wanted: list[str]) -> bool:
        if self._select(item) is None:
            return False
        if self.hint_interact(wanted, search=True):
            return True
        self._deselect()
        return False

    def _deselect(self):
        """Cancel a selected item ("Use X ->"): a click on the character's own minimap spot
        (walks nowhere, drops the selection)."""
        self.client.click((MINIMAP_C[0] + random.randint(-2, 2), MINIMAP_C[1] + random.randint(-2, 2)))
        time.sleep(random.uniform(0.3, 0.5))

    def _selected_any(self) -> bool:
        top = self.top_hover().lower()
        return top.startswith("use ") and "->" in top

    def _wield(self, names: list[str]):
        """Wield/wear the named items: hover every filled inventory slot and click the ones
        whose mouse-over says "Wield <name>" / "Wear <name>" (icon matching mixed up the
        wooden shield and the pot)."""
        left = {n.lower() for n in names}
        sc = self.client.get_screenshot()
        slots = inventory.used_slots(sc)
        random.shuffle(slots)
        for slot in slots:
            if not left:
                break
            self.move_inv(slot)
            time.sleep(random.uniform(0.25, 0.35))
            hov = [h for h in list(self.client.get_hover_texts()) + [self.top_hover()] if h]
            hit = None
            for n in list(left):
                key = n.split()[-1][:5]
                if any((text_matches(h, "Wield *") or text_matches(h, "Wear *")) and key in h.lower() for h in hov):
                    hit = n
                    break
            if hit:
                press()
                left.discard(hit)
                self.log.info(f"Wielded {hit} ({hov})")
                time.sleep(random.uniform(0.6, 1.0))
        if left:
            self.log.info(f"Not found to wield: {sorted(left)}")

    # ================================================================== world clicks
    def _player_point(self) -> tuple[int, int]:
        x1, y1, x2, y2 = VIEW
        return (x1 + x2) // 2, (y1 + y2) // 2 + 8

    def find_hint(self, sc=None, looks: int = 4) -> MatchResult | None:
        """The hint arrow flashes: look at a few frames before saying there is none."""
        for k in range(looks):
            m = self._find_hint_once(sc if k == 0 else None)
            if m is not None:
                return m
            time.sleep(random.uniform(0.15, 0.25))
        return None

    def _find_hint_once(self, sc=None) -> MatchResult | None:
        """The tutorial's yellow hint arrow: a fixed-size sprite, found by matching its shape
        (HINT_ARROW) in the yellow pixels of the game view; under the dark instruction box
        (top-left) the arrow is dimmed, so there the dim yellow is matched too. Door frames
        and other yellow things score <= 0.65, the arrow ~1.0 (measured on the island)."""
        sc = (sc or self.client.get_screenshot()).convert("RGB")
        best = None
        for dim, box in ((False, VIEW), (True, OVERLAY_BOX)):
            hsv = cv2.cvtColor(np.asarray(sc.crop(box)), cv2.COLOR_RGB2HSV)
            dh = np.abs(hsv[:, :, 0].astype(np.int16) - 29)
            if dim:
                m = (dh <= 5) & (hsv[:, :, 1] >= 60) & (hsv[:, :, 2] >= 75) & (hsv[:, :, 2] <= 150)
            else:
                m = (dh <= 5) & (hsv[:, :, 1] >= 40) & (hsv[:, :, 2] >= 200)
            if m.shape[0] < HINT_ARROW.shape[0] or m.shape[1] < HINT_ARROW.shape[1]:
                continue
            r = cv2.matchTemplate(m.astype(np.float32), HINT_ARROW, cv2.TM_CCORR_NORMED)
            _, mx, _, loc = cv2.minMaxLoc(r)
            self.log.debug(f"Hint arrow match {'dim' if dim else 'bright'}: {mx:.2f} at {loc}")
            if mx >= 0.8 and (best is None or mx > best[0]):
                x, y = loc[0] + box[0], loc[1] + box[1]
                best = (mx, MatchResult(x + 3, y + 2, x + HINT_ARROW.shape[1] - 3, y + HINT_ARROW.shape[0] - 2))
        return best[1] if best else None

    def find_minimap_hint(self, sc=None, looks: int = 4) -> tuple[float, float] | None:
        """The minimap arrow flashes too: a few looks."""
        for k in range(looks):
            p = self._find_minimap_hint_once(sc if k == 0 else None)
            if p is not None:
                return p
            time.sleep(random.uniform(0.15, 0.25))
        return None

    def _find_minimap_hint_once(self, sc=None) -> tuple[float, float] | None:
        sc = sc or self.client.get_screenshot()
        box = (MINIMAP_C[0] - MINIMAP_R, MINIMAP_C[1] - MINIMAP_R, MINIMAP_C[0] + MINIMAP_R, MINIMAP_C[1] + MINIMAP_R)
        # the minimap arrow is red (seen on the island; ground items are 2-3 px red dots),
        # sometimes yellow
        crop = sc.convert("RGB").crop(box)
        hsv = cv2.cvtColor(np.asarray(crop), cv2.COLOR_RGB2HSV)
        hh = hsv[:, :, 0].astype(np.int16)
        red = ((hh <= 6) | (hh >= 174)) & (hsv[:, :, 1] >= 150) & (hsv[:, :, 2] >= 150)
        # when the target is on the minimap the arrow is yellow over it (~33 px);
        # map icons are ~12 px yellow blobs
        yellow = (hh >= 20) & (hh <= 36) & (hsv[:, :, 1] >= 120) & (hsv[:, :, 2] >= 160)
        best = None
        for mask, min_px in ((red, self.cfg.hint_min_pixels_minimap.value),
                             (yellow, 22)):
            best = self._best_minimap_blob(mask, box, min_px, best)
        if best:
            self.log.debug(f"Minimap hint at {best[1]} ({best[0]} px)")
        return best[1] if best else None

    def _best_minimap_blob(self, mask, box, min_px, best):
        num, _, stats, cent = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
        cx, cy = MINIMAP_C  # the detected minimap box was 16 px off on the island
        r = MINIMAP_R
        for i in range(1, num):
            area = int(stats[i][4])
            px, py = box[0] + float(cent[i][0]), box[1] + float(cent[i][1])
            if math.hypot(px - cx, py - cy) > r or math.hypot(px - cx, py - cy) < 9:
                continue  # outside the round map (orbs, compass) / the character itself
            if area >= min_px and (best is None or area > best[0]):
                best = (area, (px, py))
        return best

    def top_hover(self) -> str:
        """The game's own mouse-over line in the top-left corner of the game view
        ("Walk here", "Net Fishing spot / 2 more options"): crisp text on the world."""
        sc = self.client.get_screenshot()
        box = HOVER_LINE
        a = np.asarray(sc.convert("RGB").crop(box), dtype=np.int16)
        r, g, b = a[:, :, 0], a[:, :, 1], a[:, :, 2]
        ink = (np.maximum(np.maximum(r, g), b) > 175) & ((np.minimum(np.minimum(r, g), b) > 175)
                                                         | (np.abs(r - g) > 60) | (np.abs(g - b) > 60))
        if ink.mean() < 0.01:
            return ""
        img = Image.fromarray(np.where(ink, 0, 255).astype(np.uint8))
        img = img.resize((img.width * 3, img.height * 3), Image.NEAREST)
        try:
            import pytesseract
            from core.ocr import tess  # noqa: F401
            t = pytesseract.image_to_string(img, lang="osrs_bold", config="--psm 7", timeout=6)
        except Exception as e:
            self.log.debug(f"top hover OCR failed: {e}")
            return ""
        return t.strip()

    def hover_click(self, pt, wanted: list[str]) -> bool:
        self.client.move_to(pt)
        time.sleep(random.uniform(0.08, 0.15))
        answers = self.client.get_hover_texts()
        if not any(text_matches(a, w) for a in answers for w in wanted):
            # the game's top-left line updates a frame later: give it a moment, and read it
            # twice (the first read once still showed the previous spot's text)
            time.sleep(random.uniform(0.15, 0.25))
            top = self.top_hover()
            if any(text_matches(top, w) for w in wanted):
                time.sleep(0.12)
                top2 = self.top_hover()
                top = top2 if any(text_matches(top2, w) for w in wanted) else ""
            answers = list(answers) + [top]
        if any(text_matches(a, w) for a in answers for w in wanted) \
                and not any(bad in (a or "").lower() for a in answers for bad in HOVER_NEVER):
            click(-1, -1)
            self.log.info(f"Clicked {answers} for {wanted}")
            time.sleep(self.cfg.action_pause.choose())
            return True
        try:
            mp = self.client.mouse_position()
        except Exception:
            mp = None
        self.log.debug(f"Mouse-over {answers} isn't {wanted} (aimed {pt}, mouse {mp})")
        if getattr(self, "_menu_ok", False) and any("option" in (a or "").lower() for a in answers):
            # something else is on top here ("Walk here / 2 more options"): look in the menu
            return self.menu_pick(wanted)
        return False

    def hint_interact(self, wanted: list[str], search: bool = False) -> bool:
        """Under the hint arrow: move down from its tip until the mouse-over says one of
        `wanted`, then click. `search`: no arrow / nothing there -> look around the
        character with the mouse."""
        hint = self.find_hint()
        if hint is not None:
            cx = (hint.start_x + hint.end_x) // 2
            depth = self.cfg.hint_search_depth.value
            self._menu_ok = True
            try:
                for dy in range(-2, depth, 8):
                    pt = (cx + random.randint(-7, 7), min(VIEW[3] - 2, hint.end_y + dy))
                    if self.hover_click(pt, wanted):
                        return True
            finally:
                self._menu_ok = False
            self.log.info(f"Hint arrow at {hint.bounding_box}: nothing {wanted} under it")
            near = math.hypot(cx - self._player_point()[0], hint.end_y - self._player_point()[1]) < 70
            if near or self.same >= 1:
                # right next to us and still nothing: a wall hides it - look from the other side
                self.log.info("Turning the camera (a wall may hide it)")
                try:
                    self.camera.rotate(random.uniform(1.1, 1.6))
                except Exception:
                    self.log.debug("camera turn failed", exc_info=True)
                time.sleep(random.uniform(0.4, 0.7))
                return False
            # far away: walk to it
            self.client.click((cx + random.randint(-5, 5), min(VIEW[3] - 2, hint.end_y + random.randint(25, 45))))
            self._walked = True
            self.sleep_checked(random.uniform(2.0, 3.5))
            return False
        if search:
            # off screen but the minimap points to it: walk there first (searching the
            # screen with the mouse is slow)
            mh = self.find_minimap_hint()
            if mh is not None:
                self.walk_to_hint(mh)
                return False
            return self.hover_search(wanted)
        return False

    def menu_pick(self, wanted: list[str]) -> bool:
        """Right-click where the mouse is, read the menu line by line, click a wanted entry;
        otherwise move away so the menu closes."""
        from core import ocr
        click(-1, -1, click_type=ClickType.RIGHT)
        time.sleep(random.uniform(0.2, 0.35))
        try:
            sc = self.client.get_screenshot()
            menu = self.client.get_right_click_menu(sc)
        except Exception as e:
            self.log.debug(f"No right-click menu: {e}")
            return False
        n = max(1, round((menu.height - 19) / 15))
        seen = []
        for i in range(n):
            y1 = menu.start_y + 19 + i * 15
            row = MatchResult(menu.start_x + 3, y1, menu.end_x - 3, y1 + 15)
            img = tools.mask_above_color_value(row.crop_in(sc), 150)
            try:
                text = ocr.execute(img, font=ocr.FontChoice.RUNESCAPE_BOLD_12,
                                   psm=ocr.TessPsm.SINGLE_LINE, raise_on_blank=False).strip()
            except Exception:
                text = ""
            seen.append(text)
            if any(text_matches(text, w) for w in wanted):
                target = MatchResult(row.start_x + 4, y1 + 3, min(row.end_x - 4, row.start_x + 90), y1 + 12)
                self.client.move_to(target.get_point_within(), rand_move_chance=0)
                click(-1, -1)
                self.log.info(f"Menu {seen}: picked '{text}'")
                time.sleep(self.cfg.action_pause.choose())
                return True
        self.log.debug(f"Menu {seen}: nothing {wanted}")
        x = menu.end_x + random.randint(30, 60) if menu.end_x + 70 < VIEW[2] else menu.start_x - random.randint(30, 60)
        self.client.move_to((max(8, x), random.randint(menu.start_y, menu.end_y)))
        time.sleep(random.uniform(0.2, 0.35))
        return False

    def hover_search(self, wanted: list[str]) -> bool:
        px, py = self._player_point()
        pts = []
        for r in range(25, 230, 22):
            n = max(6, int(2 * math.pi * r / 40))
            off = random.uniform(0, 2 * math.pi)
            for k in range(n):
                a = off + 2 * math.pi * k / n
                x, y = int(px + r * math.cos(a)), int(py + r * 0.75 * math.sin(a))
                if VIEW[0] + 4 < x < VIEW[2] - 4 and VIEW[1] + 4 < y < VIEW[3] - 4:
                    pts.append((x, y))
        self._menu_ok = True
        try:
            for pt in pts[: self.cfg.hover_search_points.value]:
                if self.terminate:
                    raise ScriptTerminationException()
                if self.hover_click(pt, wanted):
                    return True
        finally:
            self._menu_ok = False
        self.log.info(f"Mouse-over search: no {wanted} around the character")
        return False

    def panel_icons(self) -> list[tuple[int, int]]:
        """Centres of the icons in the side panel (anything that stands out from the
        plain brown background); the filtered spellbook shows a few big icons."""
        x1, y1, x2, y2 = SIDE_PANEL
        a = np.asarray(self.client.get_screenshot().convert("RGB").crop(SIDE_PANEL), dtype=np.int16)
        bg = np.median(a.reshape(-1, 3), axis=0)
        diff = np.abs(a - bg).sum(axis=2) > 60
        diff = cv2.morphologyEx(diff.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
        num, _, stats, cent = cv2.connectedComponentsWithStats(diff, connectivity=8)
        out = []
        for i in range(1, num):
            x, y, w, h, area = stats[i]
            if 12 <= w <= 60 and 12 <= h <= 60 and area >= 120:
                out.append((x1 + int(cent[i][0]), y1 + int(cent[i][1])))
        # an icon next to the panel's left pillar (Home Teleport) merges with it: the big
        # icons sit in a row ~69 px apart, so add the places left of the found ones too
        row = [p for p in out if p[1] < y2 - 30]
        if row:
            y = row[0][1]
            x = min(p[0] for p in row) - 69
            while x >= x1 + 12:
                out.insert(0, (x, y))
                x -= 69
        return out

    def hover_scan_panel(self, wanted: list[str]) -> bool:
        x1, y1, x2, y2 = SIDE_PANEL
        icons = self.panel_icons()
        self.log.debug(f"Panel icons: {icons}")
        for x, y in reversed(icons):  # the spell we want is usually after Home Teleport
            if self.hover_click((x + random.randint(-3, 3), y + random.randint(-3, 3)), wanted):
                return True
        for y in range(y1 + 8, y1 + 80, 24):
            for x in range(x1 + 8, x2 - 8, 24):
                if self.hover_click((x + random.randint(-3, 3), y + random.randint(-3, 3)), wanted):
                    return True
        return False

    def walk_to_hint(self, mh=None) -> bool:
        """No arrow on screen: walk toward the minimap's hint arrow."""
        hint = None if mh is not None else self.find_hint()
        if hint is not None:
            cx = (hint.start_x + hint.end_x) // 2
            self.client.click((cx + random.randint(-6, 6), min(VIEW[3] - 2, hint.end_y + random.randint(25, 45))))
            self._walked = True
            self.sleep_checked(random.uniform(2.5, 4.0))
            return True
        for _ in range(4):  # it flashes too
            if mh is not None:
                break
            mh = self.find_minimap_hint()
            if mh is None:
                time.sleep(random.uniform(0.15, 0.25))
        if mh is None:
            self.log.info("No hint arrow on the screen or the minimap")
            return False
        cx, cy = MINIMAP_C
        dx, dy = mh[0] - cx, mh[1] - cy
        d = math.hypot(dx, dy)
        # not to the edge (a spot behind a wall gives "I can't reach that"): part of the
        # way, a bit off the line after failed walks
        reach = min(d, (MINIMAP_R - 10) * random.uniform(0.45, 0.75))
        ang = math.atan2(dy, dx) + math.radians(random.uniform(-25, 25) if self.walks >= 3 else random.uniform(-6, 6))
        pt = (int(cx + reach * math.cos(ang)), int(cy + reach * math.sin(ang)))
        self.log.info(f"Walking toward the minimap hint arrow ({pt})")
        self.client.click(pt)
        self._walked = True
        self.sleep_checked(random.uniform(3.0, 5.0))
        return True

    # ------------------------------------------------------------------ NPCs
    def find_npcs(self) -> list[MatchResult]:
        sc = self.client.get_screenshot()
        view = sc.convert("RGB").crop(VIEW)
        mask = np.zeros((view.height, view.width), dtype=bool)
        for c in self.cfg.npc_colors.value:
            # by hue: the hull is drawn see-through, cyan shows as (0,160,160)..(0,255,255)
            mask |= hue_mask(view, c.value, 8, 150, 110)
        mask = cv2.dilate(mask.astype(np.uint8), np.ones((3, 3), np.uint8))
        num, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        px, py = self._player_point()
        found = []
        for i in range(1, num):
            x, y, w, h, area = (int(v) for v in stats[i])
            if area < self.cfg.min_npc_pixels.value or w < 8 or h < 8:
                continue
            m = MatchResult(VIEW[0] + x, VIEW[1] + y, VIEW[0] + x + w, VIEW[1] + y + h)
            cx, cy = m.get_center()
            found.append((math.hypot(cx - px, cy - py), m))
        found.sort(key=lambda t: t[0])
        return [m for _, m in found]

    def click_npc(self, wanted: list[str], verb_any: bool = False, search: bool = True) -> bool:
        for m in self.find_npcs()[:8]:
            inner = m.scale_px(-max(1, min(m.width, m.height) // 5)) if min(m.width, m.height) > 12 else m
            for _ in range(3):
                if self.hover_click(inner.get_point_within(), wanted):
                    return True
        # NPC not highlighted / off screen: the hint arrow may stand over it
        return self.hint_interact(wanted, search=search)

    def talk(self, names: list[str]) -> bool:
        wanted = [f"Talk-to {n}" for n in names]
        if self.click_npc(wanted, search=False):
            self.sleep_checked(random.uniform(1.2, 2.5))
            return True
        if not self.walk_to_hint():
            self.walk_to_minimap_npc()
        return False

    def walk_to_minimap_npc(self) -> bool:
        """No arrow anywhere: NPC Indicators also marks the highlighted NPCs on the minimap
        (cyan dots) - walk toward the nearest group of them."""
        sc = self.client.get_screenshot().convert("RGB")
        x0, y0 = MINIMAP_C[0] - MINIMAP_R, MINIMAP_C[1] - MINIMAP_R
        crop = sc.crop((x0, y0, MINIMAP_C[0] + MINIMAP_R, MINIMAP_C[1] + MINIMAP_R))
        m = hue_mask(crop, (0, 255, 255), 8, 150, 150)
        ys, xs = np.nonzero(m)
        pts = [(x0 + x, y0 + y) for x, y in zip(xs.tolist(), ys.tolist())
               if 8 < math.hypot(x0 + x - MINIMAP_C[0], y0 + y - MINIMAP_C[1]) < MINIMAP_R - 2]
        if not pts:
            self.log.info("No highlighted NPC on the minimap either")
            try:
                self.camera.rotate(random.uniform(0.8, 1.3))
            except Exception:
                pass
            return False
        tx, ty = min(pts, key=lambda p: math.hypot(p[0] - MINIMAP_C[0], p[1] - MINIMAP_C[1]))
        dx, dy = tx - MINIMAP_C[0], ty - MINIMAP_C[1]
        d = math.hypot(dx, dy)
        k = min(1.0, (MINIMAP_R - 12) / d)
        pt = (int(MINIMAP_C[0] + dx * k + random.uniform(-2, 2)), int(MINIMAP_C[1] + dy * k + random.uniform(-2, 2)))
        self.log.info(f"Walking toward a highlighted NPC on the minimap ({pt})")
        self.client.click(pt)
        self._walked = True
        self.sleep_checked(random.uniform(3.0, 5.0))
        return True

    # ------------------------------------------------------------------ combat
    def opponent_bar(self):
        sc = self.client.get_screenshot()
        arr = np.asarray(sc.convert("RGB").crop((0, 0, 330, 170)), dtype=np.int16)
        green = np.all(np.abs(arr - BAR_GREEN) <= BAR_TOL, axis=2)
        red = np.all(np.abs(arr - BAR_RED) <= BAR_TOL, axis=2)
        rows = [y for y in range(arr.shape[0]) if (green[y] | red[y]).sum() >= 50]
        if len(rows) < 4:
            return None
        return int(green[rows].sum()), int(red[rows].sum())

    def fighting(self) -> bool:
        bar = self.opponent_bar()
        return bool(bar and bar[0] > 12)

    def attack_rat(self) -> bool:
        if not self.click_npc(["Attack Giant rat"]):
            self.walk_to_hint()
            return False
        start = time.time()
        while time.time() - start < 6 and not self.fighting():
            self.sleep_checked(0.4)
        self.log.info("Fighting a rat" if self.fighting() else "No fight seen yet")
        while self.fighting() and time.time() - start < self.cfg.fight_timeout.value:
            self.sleep_checked(random.uniform(0.6, 1.0))
        self.log.info(f"Rat fight over after {time.time() - start:.0f}s")
        self.sleep_checked(random.uniform(1.0, 2.0))
        return True

    # ------------------------------------------------------------------ helpers
    def _scroll_open(self) -> bool:
        """The quest-complete scroll: a big plain parchment area in the game view."""
        a = np.asarray(self.client.get_screenshot().convert("RGB").crop((120, 140, 360, 240)), dtype=np.int16)
        r, g, b = a[:, :, 0], a[:, :, 1], a[:, :, 2]
        tan = (r > 170) & (g > 140) & (b > 80) & (b < 170) & (r - b > 40)
        return tan.mean() > 0.6

    def _close_interface(self) -> bool:
        """Close a window (bank, poll, equipment stats) with its X button."""
        m = self._find_tpl("data/ui/close-ui-element.png", VIEW, 0.9) \
            or self._find_tpl("data/ui/close-window-x.png", (0, 0, 520, 340), 0.9) \
            or (self._find_tpl("data/ui/close-scroll-x.png", (412, 48, 468, 104), 0.96) if self._scroll_open() else None)
        if m is None:
            return False
        self.client.click(m.scale_px(-1).get_point_within())
        time.sleep(random.uniform(0.5, 0.9))
        self.log.info(f"Closed a window (X at {m.start_x},{m.start_y} conf {m.confidence:.2f})")
        return True

    def _click_box(self, b) -> None:
        m = MatchResult(b["x1"], b["y1"], max(b["x2"], b["x1"] + 3), max(b["y2"], b["y1"] + 3))
        self.client.click(m.get_point_within())

    def _mouse_to_view(self):
        x1, y1, x2, y2 = GAME_VIEW
        self.client.move_to((random.randint(x1 + 20, x2 - 20), random.randint(y1 + 20, y2 - 20)))

    def _shot(self, tag: str):
        if self.cfg.debug_shots.value:
            self.save_debug_shot(f"tutorial-{tag}")


if __name__ == "__main__":
    BotExecutor(BotConfig()).start()
