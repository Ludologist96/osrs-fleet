"""
Fleet launcher: start a bot on several slots, spread out in time, and stop each
one after its run time. Used by the dashboard (/launcher page, /api/launch).

A plan is saved to STATE_FILE so a dashboard restart (e.g. `fleetctl update`)
doesn't forget when bots must stop.

For each slot the launcher:
  1. makes sure the slot (screen + RuneLite + bot app) is running,
  2. waits for RuneLite to show a saved login (window title "RuneLite - <name>"),
  3. asks the slot's bot app to log in (Play Now / CLICK HERE TO PLAY),
  4. starts the chosen bot with that slot's saved settings,
  5. stops the bot when its time is up (the bot then logs the character out).
"""

from __future__ import annotations

import glob
import os
import html as _html
import json
import random
import re
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

STATE_FILE = Path("/var/lib/osrs/launch.json")

# Spread-out starts: wait this many seconds between two slots, and vary each
# slot's run time by this fraction (0.1 = +-10%).
SPREAD_GAP = (60, 240)
SPREAD_RUNTIME = 0.10

_lock = threading.RLock()

# Pseudo-bot: only log the accounts in (random F2P world) so you can move them
# by hand in the screen view. No bot runs; "Stop" just ends the entry.
FREEROAM = "freeroam"
FREEROAM_DEFAULT_MINUTES = 24 * 60

# F2P worlds: normal ones (no activity / skill total / PvP) in these countries.
WORLD_COUNTRIES = ("Germany", "United Kingdom")
WORLD_LIST_URL = "https://oldschool.runescape.com/slu"
# Used when the official world list can't be read (Germany + UK, Oct 2026).
FALLBACK_F2P_WORLDS = [335, 384, 397, 399, 451, 452, 453, 454, 455, 456,
                       552, 553, 554, 555, 380, 382, 498, 499]
_worlds_cache: dict = {"at": 0.0, "worlds": []}


def f2p_worlds() -> list[int]:
    """Normal free-to-play worlds in WORLD_COUNTRIES, from the official list (cached 1 h)."""
    if time.time() - _worlds_cache["at"] < 3600 and _worlds_cache["worlds"]:
        return _worlds_cache["worlds"]
    worlds: list[int] = []
    try:
        req = urllib.request.Request(WORLD_LIST_URL, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            page = r.read().decode("utf-8", "replace")
        for row in re.findall(r"<tr[^>]*>(.*?)</tr>", page, re.S):
            m = re.search(r"world=(\d+)", row)
            cells = [_html.unescape(re.sub(r"<[^>]+>", "", c)).strip()
                     for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
            if not m or len(cells) < 5:
                continue
            location, kind, activity = cells[2], cells[3], cells[4]
            if kind == "Free" and activity in ("-", "") and location in WORLD_COUNTRIES:
                worlds.append(int(m.group(1)))
    except Exception as e:
        print(f"world list not readable ({e!r}); using the built-in list", flush=True)
    worlds = worlds or FALLBACK_F2P_WORLDS
    _worlds_cache.update(at=time.time(), worlds=worlds)
    return worlds


def set_login_world(n: int, world: int) -> int:
    """Make slot N's RuneLite open on `world` (Default World plugin). RuneLite must be
    stopped: it writes its settings back when it exits. Returns files changed."""
    return set_rl_settings(n, {"defaultworld.defaultWorld": str(world), "defaultworld.useLastWorld": "false",
                               "runelite.defaultworldplugin": "true"})


def _argb(rgb) -> str:
    r, g, b = (int(c) for c in rgb)
    v = (0xFF << 24) | (r << 16) | (g << 8) | b
    return str(v - (1 << 32))  # Java int (signed)


def read_rl_settings(n: int) -> dict:
    """Slot N's RuneLite settings (main profile, not the per-account files)."""
    out = {}
    for f in glob.glob(f"/home/bot{n}/.runelite/profiles2/*.properties"):
        if "$rsprofile" in os.path.basename(f):
            continue
        for line in Path(f).read_text(errors="replace").splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
    return out


def _set_spots(cfg: dict, spots: dict) -> None:
    """Put a run's remembered tiles into the bot config it is started with (empty = the
    bot takes the tile where it stands). Saved settings are not changed."""
    for key, field in (("home", "home_tile"), ("fire", "fire_tile")):
        f = cfg.get(field)
        if isinstance(f, dict) and "value" in f:
            f["value"] = spots.get(key, "")


def bot_rl_settings(bot: str, cfg: dict, current: dict) -> dict:
    """RuneLite settings a bot needs, made from its saved config (so its targets/loot
    are set in one place: the bot's settings)."""
    # every bot: the World Location plugin (Plugin Hub) shows the character's tile in the
    # top-left corner (core/position.py reads it to walk back to the work area)
    hub = [p.strip() for p in current.get("runelite.externalPlugins", "").split(",") if p.strip()]
    loc = {"runelite.externalPlugins": ",".join(hub + [p for p in ["world-location"] if p not in hub]),
           "runelite.worldlocationplugin": "true", "worldlocation.gridInfo": "true",
           "worldlocation.gridInfoType": "UNIQUE_ID",
           # no coordinates line in the mouse-over tooltip (the hover-text readers OCR it)
           "worldlocation.tileLocation": "false",
           # minimap at a known zoom: walking clicks it at 4 px per tile (slot 8 had 2.0
           # and every walk went twice as far as wanted)
           "minimap.zoom": "true", "minimap.zoomLevel": "4.0"}
    if bot not in ("slayer", "woodcutter"):
        return {}
    if bot == "woodcutter":
        val = lambda k, d=None: (cfg.get(k) or {}).get("value", d)
        if val("drop_items", True) is False:
            # bank mode: the bot opens the bank on a banker - highlight them
            want = dict(loc)
            want.update({"runelite.npcindicatorsplugin": "true", "npcindicators.highlightHull": "true",
                         "npcindicators.npcToHighlight": "Banker"})
            bt = val("bank_tile")
            if bt:
                want["npcindicators.npcColor"] = _argb(bt["rgb"])
            return want
        return loc
    if bot != "slayer":
        return loc
    val = lambda k, d=None: (cfg.get(k) or {}).get("value", d)
    want = dict(loc)
    want.update({"runelite.npcindicatorsplugin": "true", "runelite.opponentinfoplugin": "true",
            "npcindicators.highlightHull": "true", "npcindicators.ignoreDeadNpcs": "true",
            "opponentinfo.showOpponentHealthOverlay": "true"})
    targets = val("targets") or []
    if targets:
        want["npcindicators.npcToHighlight"] = ", ".join(targets)
    colors = val("npc_colors") or []
    if colors:
        want["npcindicators.npcColor"] = _argb(colors[0]["value"]["rgb"])
    if val("loot", True):
        loot = list(val("loot_use") or []) + list(val("loot_keep") or [])
        hidden = [h.strip() for h in current.get("grounditems.hiddenItems", "").split(",") if h.strip()]
        lower = {x.lower() for x in loot}
        want.update({
            "runelite.grounditemsplugin": "true",
            "grounditems.highlightedItems": ", ".join(loot),
            "grounditems.hiddenItems": ", ".join(h for h in hidden if h.lower() not in lower),
            "grounditems.highlightTiles": "true",
            "grounditems.ownershipFilterMode": "TAKEABLE",
            # only the wanted items are drawn: otherwise a pile's tile outline takes the colour
            # of a pricier unwanted item on it (cowhide) and the bones only show as a name
            "grounditems.showHighlightedOnly": "true",
        })
        lc = val("loot_color")
        if lc:
            want["grounditems.highlightedColor"] = _argb(lc["rgb"])
    return want


SCREEN_W, SCREEN_H = 1280, 800


def fit_window(n: int) -> bool:
    """Move slot N's RuneLite window back onto its screen if part of it is off-screen
    (bots click inside the window; a window hanging off the edge gets misclicks).
    Returns True when it was moved."""
    env = dict(os.environ, DISPLAY=f":{n}")
    try:
        wid = subprocess.run(["xdotool", "search", "--name", "^RuneLite"], capture_output=True,
                             text=True, env=env, timeout=5).stdout.split()[0]
        out = subprocess.run(["xdotool", "getwindowgeometry", "--shell", wid], capture_output=True,
                             text=True, env=env, timeout=5).stdout
    except (IndexError, subprocess.SubprocessError):
        return False
    g = dict(l.split("=", 1) for l in out.splitlines() if "=" in l)
    try:
        x, y, w, h = (int(g[k]) for k in ("X", "Y", "WIDTH", "HEIGHT"))
    except (KeyError, ValueError):
        return False
    if x >= 0 and y >= 0 and x + w <= SCREEN_W and y + h <= SCREEN_H:
        return False
    nx, ny = max(0, (SCREEN_W - w) // 2), max(0, (SCREEN_H - h) // 2)
    subprocess.run(["xdotool", "windowmove", wid, str(nx), str(ny)], env=env, capture_output=True, timeout=5)
    return True


def set_rl_settings(n: int, wanted: dict, all_profiles: bool = True) -> int:
    """Write RuneLite settings (key=value) into slot N's profile files. RuneLite must be
    stopped. all_profiles=False skips the per-account $rsprofile files. Returns files changed."""
    home = f"/home/bot{n}/.runelite"
    files = glob.glob(f"{home}/profiles2/*.properties") + glob.glob(f"{home}/settings.properties")
    if not all_profiles:
        files = [f for f in files if "$rsprofile" not in os.path.basename(f)]
    for f in files:
        lines = Path(f).read_text(errors="replace").splitlines()
        seen = set()
        for i, line in enumerate(lines):
            key = line.split("=", 1)[0].strip()
            if key in wanted:
                lines[i] = f"{key}={wanted[key]}"
                seen.add(key)
        lines += [f"{k}={v}" for k, v in wanted.items() if k not in seen]
        Path(f).write_text("\n".join(lines) + "\n")
    return len(files)


def _http(method: str, url: str, body: dict | None = None, timeout: float = 10):
    data = json.dumps(body).encode() if body is not None else (b"{}" if method == "POST" else None)
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read() or b"null")


def _app(n: int) -> str:
    return f"http://127.0.0.1:{8010 + n}"


class Launcher:
    def __init__(self, window_title: Callable[[int], str], slots: int):
        self.window_title = window_title
        self.slots = slots
        self.runs: dict[str, dict] = {}
        self.last: dict[str, dict] = {}  # per slot: the bot + run time of its last launch
        # the dashboard restarts with every code update (fleetctl update), right after the
        # bot apps: bots found stopped in the first minutes were stopped by that update
        self.started_at = time.time()
        self._load()
        threading.Thread(target=self._loop, daemon=True, name="launcher").start()

    # ------------------------------------------------------------ state
    def _load(self):
        try:
            data = json.loads(STATE_FILE.read_text())
            self.runs = data.get("runs", {})
            self.last = data.get("last", {})
            self.setup_done = data.get("setup_done", {})
            for k, r in self.runs.items():  # runs from before this was kept
                if k not in self.last and r.get("bot") and r["bot"] != FREEROAM:
                    self.last[k] = {"bot": r["bot"], "minutes": round((r["stop_at"] - r["start_at"]) / 60)}
            # a start that was in progress when the dashboard restarted: retry it
            for r in self.runs.values():
                if r["status"] == "starting":
                    r["status"] = "waiting"
                r["resuming"] = False
        except FileNotFoundError:
            self.runs = {}
        except Exception:
            self.runs = {}
        if not hasattr(self, "setup_done"):
            self.setup_done = {}

    def _save(self):
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps({"runs": self.runs, "last": self.last,
                                   "setup_done": self.setup_done}, indent=1))
        tmp.replace(STATE_FILE)

    def _set(self, n: int, **kw):
        with _lock:
            self.runs[str(n)].update(kw)
            self._save()

    # ------------------------------------------------------------ API
    def status(self) -> dict:
        now = time.time()
        with _lock:
            out = {}
            for k, r in sorted(self.runs.items(), key=lambda kv: int(kv[0])):
                r = dict(r)
                r["starts_in"] = max(0, int(r["start_at"] - now))
                r["stops_in"] = max(0, int(r["stop_at"] - now))
                r["activity"] = self._activity(r)
                out[k] = r
            return {"now": now, "runs": out, "last": dict(self.last)}

    def launch(self, slots: list[int], bot: str, minutes: float, spread: bool = True) -> dict:
        slots = [n for n in slots if 1 <= n <= self.slots]
        if bot == FREEROAM:
            spread = False  # log everyone in right away
            minutes = minutes or FREEROAM_DEFAULT_MINUTES
        if not slots or minutes <= 0 or not bot:
            raise ValueError("choose at least one slot, a bot and a run time")
        with _lock:
            busy = [n for n in slots if self.runs.get(str(n), {}).get("status") in ("waiting", "starting", "running")]
            if busy:
                raise ValueError(f"slots already launched: {busy} (stop them first)")
            t = time.time()
            for i, n in enumerate(slots):
                if i and spread:
                    t += random.uniform(*SPREAD_GAP)
                run_s = minutes * 60
                if spread:
                    run_s *= random.uniform(1 - SPREAD_RUNTIME, 1 + SPREAD_RUNTIME)
                self.runs[str(n)] = {
                    "slot": n, "bot": bot, "start_at": t, "stop_at": t + run_s,
                    "status": "waiting", "msg": "", "account": self.window_title(n)[len("RuneLite - "):],
                }
                if bot != FREEROAM:  # the launcher preselects this next time the account is chosen
                    self.last[str(n)] = {"bot": bot, "minutes": minutes}
            self._save()
        return self.status()

    def stop(self, slots: list[int] | None = None) -> dict:
        with _lock:
            targets = [int(k) for k in self.runs] if not slots else slots
            for n in targets:
                r = self.runs.get(str(n))
                if not r or r["status"] in ("done", "error", "stopped", "dead"):
                    continue
                if r["status"] == "running" and r["bot"] != FREEROAM:
                    self._final_counts(n, r)
                    self._stop_bot(n, r["bot"])
                r.update(status="stopped", msg="stopped by you", stop_at=time.time())
                r.pop("activity_now", None)
            self._save()
        return self.status()

    def clear_finished(self) -> dict:
        with _lock:
            self.runs = {k: r for k, r in self.runs.items()
                         if r["status"] in ("waiting", "starting", "running")}
            self._save()
        return self.status()

    # ------------------------------------------------------------ worker
    def _loop(self):
        while True:
            try:
                self._tick()
            except Exception as e:  # never let the worker die
                print(f"launcher tick failed: {e!r}", flush=True)
            time.sleep(3)

    def _tick(self):
        now = time.time()
        with _lock:
            todo = [(int(k), dict(r)) for k, r in self.runs.items()]
        for n, r in todo:
            if r["status"] == "waiting" and now >= r["start_at"]:
                self._set(n, status="starting", msg="starting")
                threading.Thread(target=self._start, args=(n, r["bot"]), daemon=True).start()
            elif r["status"] == "running" and not r.get("resuming"):
                if now >= r["stop_at"]:
                    if r["bot"] == FREEROAM:
                        self._set(n, status="done", msg="free roam over")
                        continue
                    with _lock:
                        self._final_counts(n, self.runs[str(n)])
                    self._stop_bot(n, r["bot"])
                    self._set(n, status="done", msg="run time over, bot stopped", activity_now=None)
                elif r["bot"] == FREEROAM:
                    continue
                else:
                    info = self._bot_info(n, r["bot"])
                    st = info.get("status") if info else None
                    if info:
                        self._note_info(n, info)
                    if st not in ("running", "paused", None) and info.get("reason") == "died":
                        # leave a dead character alone (no restart); Telegram sends an alert
                        self._set(n, status="dead", msg="the character died; bot stopped, left it there",
                                  activity_now=None, ran_s=time.time() - r.get("began_at", r["start_at"]))
                    elif st not in ("running", "paused", None):
                        # stopped unexpectedly (bot app restarted by an update, or a crash):
                        # start it again a few times before giving up
                        # count only restarts close together (a crash loop), not one per update
                        restarts = r.get("restarts", 0) if now - r.get("last_restart", 0) < 900 else 0
                        by_update = now - self.started_at < 240  # a code update, not a crash
                        if by_update or restarts < 3:
                            self._set(n, restarts=restarts if by_update else restarts + 1,
                                      last_restart=r.get("last_restart", 0) if by_update else now, resuming=True,
                                      msg=f"bot stopped ({st}); restarting it")
                            threading.Thread(target=self._resume, args=(n, r["bot"]), daemon=True).start()
                        else:
                            self._set(n, status="error", msg=f"bot stopped on its own ({st}) 3 times; see its log",
                                      activity_now=None, ran_s=time.time() - r.get("began_at", r["start_at"]))

    def _cancelled(self, n: int) -> bool:
        with _lock:
            return self.runs.get(str(n), {}).get("status") != "starting"

    def _fresh_client(self, n: int, rl_change: dict | None = None):
        """Restart RuneLite on a random F2P world. A fresh start also downloads the
        newest RuneLite client, which is needed after a game update: a client opened
        before the update can't log in any more."""
        world = random.choice(f2p_worlds())
        self._set(n, msg=f"restarting RuneLite on world {world}", world=world)
        subprocess.run(["systemctl", "stop", f"osrs-client@{n}.service"], capture_output=True)
        if not set_login_world(n, world):
            raise RuntimeError("RuneLite settings not found for this slot")
        if rl_change:
            set_rl_settings(n, rl_change, all_profiles=False)
        subprocess.run(["systemctl", "start", f"osrs-client@{n}.service"], capture_output=True)
        time.sleep(5)
        for _ in range(60):
            if self.window_title(n).startswith("RuneLite - "):
                break
            time.sleep(3)
        time.sleep(15)  # let the login screen finish loading

    def _account_setup(self, n: int):
        """Once per account: game settings the bots need (level-up pop-ups off).
        Kept in the state file by account name; a failure is retried on the next launch."""
        acct = self.runs.get(str(n), {}).get("account") or ""
        if not acct or "levelup" in self.setup_done.get(acct, []):
            return
        self._set(n, msg="turning level-up pop-ups off (once per account)")
        try:
            res = _http("POST", f"{_app(n)}/api/session/setup?what=levelup", timeout=90)
        except Exception as e:
            res = {"ok": False, "error": str(e)}
        if res.get("ok"):
            with _lock:
                self.setup_done.setdefault(acct, []).append("levelup")
                self._save()
        else:
            self._set(n, msg=f"couldn't turn level-up pop-ups off ({res.get('error')}); trying next launch")

    def _login(self, n: int, what: str, cancellable: bool = False):
        """Log the slot in. If that fails, restart RuneLite (e.g. the game was updated
        while this client was open) and try once more."""
        st = _http("POST", f"{_app(n)}/api/session/login", timeout=150)
        if st.get("state") == "game":
            return
        first = st.get("error") or st.get("state")
        if cancellable and self._cancelled(n):
            return
        self._set(n, msg=f"login failed ({first}): restarting RuneLite and trying again")
        self._fresh_client(n)
        if cancellable and self._cancelled(n):
            return
        self._set(n, msg="logging in (2nd try)")
        st = _http("POST", f"{_app(n)}/api/session/login", timeout=150)
        if st.get("state") != "game":
            raise RuntimeError(f"{what} ({st.get('error') or st.get('state')})")

    def _start(self, n: int, bot: str):
        try:
            # 1. slot running
            subprocess.run(["systemctl", "start", f"osrs-slot@{n}.target"], capture_output=True)
            # 2. RuneLite up with a saved login
            title = ""
            for _ in range(60):
                title = self.window_title(n)
                if title.startswith("RuneLite - "):
                    break
                time.sleep(3)
            else:
                raise RuntimeError("RuneLite has no saved login (copy the account's login to this slot)")
            # bot app up
            for _ in range(40):
                try:
                    _http("GET", f"{_app(n)}/api/bots/status", timeout=3)
                    break
                except Exception:
                    time.sleep(3)
            # RuneLite settings this bot needs (e.g. slayer: which monsters/loot to highlight)
            rl_change = {}
            if bot != FREEROAM:
                try:
                    bcfg = _http("GET", f"{_app(n)}/api/bot/{bot}/config")
                    cur = read_rl_settings(n)
                    rl_change = {k: v for k, v in bot_rl_settings(bot, bcfg, cur).items() if cur.get(k) != v}
                except Exception as e:
                    self._set(n, msg=f"couldn't read the bot's settings ({e})")
            # 3. not in game yet (or RuneLite settings to change): restart RuneLite on a
            #    random F2P world, then log in
            st = _http("GET", f"{_app(n)}/api/session/state", timeout=20)
            if st.get("state") != "game" or rl_change:
                self._fresh_client(n, rl_change)
            if self._cancelled(n):
                return
            self._set(n, msg="logging in")
            self._login(n, "couldn't get into the game", cancellable=True)
            if self._cancelled(n):
                return
            # 4. start the bot with this slot's saved settings (unless Stop was pressed meanwhile)
            if self._cancelled(n):
                return
            if fit_window(n):
                self._set(n, msg="RuneLite window was partly off-screen: moved it back")
            self._account_setup(n)
            if bot == FREEROAM:
                with _lock:
                    r = self.runs[str(n)]
                    where = f" on world {r['world']}" if r.get("world") else ""
                    r.update(status="running", msg=f"logged in{where}: free roam, move it by hand")
                    self._save()
                return
            self._set(n, msg=f"starting {bot}")
            cfg = _http("GET", f"{_app(n)}/api/bot/{bot}/config")
            # a new run: the start area is wherever the character stands now
            _set_spots(cfg, {})
            self._set(n, spots={})
            res = _http("POST", f"{_app(n)}/api/bot/{bot}/start", {"config": cfg}, timeout=60)
            if not res.get("success"):
                raise RuntimeError(f"bot didn't start: {res.get('error')}")
            # run time counts from the real start
            with _lock:
                r = self.runs[str(n)]
                r["stop_at"] = time.time() + (r["stop_at"] - r["start_at"])
                where = f" on world {r['world']}" if r.get("world") else ""
                r.update(status="running", msg=f"{bot} running{where}", began_at=time.time(), counts={},
                         counts_raw={}, counts_base={})
                self._save()
        except Exception as e:
            if not self._cancelled(n):
                self._set(n, status="error", msg=str(e))

    def _resume(self, n: int, bot: str):
        try:
            self._login(n, "couldn't get back into the game")
            cfg = _http("GET", f"{_app(n)}/api/bot/{bot}/config")
            # a restart (update / crash) in the middle of a run: keep the run's start area
            # and fire spot (the bot walks back there first)
            _set_spots(cfg, (self.runs.get(str(n)) or {}).get("spots") or {})
            res = _http("POST", f"{_app(n)}/api/bot/{bot}/start", {"config": cfg}, timeout=60)
            if not res.get("success"):
                raise RuntimeError(f"bot didn't start: {res.get('error')}")
            self._set(n, msg=f"{bot} running (restarted)", resuming=False)
        except Exception as e:
            self._set(n, msg=f"restart failed: {e}", resuming=False)

    @staticmethod
    def _activity(r: dict) -> str:
        """What the account is doing, for the launcher page and Telegram."""
        st = r.get("status")
        if st == "running":
            if r.get("bot") == FREEROAM:
                return "free roam"
            if r.get("resuming"):
                return "restarting"
            return r.get("activity_now") or "working"
        if st == "starting":
            return "logging in" if "log" in (r.get("msg") or "") else "starting"
        return st or ""

    def _note_info(self, n: int, info: dict):
        """Remember the bot's current activity and counters (no file write for the
        activity alone - it changes often; counters are saved with the next save)."""
        with _lock:
            r = self.runs.get(str(n))
            if not r or r.get("status") != "running":
                return
            if info.get("activity"):
                r["activity_now"] = info["activity"]
            sp = info.get("spots")
            if isinstance(sp, dict) and sp and sp != r.get("spots"):
                r["spots"] = sp  # where this run started / lights fires: kept for restarts
                self._save()
            c = info.get("counts")
            if isinstance(c, dict) and c != r.get("counts_raw"):
                raw = r.get("counts_raw") or {}
                if sum(c.values()) < sum(raw.values()):
                    # the bot was restarted (update / crash): its counters start again at 0
                    base = r.get("counts_base") or {}
                    r["counts_base"] = {k: base.get(k, 0) + raw.get(k, 0) for k in set(base) | set(raw)}
                r["counts_raw"] = c
                base = r.get("counts_base") or {}
                r["counts"] = {k: base.get(k, 0) + c.get(k, 0) for k in set(base) | set(c)}
                self._save()

    def _final_counts(self, n: int, r: dict):
        """Before stopping a bot: keep its last counters and how long it ran."""
        info = self._bot_info(n, r["bot"])
        if info and isinstance(info.get("counts"), dict) and info["counts"]:
            base = r.get("counts_base") or {}
            c = info["counts"]
            r["counts"] = {k: base.get(k, 0) + c.get(k, 0) for k in set(base) | set(c)}
        r["ran_s"] = time.time() - r.get("began_at", r["start_at"])

    def _bot_info(self, n: int, bot: str) -> dict | None:
        try:
            return _http("GET", f"{_app(n)}/api/bot/{bot}/status", timeout=4)
        except Exception:
            return None  # app restarting (e.g. update): don't count as a failure

    def _bot_status(self, n: int, bot: str):
        try:
            return _http("GET", f"{_app(n)}/api/bot/{bot}/status", timeout=4).get("status")
        except Exception:
            return None  # app restarting (e.g. update): don't count as a failure

    def _stop_bot(self, n: int, bot: str):
        try:
            _http("POST", f"{_app(n)}/api/bot/{bot}/stop", timeout=10)
        except Exception:
            pass
