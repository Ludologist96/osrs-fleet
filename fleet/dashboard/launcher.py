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
  5. stops the bot when its time is up (the character stays logged in).
"""

from __future__ import annotations

import json
import random
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
        self._load()
        threading.Thread(target=self._loop, daemon=True, name="launcher").start()

    # ------------------------------------------------------------ state
    def _load(self):
        try:
            self.runs = json.loads(STATE_FILE.read_text()).get("runs", {})
            # a start that was in progress when the dashboard restarted: retry it
            for r in self.runs.values():
                if r["status"] == "starting":
                    r["status"] = "waiting"
        except FileNotFoundError:
            self.runs = {}
        except Exception:
            self.runs = {}

    def _save(self):
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps({"runs": self.runs}, indent=1))
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
                out[k] = r
            return {"now": now, "runs": out}

    def launch(self, slots: list[int], bot: str, minutes: float, spread: bool = True) -> dict:
        slots = [n for n in slots if 1 <= n <= self.slots]
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
            self._save()
        return self.status()

    def stop(self, slots: list[int] | None = None) -> dict:
        with _lock:
            targets = [int(k) for k in self.runs] if not slots else slots
            for n in targets:
                r = self.runs.get(str(n))
                if not r or r["status"] in ("done", "error", "stopped"):
                    continue
                if r["status"] == "running":
                    self._stop_bot(n, r["bot"])
                r.update(status="stopped", msg="stopped by you", stop_at=time.time())
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
            elif r["status"] == "running":
                if now >= r["stop_at"]:
                    self._stop_bot(n, r["bot"])
                    self._set(n, status="done", msg="run time over, bot stopped")
                else:
                    st = self._bot_status(n, r["bot"])
                    if st not in ("running", "paused", None):
                        self._set(n, status="error", msg=f"bot stopped on its own ({st}); see its log")

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
            # 3. log in
            self._set(n, msg="logging in")
            st = _http("POST", f"{_app(n)}/api/session/login", timeout=150)
            if st.get("state") != "game":
                raise RuntimeError(f"couldn't get into the game ({st.get('error') or st.get('state')})")
            # 4. start the bot with this slot's saved settings
            self._set(n, msg=f"starting {bot}")
            cfg = _http("GET", f"{_app(n)}/api/bot/{bot}/config")
            res = _http("POST", f"{_app(n)}/api/bot/{bot}/start", {"config": cfg}, timeout=60)
            if not res.get("success"):
                raise RuntimeError(f"bot didn't start: {res.get('error')}")
            # run time counts from the real start
            with _lock:
                r = self.runs[str(n)]
                r["stop_at"] = time.time() + (r["stop_at"] - r["start_at"])
                r.update(status="running", msg=f"{bot} running")
                self._save()
        except Exception as e:
            self._set(n, status="error", msg=str(e))

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
