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
    min_npc_pixels: IntParam = IntParam(60)
    # The tutorial's hint arrow: yellow (hue), strongly coloured.
    hint_color: RGBParam = RGBParam(255, 255, 0)
    hint_hue_tol: IntParam = IntParam(8)
    hint_min_pixels: IntParam = IntParam(40)       # in the game view
    hint_min_pixels_minimap: IntParam = IntParam(14)  # minimap arrow (NPC dots are ~4 px)
    # How far below the arrow's tip the mouse-over search goes (px).
    hint_search_depth: IntParam = IntParam(110)

    # --- dialogue: options picked in this order (lower case, part of the line) ---
    option_prefs: StringListParam = StringListParam([
        "experienced player", "yes.", "not planning", "i'm fine", "fine, thanks", "yes",
    ])
    # never picked (ironman modes)
    option_never: StringListParam = StringListParam([
        "become an iron", "change my iron", "tell me about iron", "what's an iron",
    ])

    # --- pacing ---
    step_wait: FloatParam = FloatParam(25.0)        # s to wait for the instruction to change
    action_pause: RangeParam = RangeParam(0.35, 0.9)  # after a click
    read_every: RangeParam = RangeParam(0.9, 1.6)   # s between two looks while waiting
    continue_pause: RangeParam = RangeParam(0.45, 1.3)  # before pressing space in a dialogue
    max_same: IntParam = IntParam(8)               # tries on one instruction before "stuck"
    max_unknown: IntParam = IntParam(25)           # looks with no instruction/dialogue before "stuck"
    fight_timeout: FloatParam = FloatParam(90.0)
    hover_search_points: IntParam = IntParam(40)   # mouse-over search around the character

    # --- habits (small, it's a short run) ---
    camera_chance: FloatParam = FloatParam(0.04)   # after a finished step
    camera_rotate_time: RangeParam = RangeParam(0.3, 1.0)
    camera_zoom_chance: FloatParam = FloatParam(0.4)
    start_zoom_in: IntParam = IntParam(10)
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
SIDE_PANEL = (548, 205, 740, 465)
TAB_ROWS = ((521, 168, 752, 204), (521, 466, 752, 502))
TAB_W = 33
VIEW = (4, 4, 512, 334)  # game view
# tab name -> template (data/ui) and words in the instruction that point to it
TABS = {
    "settings": ("data/ui/settings.webp", ("spanner", "settings")),
    "inventory": ("data/ui/inventory.webp", ("backpack", "inventory")),
    "skills": ("data/ui/stats.webp", ("bar graph", "skills menu")),
    "quests": ("data/ui/quests.webp", ("quest journal", "left of your inventory", "quest")),
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
NPC_WORDS = [("gielinor guide", "Gielinor Guide"), ("survival", "Survival Expert"),
             ("chef", "Master Chef"), ("quest guide", "Quest Guide"), ("quests", "Quest Guide"),
             ("mining instructor", "Mining Instructor"), ("combat", "Combat Instructor"),
             ("account", "Account Guide"), ("monk", "Brother Brace"), ("brother brace", "Brother Brace"),
             ("prayer", "Brother Brace"), ("magic", "Magic Instructor"), ("mainland", "Magic Instructor")]
# Tutorial Island (surface and the caves) in world tiles; outside = on the mainland.
ISLAND = ((3040, 3040, 3170, 3145), (3040, 9480, 3170, 9545))
HOVER_SIM = 0.72
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
    if verb != "*":
        first = text.split(" ", 1)[0]
        if tools.text_similarity(first, verb) < HOVER_SIM and not text.startswith(verb):
            return False
        rest = text.split(" ", 1)[1] if " " in text else ""
        if verb in ("climb-up", "climb-down", "talk-to", "chop"):
            rest = text  # these verbs have their own words; look at all of it
    else:
        rest = text
    if not name:
        return True
    if len(name) <= 4:
        return name in rest
    sim = max(tools.text_similarity(rest, name),
              max((SequenceMatcher(None, rest[i:i + len(name)], name).ratio()
                   for i in range(0, max(1, len(rest) - len(name) + 1))), default=0.0))
    return sim >= HOVER_SIM


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
        self.human_init()
        try:
            while not self.terminate:
                if self._done():
                    self.log.info("On the mainland: Tutorial Island done.")
                    self.exit_reason = "done"
                    self.counts["done"] = 1
                    return
                res = self._step()
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
        # 2) the appearance screen (no instruction box yet)
        if self._appearance(sc):
            return
        if not low.strip():
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
            self.same += 1
        else:
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
        try:
            handler(low)
        except ScriptTerminationException:
            raise
        except Exception:
            self.log.warning(f"Step '{name}' failed", exc_info=True)
        self._wait_change(key)

    def _key(self, low: str) -> str:
        """The instruction without OCR noise (for 'did it change?')."""
        return re.sub(r"[^a-z]", "", low)[:90]

    def _wait_change(self, key: str):
        end = time.time() + self.cfg.step_wait.value
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
        sc = sc or self.client.get_screenshot()
        box = self._chat_box()
        try:
            ls = lines(words(sc, box, psm=6, min_conf=20))
        except Exception:
            self.log.debug("chat OCR failed", exc_info=True)
            return ""
        self._chat_lines = ls
        return " ".join(l["text"] for l in ls)

    def _chat_box(self):
        try:
            c = self.client.sectors.chat
            if c and c.width > 300 and c.height > 80:
                return (c.start_x, c.start_y, c.end_x, c.end_y)
        except Exception:
            pass
        return CHAT_BOX

    def _is_dialogue(self, low: str) -> bool:
        return "to continue" in low or "select an option" in low

    def _dialogue(self, low: str, sc) -> bool:
        if "select an option" in low:
            return self._choose_option()
        if "to continue" in low:
            time.sleep(self.cfg.continue_pause.choose())
            keyboard.press_and_release("space")
            self.log.debug("Dialogue: space")
            time.sleep(random.uniform(0.3, 0.6))
            # some boxes ignore space: click the line then
            if "to continue" in self.read_chat().lower() and self._key(self.read_chat().lower()) == self._key(low):
                ln = next((l for l in getattr(self, "_chat_lines", []) if "continue" in l["text"].lower()), None)
                if ln:
                    self._click_box(ln)
            return True
        return False

    def _choose_option(self) -> bool:
        ls = getattr(self, "_chat_lines", [])
        idx = next((i for i, l in enumerate(ls) if "select an option" in l["text"].lower()), None)
        if idx is None:
            return False
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
        if pick is None:
            pick = next((i for i, t in enumerate(texts) if not any(n in t for n in never)), 0)
        self.log.info(f"Options {[o['text'] for o in options]}: choosing {pick + 1}")
        time.sleep(self.cfg.continue_pause.choose())
        if random.random() < 0.5:
            keyboard.press_and_release(str(pick + 1))
        else:
            self._click_box(options[pick])
        time.sleep(random.uniform(0.4, 0.8))
        return True

    # ================================================================== rules
    def _rule(self, t: str):
        R = [
            ("appearance", lambda: "appearance" in t and "character" in t, self.do_appearance),
            ("waiting", lambda: "please wait" in t or "sit back" in t or "attempting to" in t
                                or "bar over your head" in t, self.do_wait),
            ("tab", lambda: "flashing" in t or "open up the magic" in t, self.do_tab),
            ("go on", lambda: "if you want a recap" in t, self.do_path),
            ("magic: cast", lambda: "wind strike" in t, self.do_wind_strike),
            ("mainland", lambda: "mainland" in t, self.do_mainland),
            ("fishing", lambda: "fishing spot" in t or ("net" in t and "shrimp" in t), self.do_fish),
            ("woodcutting", lambda: "need some logs" in t or "cut down" in t or "chop" in t, self.do_chop),
            ("firemaking", lambda: "tinderbox" in t, self.do_fire),
            ("cook shrimp", lambda: "shrimp" in t and "cook" in t, self.do_cook_shrimp),
            ("dough", lambda: "dough" in t and ("flour" in t or "mix" in t), self.do_dough),
            ("bake", lambda: "range" in t and ("bread" in t or "dough" in t or "bake" in t), self.do_range),
            ("run", lambda: "run or walk" in t or "running is faster" in t, self.do_run),
            ("smithing menu", lambda: "smithing menu" in t or "list of all the things" in t, self.do_dagger_menu),
            ("anvil", lambda: "anvil" in t and "hammer" in t, self.do_anvil),
            ("smelt", lambda: "smelt" in t and "furnace" in t, self.do_smelt),
            ("mine", lambda: ("mine" in t or "mining" in t) and ("tin" in t or "copper" in t)
                             and "bronze bar" not in t, self.do_mine),
            ("equipment stats", lambda: "worn inventory" in t and "unequip" not in t
                                        and "holding your dagger" not in t, self.do_equipment_stats),
            ("wield dagger", lambda: "equipment stats" in t or ("dagger" in t and "wear" in t), self.do_wield_dagger),
            ("sword and shield", lambda: "unequip" in t, self.do_sword_shield),
            ("bow", lambda: "bow" in t and "arrow" in t, self.do_bow),
            ("attack rat", lambda: "rat" in t and ("slay" in t or "attack" in t), self.do_attack_rat),
            ("first kill", lambda: "first kill" in t, self.do_after_kill),
            ("bank", lambda: "this is your bank" in t, self.do_close_bank),
            ("bank booth", lambda: "bank of gielinor" in t or "front of the building" in t, self.do_bank_booth),
            ("poll booth", lambda: "poll booth" in t and "door" not in t, self.do_poll),
            ("ladder", lambda: "ladder" in t, self.do_ladder),
            ("door", lambda: "door" in t or "gate" in t or "follow the path" in t or "pass through" in t
                             or "continue through" in t, self.do_path),
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
        for name, (_, keys) in TABS.items():
            if any(k in t for k in keys):
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
        verbs = ["Open Door", "Open Gate", "Climb-down Ladder", "Climb-up Ladder", "Enter *"]
        if self.hint_interact(verbs):
            return
        self.walk_to_hint()

    def do_ladder(self, t):
        up = "up" in t and "down" not in t
        verbs = ["Climb-up Ladder"] if up else ["Climb-down Ladder", "Climb-up Ladder"]
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
        # "First up, try mining some tin" / "...you just need some copper"
        if "need some copper" in t:
            ore = "copper"
        elif "need some tin" in t:
            ore = "tin"
        else:
            ore = "tin" if "tin" in t else "copper"
        if self.hint_interact([f"Mine {ore.title()} rocks", f"Mine {ore.title()}", "Mine Rocks"], search=True):
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
        if not self._inv_item("Bronze sword"):
            self.talk(["Combat Instructor"])
            return
        self._wield(["Bronze sword", "Wooden shield"])

    def do_bow(self, t):
        self.ensure_tab("inventory")
        if self._inv_item("Shortbow") or self._inv_item("Bronze arrow"):
            self._wield(["Shortbow", "Bronze arrow"])
        self.attack_rat()

    def do_attack_rat(self, t):
        self.attack_rat()

    def do_after_kill(self, t):
        if not self.hint_interact(["Open Gate"]):
            pass
        time.sleep(random.uniform(1.5, 3.0))
        self.talk(["Combat Instructor"])

    def do_bank_booth(self, t):
        if not self.hint_interact(["Use Bank booth", "Bank Bank booth"], search=True):
            self.walk_to_hint()

    def do_close_bank(self, t):
        self._close_interface()
        time.sleep(random.uniform(0.6, 1.2))
        self.do_poll(t)

    def do_poll(self, t):
        if self._close_interface():
            return
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
        if "teleport" in t and "home" in t:
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
        for box in TAB_ROWS:
            m = self._find_tpl(TABS[name][0], (box[0] - 2, box[1] - 2, box[2] + 2, box[3] + 2), 0.72)
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
        for _ in range(6):
            frames.append(np.asarray(self.client.get_screenshot().convert("L"), dtype=np.int16))
            time.sleep(random.uniform(0.18, 0.26))
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
        # clicking an empty bit of the side panel's frame cancels "Use ... ->"
        try:
            keyboard.press_and_release("esc")
        except Exception:
            pass

    def _wield(self, names: list[str]):
        for n in names:
            m = self._inv_item(n)
            if m is None:
                self.log.info(f"{n}: not in the inventory")
                continue
            self.move_inv(m)
            time.sleep(random.uniform(0.08, 0.15))
            if any(text_matches(h, "Wield *") or text_matches(h, "Wear *") for h in self.client.get_hover_texts()):
                press()
            else:
                self.click_inv(m)
            time.sleep(random.uniform(0.6, 1.0))

    # ================================================================== world clicks
    def _player_point(self) -> tuple[int, int]:
        x1, y1, x2, y2 = VIEW
        return (x1 + x2) // 2, (y1 + y2) // 2 + 8

    def find_hint(self, sc=None) -> MatchResult | None:
        """The yellow hint arrow in the game view (biggest yellow blob)."""
        sc = sc or self.client.get_screenshot()
        x1, y1, x2, y2 = VIEW
        mask = hue_mask(sc.crop(VIEW), self.cfg.hint_color.value, self.cfg.hint_hue_tol.value)
        mask = cv2.dilate(mask.astype(np.uint8), np.ones((3, 3), np.uint8))
        num, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        best = None
        for i in range(1, num):
            x, y, w, h, area = (int(v) for v in stats[i])
            if area < self.cfg.hint_min_pixels.value or w < 6 or h < 6 or w > 90 or h > 90:
                continue
            if best is None or area > best[0]:
                best = (area, MatchResult(x1 + x, y1 + y, x1 + x + w, y1 + y + h))
        return best[1] if best else None

    def find_minimap_hint(self, sc=None) -> tuple[float, float] | None:
        sc = sc or self.client.get_screenshot()
        try:
            mm = self.client.minimap.map
            box = mm.bounding_box
        except Exception:
            return None
        mask = hue_mask(sc.crop(box), self.cfg.hint_color.value, self.cfg.hint_hue_tol.value, 120, 120)
        num, _, stats, cent = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
        best = None
        for i in range(1, num):
            area = int(stats[i][4])
            if area >= self.cfg.hint_min_pixels_minimap.value and (best is None or area > best[0]):
                best = (area, (box[0] + float(cent[i][0]), box[1] + float(cent[i][1])))
        return best[1] if best else None

    def hover_click(self, pt, wanted: list[str]) -> bool:
        self.client.move_to(pt)
        time.sleep(random.uniform(0.06, 0.13))
        answers = self.client.get_hover_texts()
        if any(text_matches(a, w) for a in answers for w in wanted):
            click(-1, -1)
            self.log.info(f"Clicked {answers} for {wanted}")
            time.sleep(self.cfg.action_pause.choose())
            return True
        self.log.debug(f"Mouse-over {answers} isn't {wanted}")
        return False

    def hint_interact(self, wanted: list[str], search: bool = False) -> bool:
        """Under the hint arrow: move down from its tip until the mouse-over says one of
        `wanted`, then click. `search`: no arrow / nothing there -> look around the
        character with the mouse."""
        hint = self.find_hint()
        if hint is not None:
            cx = (hint.start_x + hint.end_x) // 2
            depth = self.cfg.hint_search_depth.value
            for dy in range(6, depth, 9):
                pt = (cx + random.randint(-4, 4), min(VIEW[3] - 2, hint.end_y + dy))
                if self.hover_click(pt, wanted):
                    return True
            self.log.info(f"Hint arrow at {hint.bounding_box}: nothing {wanted} under it")
            # far away: walk to it
            self.client.click((cx + random.randint(-5, 5), min(VIEW[3] - 2, hint.end_y + random.randint(25, 45))))
            self.sleep_checked(random.uniform(2.0, 3.5))
            return False
        if search:
            return self.hover_search(wanted)
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
        for pt in pts[: self.cfg.hover_search_points.value]:
            if self.terminate:
                raise ScriptTerminationException()
            if self.hover_click(pt, wanted):
                return True
        self.log.info(f"Mouse-over search: no {wanted} around the character")
        return False

    def hover_scan_panel(self, wanted: list[str]) -> bool:
        x1, y1, x2, y2 = SIDE_PANEL
        for y in range(y1 + 8, y1 + 80, 24):
            for x in range(x1 + 8, x2 - 8, 24):
                if self.hover_click((x + random.randint(-3, 3), y + random.randint(-3, 3)), wanted):
                    return True
        return False

    def walk_to_hint(self) -> bool:
        """No arrow on screen: walk toward the minimap's hint arrow."""
        hint = self.find_hint()
        if hint is not None:
            cx = (hint.start_x + hint.end_x) // 2
            self.client.click((cx + random.randint(-6, 6), min(VIEW[3] - 2, hint.end_y + random.randint(25, 45))))
            self.sleep_checked(random.uniform(2.5, 4.0))
            return True
        mh = self.find_minimap_hint()
        if mh is None:
            self.log.info("No hint arrow on the screen or the minimap")
            return False
        mm = self.client.minimap.map
        cx, cy = mm.get_center()
        dx, dy = mh[0] - cx, mh[1] - cy
        d = math.hypot(dx, dy)
        r = min(mm.width, mm.height) / 2 - 12
        k = min(1.0, r / d) if d else 0
        pt = (int(cx + dx * k + random.uniform(-3, 3)), int(cy + dy * k + random.uniform(-3, 3)))
        self.log.info(f"Walking toward the minimap hint arrow ({pt})")
        self.client.click(pt)
        self.sleep_checked(random.uniform(3.0, 5.0))
        return True

    # ------------------------------------------------------------------ NPCs
    def find_npcs(self) -> list[MatchResult]:
        sc = self.client.get_screenshot()
        arr = np.asarray(sc.convert("RGB").crop(VIEW), dtype=np.int16)
        tol = self.cfg.color_tolerance.value
        mask = np.zeros(arr.shape[:2], dtype=bool)
        for c in self.cfg.npc_colors.value:
            mask |= np.all(np.abs(arr - np.array(c.value)) <= tol, axis=2)
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

    def click_npc(self, wanted: list[str], verb_any: bool = False) -> bool:
        for m in self.find_npcs()[:6]:
            inner = m.scale_px(-max(2, min(m.width, m.height) // 5))
            for _ in range(2):
                if self.hover_click(inner.get_point_within(), wanted):
                    return True
        # NPC not highlighted / off screen: the hint arrow may stand over it
        return self.hint_interact(wanted, search=True)

    def talk(self, names: list[str]) -> bool:
        wanted = [f"Talk-to {n}" for n in names]
        if self.click_npc(wanted):
            self.sleep_checked(random.uniform(1.2, 2.5))
            return True
        self.walk_to_hint()
        return False

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
    def _close_interface(self) -> bool:
        """Close a window (bank, poll, equipment stats) with its X button."""
        m = self._find_tpl("data/ui/close-ui-element.png", VIEW, 0.8)
        if m is None:
            return False
        self.client.click(m.scale_px(-1).get_point_within())
        time.sleep(random.uniform(0.5, 0.9))
        self.log.info("Closed a window")
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
