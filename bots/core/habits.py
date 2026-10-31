"""Player habits shared by EVERY bot (Igor's rule, Oct 2026).

Every bot's config inherits these fields:

    from bots.core.habits import HabitsConfig
    class BotConfig(HabitsConfig): ...

and its executor uses `core.human.HumanMixin` (`class BotExecutor(HumanMixin, Bot)`), which
reads them: breaks (short + long, side-panel browsing), alt-tabs, misclicks, quick/double
clicks, short extra pauses, camera fidgets, walk-aways. Change a default HERE and every bot
gets it; a new habit goes into core/human.py + a field here, then gets wired into every bot.
A bot may override a field (same name in its own BotConfig) only for a real reason, written
next to it.

Accounts keep their saved settings per bot (data/configs/slotN/), so a changed default
reaches an account that already ran the bot only after its saved value is updated too.
"""
from bots.core.config import BotConfigMixin
from bots.core.cfg_types import BreakCfgParam, FloatParam, IntParam, RangeParam


class HabitsConfig(BotConfigMixin):
    # --- breaks (Bot / ScriptControl) ---
    break_cfg: BreakCfgParam = BreakCfgParam(
        RangeParam(12, 40),  # break duration range in seconds
        FloatParam(0.012)    # break chance per check
    )
    # Chance a short break is spent looking through the side-panel tabs
    # (skills, quests, equipment...) before going back to the inventory.
    break_ui_browse_chance: FloatParam = FloatParam(0.5)
    # Long break: AFK long enough to get logged out (logs back in after),
    # at most once every 90 minutes.
    long_break_cfg: BreakCfgParam = BreakCfgParam(
        RangeParam(1500, 2000),  # 25-33 minutes, logged out
        FloatParam(0.014)
    )
    # Forced long break after this much play (minutes) without one.
    session_max_minutes: IntParam = IntParam(210)

    # --- alt-tab: 1-2 s after a main action, sometimes look at another window a while ---
    alt_tab_chance: FloatParam = FloatParam(0.2)  # per roll: short 18.7% (doubled twice), medium 1.3%
    alt_tab_cooldown: FloatParam = FloatParam(60.0)        # s between two rolls
    alt_tab_short: RangeParam = RangeParam(4.0, 18.0)       # s
    alt_tab_medium: RangeParam = RangeParam(25.0, 90.0)     # s
    alt_tab_medium_chance: FloatParam = FloatParam(0.066)

    # --- walk-away: after a finished cycle, sometimes a few steps via the minimap ---
    walk_away_chance: FloatParam = FloatParam(0.0)        # off until pathfinding exists (it got the bots lost)
    walk_away_cooldown: FloatParam = FloatParam(300.0)     # s
    walk_away_tiles: RangeParam = RangeParam(3, 8)
    walk_away_pause: RangeParam = RangeParam(0.8, 2.2)

    # --- clicks ---
    # Rarely click a little next to the target, then click the target again.
    misclick_chance: FloatParam = FloatParam(0.03)
    # A quick click is sometimes a fast double click.
    double_click_chance: FloatParam = FloatParam(0.40)
    double_click_gap: RangeParam = RangeParam(0.08, 0.16)  # s between the two clicks
    # After a click, sometimes a short extra pause.
    micro_idle_chance: FloatParam = FloatParam(0.07)
    micro_idle: RangeParam = RangeParam(0.25, 0.9)

    # --- camera: after a finished action, this chance to rotate / zoom a bit ---
    camera_chance: FloatParam = FloatParam(0.10)
    camera_force_every: IntParam = IntParam(10)  # actions without a fidget: force one
    camera_rotate_time: RangeParam = RangeParam(0.3, 1.2)  # seconds holding an arrow key (~3 s = full turn)
    camera_zoom_chance: FloatParam = FloatParam(0.5)       # chance a fidget also zooms
    zoom_min: IntParam = IntParam(-4)  # wheel notches out from the starting zoom (limit)
    zoom_max: IntParam = IntParam(3)   # wheel notches in from the starting zoom (limit)
    start_zoom_in: IntParam = IntParam(14)  # start view: fully out, then this many notches in
