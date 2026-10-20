"""
OSRS fleet Telegram bot: start, watch and stop the fleet's bots from the phone.

Runs on the fleet VM as the osrs-telegram service (next to the dashboard) and
does everything through the dashboard's API (http://127.0.0.1:8000), so it
works exactly like the launcher page.

* Token: fleet/telegram/config.ini in the Windows code folder (D:\\osrs-fleet),
  [telegram] token = ...  (never committed - .gitignore). Read again every
  minute until it is there, so no restart is needed after adding it.
* Answers only the owner: the first private chat that writes to it
  (saved in /var/lib/osrs/telegram.json).
* Messages without asking: a run finished, a bot stopped on its own and is
  restarted (or gave up after 3 tries), a login failed.

Only the standard library + Pillow (in the bot venv) for the screens picture.
"""

from __future__ import annotations

import configparser
import io
import json
import math
import re
import sys
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
STATE_FILE = Path("/var/lib/osrs/telegram.json")
FLEET_CONF = Path("/etc/osrs/fleet.conf")
SOURCE_DIR_FILE = Path("/etc/osrs/source_dir")


def say(msg: str):
    print(time.strftime("[%H:%M:%S] ") + msg, flush=True)


def read_conf() -> dict:
    conf = {"DASHBOARD_PORT": "8000"}
    try:
        for line in FLEET_CONF.read_text().splitlines():
            m = re.match(r'\s*([A-Z_]+)=(.*)', line)
            if m:
                conf[m.group(1)] = m.group(2).strip().strip('"')
    except OSError:
        pass
    return conf


DASH = f"http://127.0.0.1:{read_conf().get('DASHBOARD_PORT', '8000')}"


def config_files() -> list[Path]:
    """config.ini in the Windows code folder first (where Igor puts it), then the VM copy."""
    out = []
    try:
        out.append(Path(SOURCE_DIR_FILE.read_text().strip()) / "fleet" / "telegram" / "config.ini")
    except OSError:
        pass
    out.append(HERE / "config.ini")
    return out


def read_token() -> str:
    for f in config_files():
        if f.is_file():
            cfg = configparser.ConfigParser(interpolation=None)
            try:
                cfg.read(f, encoding="utf-8-sig")
                tok = cfg.get("telegram", "token", fallback="").strip()
            except configparser.Error:
                tok = ""
            if re.fullmatch(r"\d+:[A-Za-z0-9_-]{20,}", tok):
                return tok
    return ""


def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {}


def save_state(d: dict):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=1))
    tmp.replace(STATE_FILE)


STATE = load_state()          # owner, last answers
TOKEN = ""
API = ""

# ------------------------------------------------------------------ telegram

def tg(method: str, params: dict | None = None, timeout: float = 70):
    data = urllib.parse.urlencode(params or {}).encode()
    with urllib.request.urlopen(API + method, data=data, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def send(text: str, keyboard=None, chat=None):
    chat = chat or STATE.get("owner")
    if not chat:
        return
    text = text if text.strip() else "(empty)"
    parts = [text[i:i + 3900] for i in range(0, len(text), 3900)]
    for n, part in enumerate(parts):
        params = {"chat_id": chat, "text": part}
        if keyboard and n == len(parts) - 1:
            params["reply_markup"] = json.dumps(keyboard)
        for _ in range(3):
            try:
                tg("sendMessage", params, timeout=30)
                break
            except Exception as e:
                say(f"send failed: {e}")
                time.sleep(3)


def send_photo(jpeg: bytes, caption: str = "", keyboard=None):
    b = uuid.uuid4().hex
    body = io.BytesIO()
    fields = [("chat_id", STATE.get("owner")), ("caption", caption[:1000])]
    if keyboard:
        fields.append(("reply_markup", json.dumps(keyboard)))
    for k, v in fields:
        body.write(f"--{b}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode())
    body.write(f"--{b}\r\nContent-Disposition: form-data; name=\"photo\"; filename=\"screens.jpg\"\r\n"
               f"Content-Type: image/jpeg\r\n\r\n".encode())
    body.write(jpeg)
    body.write(f"\r\n--{b}--\r\n".encode())
    req = urllib.request.Request(API + "sendPhoto", data=body.getvalue(),
                                 headers={"Content-Type": f"multipart/form-data; boundary={b}"})
    urllib.request.urlopen(req, timeout=90).read()

# ------------------------------------------------------------------ dashboard

LAUNCHER_URL = "http://localhost:8000/launcher"
WIN_CMD = "/mnt/c/Windows/System32/cmd.exe"


def open_launcher_on_pc() -> str:
    """Open the launcher page in the browser on the home PC's desktop (WSL interop),
    so the account screens are visible there. Returns a short status line."""
    try:
        import subprocess
        subprocess.run([WIN_CMD, "/c", "start", "", LAUNCHER_URL],
                       check=True, timeout=20, capture_output=True)
        return "🖥 Launcher opened on the PC."
    except Exception as e:  # noqa: BLE001 - report to the owner, keep the bot running
        say(f"open launcher on PC failed: {e!r}")
        return "🖥 Couldn't open the launcher on the PC (is the PC on and logged in?)."


def dash(path: str, body: dict | None = None, timeout: float = 20, raw: bool = False):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(DASH + path, data=data, method="POST" if body is not None else "GET",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            out = r.read()
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read()).get("error") or str(e)
        except Exception:
            msg = str(e)
        raise RuntimeError(msg) from None
    return out if raw else json.loads(out or b"null")


def slots() -> list[dict]:
    return dash("/api/slots")["slots"]


def runs() -> dict:
    return dash("/api/launch")["runs"]


def bots() -> list[dict]:
    return [b for b in dash("/api/bots")["bots"] if b["id"] != "freeroam"]


ACTIVE = ("waiting", "starting", "running")


def fmt_s(s: float) -> str:
    s = max(0, int(s))
    h, m = s // 3600, s % 3600 // 60
    return f"{h}h {m:02d}m" if h else f"{m}m"


def fmt_min(minutes: float) -> str:
    minutes = int(round(minutes))
    h, m = divmod(minutes, 60)
    return (f"{h} h" + (f" {m} min" if m else "")) if h else f"{m} min"


def gb(b: float) -> str:
    return f"{b / 1073741824:.1f}"


def acct_name(n: int, names: dict) -> str:
    return names.get(n) or f"slot {n}"

# ------------------------------------------------------------------ texts

def status_text() -> str:
    s = slots()
    names = {x["slot"]: x["account"] for x in s}
    r = runs()
    lines, counts = [], {"running": 0, "waiting": 0, "starting": 0, "error": 0}
    for x in s:
        n = x["slot"]
        run = r.get(str(n))
        name = acct_name(n, names)
        if run and run["status"] in ACTIVE + ("error",):
            counts[run["status"]] += 1
            bot = "free roam" if run["bot"] == "freeroam" else run["bot"]
            if run["status"] == "running":
                world = f", w{run['world']}" if run.get("world") else ""
                extra = " (restarted)" if "restart" in (run.get("msg") or "") else ""
                lines.append(f"▶ {n} {name} - {bot}, {fmt_s(run['stops_in'])} left{world}{extra}")
            elif run["status"] == "waiting":
                lines.append(f"⏳ {n} {name} - {bot}, starts in {fmt_s(run['starts_in'])}")
            elif run["status"] == "starting":
                lines.append(f"⏳ {n} {name} - {bot}: {run.get('msg') or 'starting'}")
            else:
                lines.append(f"❌ {n} {name} - {bot}: {run.get('msg')}")
        else:
            b = x.get("bot") or {}
            if b.get("status") in ("running", "paused"):     # started by hand in its web UI
                lines.append(f"▶ {n} {name} - {b['bot']} ({b['status']}, not from the launcher)")
            elif not x["account"]:
                lines.append(f"· {n} - no login")
            else:
                done = f" (last: {run['bot']} {run['status']})" if run else ""
                lines.append(f"· {n} {name} - idle{done}")
    head = []
    if counts["running"]:
        head.append(f"{counts['running']} running")
    if counts["waiting"] + counts["starting"]:
        head.append(f"{counts['waiting'] + counts['starting']} starting")
    if counts["error"]:
        head.append(f"{counts['error']} failed")
    out = ("📊 " + (", ".join(head) if head else "nothing running")) + "\n\n" + "\n".join(lines)
    try:
        st = dash("/api/stats?min=5", timeout=10)["vm"]
        out += (f"\n\nVM: RAM {gb(st['ram_used'])}/{gb(st['ram_total'])} GB, "
                f"CPU {round(st['cpu_avg'] or 0)}% (5 min avg)")
    except Exception:
        pass
    return out


def stats_text() -> str:
    s = dash("/api/stats?min=10", timeout=15)
    vm, sl, win = s["vm"], s["slots"], s.get("windows", {})
    names = {x["slot"]: x["account"] for x in slots()}
    lines = [f"📈 Resources (avg over {s['window_min']} min)",
             f"VM RAM {gb(vm['ram_used'])}/{gb(vm['ram_total'])} GB (peak {gb(vm['ram_peak'])})",
             f"VM CPU {vm['cpu_avg']}% avg, {vm['cpu_max']}% max of {vm['cpu_threads']} threads"]
    if vm.get("swap_used", 0) > 100 * 1048576:
        lines.append(f"Swap used {gb(vm['swap_used'])} GB")
    if win.get("pc_ram_bytes"):
        lines.append(f"PC RAM {gb(win['pc_ram_bytes'])} GB, {gb(win.get('pc_free_bytes', 0))} GB free")
    lines.append("")
    for n, v in sorted(sl.items(), key=lambda kv: int(kv[0])):
        if v["ram_now"] < 50 * 1048576:
            continue
        lines.append(f"{n} {acct_name(int(n), names)}: {gb(v['ram_avg'])} GB, CPU {v['cpu_avg']:.0f}%")
    lines.append("\n(CPU per slot: 100% = one full thread)")
    return "\n".join(lines)


def screens_picture(only: list[int] | None = None) -> tuple[bytes, str] | None:
    """One picture with the RuneLite window of every launched slot (else every logged-in one)."""
    from PIL import Image
    r = runs()
    s = slots()
    names = {x["slot"]: x["account"] for x in s}
    if only:
        want = only
    else:
        want = sorted(int(k) for k, v in r.items() if v["status"] in ACTIVE) or \
               [x["slot"] for x in s if x["account"]]
    if not want:
        return None
    geom = dash("/api/geometry")
    width = 1280 if len(want) == 1 else 640
    scale = width / 1280
    tiles = []
    for n in want:
        try:
            img = Image.open(io.BytesIO(dash(f"/shot/{n}.jpg?w={width}", raw=True, timeout=15))).convert("RGB")
        except Exception:
            continue
        g = geom.get(str(n))
        if g:
            box = (int(g["x"] * scale), int(g["y"] * scale),
                   int((g["x"] + g["width"]) * scale), int((g["y"] + g["height"]) * scale))
            box = (max(0, box[0]), max(0, box[1]), min(img.width, box[2]), min(img.height, box[3]))
            if box[2] - box[0] > 50 and box[3] - box[1] > 50:
                img = img.crop(box)
        tiles.append((n, img))
    if not tiles:
        return None
    cols = math.ceil(math.sqrt(len(tiles)))
    rows = math.ceil(len(tiles) / cols)
    tw = max(t.width for _, t in tiles)
    th = max(t.height for _, t in tiles)
    sheet = Image.new("RGB", (cols * tw + (cols - 1) * 4, rows * th + (rows - 1) * 4), (20, 19, 17))
    for i, (_, t) in enumerate(tiles):
        sheet.paste(t, ((i % cols) * (tw + 4), (i // cols) * (th + 4)))
    buf = io.BytesIO()
    sheet.save(buf, "JPEG", quality=80)
    cap = " · ".join(f"{n} {acct_name(n, names)}" for n, _ in tiles)
    return buf.getvalue(), cap

# ------------------------------------------------------------------ keyboards

B_START, B_FREE = "🚀 Start bots", "🧭 Free roam"
B_STATUS, B_SHOT = "📊 Status", "📸 Screens"
B_STOP, B_MORE = "⏹ Stop", "⋯ More"
B_UPDATE, B_STATS, B_CLEAR = "🔄 Update code", "📈 Resources", "🧹 Clear finished"
B_BACK, B_CANCEL, B_GO, B_YES = "« Back", "✖ Cancel", "✅ Start", "✅ Yes"
B_NEXT, B_ALL, B_NONE = "➡ Next", "☑ All free", "☐ None"
B_STOP_ALL = "⏹ Stop ALL"
KEEP = "↩ Same as last: "

MENU = {"keyboard": [[B_START, B_FREE], [B_STATUS, B_SHOT], [B_STOP, B_MORE]], "resize_keyboard": True}
MORE = {"keyboard": [[B_STATS, B_CLEAR], [B_UPDATE], [B_BACK]], "resize_keyboard": True}


def kb(rows, keep=None, back=True):
    rows = [list(r) for r in rows]
    if keep not in (None, ""):
        rows.insert(0, [KEEP + str(keep)[-40:]])
    rows.append([B_BACK, B_CANCEL] if back else [B_CANCEL])
    return {"keyboard": rows, "resize_keyboard": True}


def chunks(items, n):
    return [items[i:i + n] for i in range(0, len(items), n)]


def last(key, default=None):
    return STATE.get("last", {}).get(key, default)


def remember(**kw):
    STATE.setdefault("last", {}).update(kw)
    save_state(STATE)

# ------------------------------------------------------------------ start wizard
# steps: accounts -> bot -> time -> spread -> confirm   (free roam: accounts -> confirm)

wiz: dict | None = None
pending: tuple | None = None       # ("stop", None) / ("update", None)


def free_accounts() -> list[tuple[int, str]]:
    r = runs()
    return [(x["slot"], x["account"]) for x in slots()
            if x["account"] and r.get(str(x["slot"]), {}).get("status") not in ACTIVE]


def acct_label(n: int, name: str, chosen: bool) -> str:
    return ("✅ " if chosen else "") + f"{n} · {name}"[:30]


def parse_slots(t: str, valid: set[int]) -> set[int] | None:
    """'1,3,5' / '1-4' / '2 6' -> slot numbers (None if it isn't a slot list)."""
    if not re.fullmatch(r"[\d\s,\-]+", t):
        return None
    out = set()
    for part in re.split(r"[\s,]+", t.strip()):
        if not part:
            continue
        if m := re.fullmatch(r"(\d+)-(\d+)", part):
            out |= set(range(int(m.group(1)), int(m.group(2)) + 1))
        elif part.isdigit():
            out.add(int(part))
    return out & valid


def parse_minutes(t: str) -> float | None:
    t = t.lower().replace(",", ".").replace(" ", "")
    if m := re.fullmatch(r"(\d+(?:\.\d+)?)h(?:(\d+)(?:m|min)?)?", t):
        return float(m.group(1)) * 60 + float(m.group(2) or 0)
    if m := re.fullmatch(r"(\d+)(?:m|min)", t):
        return float(m.group(1))
    if m := re.fullmatch(r"(\d+):(\d\d)", t):
        return int(m.group(1)) * 60 + int(m.group(2))
    if re.fullmatch(r"\d+", t):
        return float(t)
    return None


TIME_BUTTONS = {"30 min": 30, "1 h": 60, "2 h": 120, "3 h": 180, "4 h": 240, "6 h": 360}
SPREAD_YES, SPREAD_NO = "Spread out (1-4 min apart)", "All at once"


def wiz_ask(note: str = ""):
    w = wiz
    pre = (note + "\n\n") if note else ""
    step = w["step"]
    if step == "accounts":
        free = free_accounts()
        w["free"] = dict(free)
        if not free:
            return pre + "No free accounts: every logged-in account is already launched.", kb([], back=False)
        sel = w["sel"]
        rows = chunks([acct_label(n, nm, n in sel) for n, nm in free], 2)
        rows.append([B_ALL, B_NONE])
        rows.append([B_NEXT])
        chosen = ", ".join(f"{n}" for n in sorted(sel)) or "none"
        what = "Free roam - which accounts to log in?" if w["free_roam"] else "Which accounts?"
        return (pre + f"{what}\nTap to pick (or type e.g. 1-4 or 1,3,5).\nChosen: {chosen}",
                kb(rows, back=False))
    if step == "bot":
        names = [b["name"] if len(b["name"]) <= 28 else b["id"] for b in w["bots"]]
        keep = next((b["name"] for b in w["bots"] if b["id"] == last("bot")), None)
        return pre + "Which bot?", kb(chunks(names, 2), keep)
    if step == "time":
        lm = last("minutes")
        return (pre + "Run for how long? (or type e.g. 90, 1h30, 2.5h)",
                kb(chunks(list(TIME_BUTTONS), 3), fmt_min(lm) if lm else None))
    if step == "spread":
        return (pre + "Start them spread out (like a human) or all at once?",
                kb([[SPREAD_YES], [SPREAD_NO]]))
    # confirm
    a = w["a"]
    names = w["free"]
    accts = "\n".join(f"  {n} {names.get(n, '')}" for n in sorted(a["slots"]))
    if w["free_roam"]:
        txt = f"🧭 Free roam - log in (no bot):\n{accts}\n\nRandom F2P world each. Stop them with ⏹ when done."
    else:
        txt = (f"🚀 {a['bot_name']} for {fmt_min(a['minutes'])}"
               f"{' (±10%)' if a['spread'] else ''}\n{accts}\n\n"
               f"{'Spread out: 1-4 min between starts.' if a['spread'] else 'All at once.'}\n"
               "Each account must already stand where its bot works.")
    return pre + txt, kb([[B_GO]])


def wiz_answer(t: str) -> str:
    """Store the answer for the current step; '' = go on, else a note to show (stay on the step)."""
    w = wiz
    step, a = w["step"], w["a"]
    if step == "accounts":
        free = w.get("free") or dict(free_accounts())
        if t == B_ALL:
            w["sel"] = set(free)
            return "_stay"
        if t == B_NONE:
            w["sel"] = set()
            return "_stay"
        if t == B_NEXT:
            if not w["sel"]:
                return "Pick at least one account."
            a["slots"] = sorted(w["sel"])
            return ""
        if m := re.match(r"(?:✅ )?(\d+) · ", t):
            n = int(m.group(1))
            if n in free:
                w["sel"] ^= {n}
            return "_stay"
        got = parse_slots(t, set(free))
        if got is not None:
            if not got:
                return "None of those are free accounts."
            w["sel"] = got
            return "_stay"
        return "Tap an account, then ➡ Next."
    if step == "bot":
        if t.startswith(KEEP):
            t = t[len(KEEP):]
        for b in w["bots"]:
            if t in (b["name"], b["id"]) or t.lower() == b["name"].lower():
                a["bot"], a["bot_name"] = b["id"], b["name"]
                return ""
        return "Pick a bot from the buttons."
    if step == "time":
        if t.startswith(KEEP):
            mins = last("minutes")
        else:
            mins = TIME_BUTTONS.get(t) or parse_minutes(t)
        if not mins or mins <= 0 or mins > 24 * 60:
            return "Give a time between 1 min and 24 h (e.g. 90, 1h30)."
        a["minutes"] = float(mins)
        return ""
    if step == "spread":
        if t not in (SPREAD_YES, SPREAD_NO):
            return "Pick one of the two buttons."
        a["spread"] = t == SPREAD_YES
        return ""
    return ""


def wiz_steps() -> list[str]:
    return ["accounts", "confirm"] if wiz["free_roam"] else ["accounts", "bot", "time", "spread", "confirm"]


def wiz_start() -> str:
    a = wiz["a"]
    if wiz["free_roam"]:
        dash("/api/launch", {"slots": a["slots"], "bot": "freeroam", "minutes": 0, "spread": False})
        return f"🧭 Logging in {len(a['slots'])} account(s). I'll tell you if a login fails."
    dash("/api/launch", {"slots": a["slots"], "bot": a["bot"], "minutes": a["minutes"], "spread": a["spread"]})
    remember(bot=a["bot"], minutes=a["minutes"], spread=a["spread"])
    first = "now" if not a["spread"] else "now, the rest over the next minutes"
    return (f"🚀 Launched {a['bot_name']} on {len(a['slots'])} account(s) for {fmt_min(a['minutes'])}. "
            f"First starts {first}.\nI'll message you when runs finish or something goes wrong.")

# ------------------------------------------------------------------ menu

def stop_keyboard():
    r = runs()
    names = {x["slot"]: x["account"] for x in slots()}
    act = [int(k) for k, v in r.items() if v["status"] in ACTIVE]
    if not act:
        return None
    rows = chunks([f"⏹ {n} · {acct_name(n, names)}"[:30] for n in sorted(act)], 2)
    rows.insert(0, [B_STOP_ALL])
    return kb(rows, back=False)


def handle(text: str):
    """Returns (reply, keyboard). reply None = already sent."""
    global wiz, pending
    t = text.strip()

    if t in (B_CANCEL, "/cancel"):
        wiz = pending = None
        return "Cancelled.", MENU

    if wiz:
        if t == B_BACK:
            steps = wiz_steps()
            i = steps.index(wiz["step"])
            if i == 0:
                wiz = None
                return "Menu:", MENU
            wiz["step"] = steps[i - 1]
            return wiz_ask()
        if wiz["step"] == "confirm":
            if t != B_GO:
                return wiz_ask("Press ✅ Start, « Back or ✖ Cancel.")
            try:
                msg = wiz_start()
            finally:
                wiz = None
            return msg, MENU
        note = wiz_answer(t)
        if note == "_stay":
            return wiz_ask()
        if note:
            return wiz_ask(note)
        steps = wiz_steps()
        wiz["step"] = steps[steps.index(wiz["step"]) + 1]
        return wiz_ask()

    if pending:
        what, _ = pending
        pending = None
        if what == "stop":
            if t == B_STOP_ALL:
                dash("/api/launch/stop", {"slots": []})
                return "⏹ Stopped everything (characters stay logged in).", MENU
            if m := re.match(r"⏹ (\d+) · ", t):
                dash("/api/launch/stop", {"slots": [int(m.group(1))]})
                return f"⏹ Stopped slot {m.group(1)}.", MENU
            return "Not stopped.", MENU
        if what == "update":
            if t != B_YES:
                return "Not updated.", MENU
            res = dash("/api/update", {})
            if not res.get("ok"):
                return f"Update didn't start: {res.get('error')}", MENU
            return ("🔄 Updating: copying the code from D:\\osrs-fleet and restarting the bot apps. "
                    "Running bots are restarted by the launcher; RuneLite stays logged in. "
                    "I'll be back in a few seconds."), MENU
        return "Menu:", MENU

    if t in (B_START, "/start_bots", "/run"):
        wiz = {"step": "accounts", "a": {}, "sel": set(), "free_roam": False, "bots": bots()}
        return wiz_ask()
    if t in (B_FREE, "/freeroam"):
        wiz = {"step": "accounts", "a": {}, "sel": set(), "free_roam": True, "bots": []}
        return wiz_ask()
    if t in (B_STATUS, "/status"):
        return status_text(), MENU
    if t in (B_SHOT, "/shot") or t.startswith("/shot "):
        only = None
        if t.startswith("/shot "):
            only = sorted(parse_slots(t[6:], set(range(1, 33))) or []) or None
        opened = open_launcher_on_pc()
        pic = screens_picture(only)
        if not pic:
            return f"{opened}\nNo screens to show (no account logged in).", MENU
        send_photo(pic[0], f"{pic[1]}\n{opened}", keyboard=MENU)
        return None, MENU
    if t in ("/launcher", "/view"):
        return open_launcher_on_pc(), MENU
    if t in (B_STOP, "/stop"):
        k = stop_keyboard()
        if not k:
            return "Nothing is running.", MENU
        pending = ("stop", None)
        return "Stop which? (characters stay logged in)", k
    if t == "/stop all":
        dash("/api/launch/stop", {"slots": []})
        return "⏹ Stopped everything.", MENU
    if t in (B_MORE,):
        return "More:", MORE
    if t in (B_STATS, "/stats"):
        return stats_text(), MORE
    if t in (B_CLEAR, "/clear"):
        dash("/api/launch/clear", {})
        return "🧹 Finished and stopped runs cleared from the list.", MORE
    if t in (B_UPDATE, "/update"):
        pending = ("update", None)
        return ("Copy the latest code from D:\\osrs-fleet into the VM and restart the bot apps?\n"
                "(Pull it in GitHub Desktop first.)"), {"keyboard": [[B_YES], [B_CANCEL]], "resize_keyboard": True}
    if t == B_BACK:
        return "Menu:", MENU
    if t in ("/help", "/start", "/menu"):
        return HELP, MENU
    return "Choose what to do:", MENU


HELP = """OSRS fleet bot - buttons:
🚀 Start bots: accounts → bot → run time → spread → Start
🧭 Free roam: log accounts in without a bot
📊 Status · 📸 Screens (also opens the launcher on the PC) · ⏹ Stop
⋯ More: Resources, Clear finished, Update code

Also: /status  /shot 3  /launcher  /stop all  /stats  /update
I message you when a run finishes, a bot stops on its own, or a login fails."""

# ------------------------------------------------------------------ alerts

LOGIN_WORDS = ("login", "get into the game", "get back into the game", "no saved login", "log in")


def is_login(msg: str) -> bool:
    m = (msg or "").lower()
    return any(w in m for w in LOGIN_WORDS)


def watcher():
    prev: dict[str, dict] | None = None
    down_since = None
    warned_down = False
    while True:
        time.sleep(5)
        try:
            cur = runs()
            names = {x["slot"]: x["account"] for x in slots()}
        except Exception:
            down_since = down_since or time.time()
            if not warned_down and time.time() - down_since > 180 and STATE.get("owner"):
                send("⚠️ The fleet dashboard isn't answering for 3 min (VM or dashboard down?).")
                warned_down = True
            continue
        if warned_down:
            send("✅ Dashboard is answering again.")
        down_since, warned_down = None, False
        if prev is None:
            prev = cur
            continue
        msgs = []
        for k, r in cur.items():
            p = prev.get(k)
            if p and p.get("start_at") != r.get("start_at"):
                p = None                                    # a new launch on this slot
            n = int(k)
            who = f"{n} {r.get('account') or acct_name(n, names)}"
            bot = "free roam" if r["bot"] == "freeroam" else r["bot"]
            ps = p["status"] if p else None
            st, msg = r["status"], r.get("msg") or ""
            if st == "done" and ps != "done":
                ran = r.get("stop_at", 0) - r.get("start_at", 0)
                if r["bot"] == "freeroam":
                    msgs.append(f"✅ Free roam over: {who}")
                else:
                    msgs.append(f"✅ Run finished: {who} - {bot}, ~{fmt_s(ran)} (still logged in)")
            elif st == "error" and ps != "error":
                if is_login(msg):
                    msgs.append(f"🔑 Login failed: {who}\n   {msg}")
                else:
                    msgs.append(f"❌ {who} - {bot} gave up:\n   {msg}")
            elif st == "running":
                if r.get("restarts", 0) > (p or {}).get("restarts", 0) and p is not None:
                    msgs.append(f"⚠️ {who}: {bot} stopped on its own, restarting it "
                                f"({r['restarts']}/3).")
                if msg.startswith("restart failed") and msg != (p or {}).get("msg"):
                    if is_login(msg):
                        msgs.append(f"🔑 Login failed after a restart: {who}\n   {msg[len('restart failed: '):]}")
                    else:
                        msgs.append(f"❌ Restart failed: {who}\n   {msg}")
        prev = cur
        if msgs and STATE.get("owner"):
            send("\n".join(msgs))

# ------------------------------------------------------------------ main

def uptime() -> float:
    try:
        return float(Path("/proc/uptime").read_text().split()[0])
    except Exception:
        return 1e9


def main():
    global TOKEN, API, wiz, pending
    say("telegram bot starting")
    while not TOKEN:
        TOKEN = read_token()
        if not TOKEN:
            say("no token yet - put it in " + " or ".join(str(f) for f in config_files()) +
                "  ([telegram] token = ...); checking again in 60 s")
            time.sleep(60)
    API = f"https://api.telegram.org/bot{TOKEN}/"
    me = tg("getMe", timeout=20).get("result", {})
    say(f"logged in as @{me.get('username')}; owner {STATE.get('owner') or '(none yet)'}")
    threading.Thread(target=watcher, daemon=True, name="watcher").start()
    # no "PC is on" message at start (Igor 2026-10-18)
    offset = 0
    while True:
        try:
            r = tg("getUpdates", {"offset": offset, "timeout": 50})
            for u in r.get("result", []):
                offset = u["update_id"] + 1
                m = u.get("message") or {}
                chat = m.get("chat", {})
                if chat.get("type") != "private" or "text" not in m:
                    continue
                if not STATE.get("owner"):
                    STATE["owner"] = str(chat["id"])
                    save_state(STATE)
                    say(f"owner set to chat {chat['id']}")
                    send("Hi Igor - this bot now answers only you.\n\n" + HELP, keyboard=MENU)
                    continue
                if str(chat["id"]) != STATE["owner"]:
                    say(f"ignored message from chat {chat['id']}")
                    continue
                say(f"cmd: {m['text'][:100]}")
                try:
                    reply, keys = handle(m["text"])
                except Exception as e:
                    wiz = pending = None
                    say(f"error on {m['text'][:50]}: {e!r}\n{traceback.format_exc()}")
                    reply, keys = f"Error: {e}", MENU
                if reply:
                    send(reply, keyboard=keys)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            say(f"network: {e}")
            time.sleep(10)
        except Exception as e:
            say(f"poll error: {e!r}")
            time.sleep(10)


if __name__ == "__main__":
    sys.exit(main())
