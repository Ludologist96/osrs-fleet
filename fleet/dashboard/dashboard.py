"""
OSRS fleet dashboard: one page showing every slot's screen and status.

Runs on the fleet VM as the osrs-dashboard service (root, so it can restart
slots). Open http://localhost:8000 on Windows.

Only the Python standard library plus mss + Pillow (already in the bot venv).
"""

from __future__ import annotations

import io
import json
import os
import re
import subprocess
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

CONF_PATH = Path("/etc/osrs/fleet.conf")
HERE = Path(__file__).resolve().parent
COMPONENTS = ["xvfb", "wm", "vnc", "client", "app"]


def read_conf() -> dict:
    conf = {"SLOTS": "8", "DASHBOARD_PORT": "8000"}
    if CONF_PATH.exists():
        for line in CONF_PATH.read_text().splitlines():
            m = re.match(r'\s*([A-Z_]+)=(.*)', line)
            if m:
                conf[m.group(1)] = m.group(2).strip().strip('"')
    return conf


CONF = read_conf()
SLOTS = int(CONF.get("SLOTS", 8))
PORT = int(CONF.get("DASHBOARD_PORT", 8000))


# ---------------------------------------------------------------- status

def _run(cmd: list[str], env: dict | None = None, timeout: float = 4) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                              env=env).stdout.strip()
    except Exception:
        return ""


def unit_states(n: int) -> dict:
    units = [f"osrs-{c}@{n}.service" for c in COMPONENTS]
    out = _run(["systemctl", "is-active", *units]).splitlines()
    out += ["unknown"] * (len(units) - len(out))
    return dict(zip(COMPONENTS, out))


def window_title(n: int) -> str:
    env = dict(os.environ, DISPLAY=f":{n}")
    return _run(["xdotool", "search", "--name", "^RuneLite", "getwindowname"], env=env).split("\n")[0]


def bot_status(n: int) -> dict:
    """Ask the slot's web UI which bot (if any) is running."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{8010 + n}/api/bots/status", timeout=2) as r:
            data = json.load(r)
        for bot_id, st in data.items():
            if st.get("status") in ("running", "paused"):
                return {"bot": bot_id, "status": st.get("status"),
                        "runtime": st.get("runtime_formatted", "")}
        return {"bot": None, "status": "idle", "runtime": ""}
    except Exception:
        return {"bot": None, "status": "offline", "runtime": ""}


def slot_info(n: int) -> dict:
    title = window_title(n)
    account = ""
    if title.startswith("RuneLite - "):
        account = title[len("RuneLite - "):]
    return {
        "slot": n,
        "units": unit_states(n),
        "window": title,
        "account": account,
        "bot": bot_status(n),
        "ui_port": 8010 + n,
        "vnc_port": 5900 + n,
    }


# ---------------------------------------------------------------- screenshots

_shot_cache: dict[tuple[int, int], tuple[float, bytes]] = {}
_shot_lock = threading.Lock()


def screenshot(n: int, width: int = 640) -> bytes | None:
    with _shot_lock:
        hit = _shot_cache.get((n, width))
        if hit and time.time() - hit[0] < 1.5:
            return hit[1]
    try:
        import mss
        from PIL import Image
        with mss.mss(display=f":{n}") as sct:
            raw = sct.grab(sct.monitors[0])
            img = Image.frombytes("RGB", raw.size, raw.rgb)
        if img.width > width:
            img = img.resize((width, round(img.height * width / img.width)))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=70)
        data = buf.getvalue()
    except Exception:
        return None
    with _shot_lock:
        _shot_cache[(n, width)] = (time.time(), data)
    return data


# ---------------------------------------------------------------- actions

ACTIONS = {
    "restart-client": lambda n: ["systemctl", "restart", f"osrs-client@{n}.service"],
    "restart-app": lambda n: ["systemctl", "restart", f"osrs-app@{n}.service"],
    "restart-slot": lambda n: ["systemctl", "restart", f"osrs-slot@{n}.target"],
    "stop-slot": lambda n: ["systemctl", "stop", f"osrs-slot@{n}.target"],
    "start-slot": lambda n: ["systemctl", "start", f"osrs-slot@{n}.target"],
    # Give slot N the Jagex login RuneLite last saved on Windows (credentials.properties).
    "creds": lambda n: ["/opt/osrs/bin/fleetctl", "creds", str(n)],
    # Copy slot 1's RuneLite plugins/settings to slot N (logins are not copied).
    "copy-settings": lambda n: ["/opt/osrs/bin/fleetctl", "copy-settings", "1", str(n)],
}


def start_update() -> dict:
    """Run `fleetctl update` outside this service (it restarts the dashboard at the end)."""
    unit = f"osrs-update-{int(time.time())}"
    res = subprocess.run(["systemd-run", "--no-block", f"--unit={unit}",
                          "/opt/osrs/bin/fleetctl", "update"],
                         capture_output=True, text=True)
    return {"ok": res.returncode == 0, "unit": unit, "error": res.stderr.strip()}


def journal(unit: str, lines: int = 100) -> str:
    return _run(["journalctl", "-u", unit, "-n", str(lines), "--no-pager", "-o", "short-iso"],
                timeout=10)


def stop_bot(n: int) -> bool:
    st = bot_status(n)
    if not st["bot"]:
        return False
    req = urllib.request.Request(f"http://127.0.0.1:{8010 + n}/api/bot/{st['bot']}/stop",
                                 method="POST", data=b"{}",
                                 headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=3).read()
        return True
    except Exception:
        return False


# ---------------------------------------------------------------- http

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # quiet
        pass

    def _send(self, code: int, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj).encode(), "application/json")

    def do_GET(self):
        path, _, query = self.path.partition("?")
        if path in ("/", "/index.html"):
            self._send(200, (HERE / "index.html").read_bytes(), "text/html; charset=utf-8")
        elif path == "/api/slots":
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=SLOTS) as ex:
                slots = list(ex.map(slot_info, range(1, SLOTS + 1)))
            self._json({"slots": slots})
        elif m := re.fullmatch(r"/api/slot/(\d+)/log/(xvfb|wm|vnc|client|app)", path):
            # Last lines of one slot part's log (what `fleetctl logs N part` shows).
            n, comp = int(m.group(1)), m.group(2)
            lm = re.search(r"(?:^|&)n=(\d+)", query)
            lines = min(1000, int(lm.group(1))) if lm else 100
            if not 1 <= n <= SLOTS:
                return self._json({"error": "bad slot"}, 400)
            self._send(200, journal(f"osrs-{comp}@{n}.service", lines).encode(), "text/plain; charset=utf-8")
        elif m := re.fullmatch(r"/api/update-log/(osrs-update-\d+)", path):
            self._send(200, journal(m.group(1), 200).encode(), "text/plain; charset=utf-8")
        elif m := re.fullmatch(r"/shot/(\d+)\.jpg", path):
            n = int(m.group(1))
            wm = re.search(r"(?:^|&)w=(\d+)", query)
            width = min(1920, max(160, int(wm.group(1)))) if wm else 640
            data = screenshot(n, width) if 1 <= n <= SLOTS else None
            if data:
                self._send(200, data, "image/jpeg")
            else:
                self._send(404, b"", "text/plain")
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self):
        if self.path == "/api/update":
            # Copy the new code from the Windows folder into the VM and restart the bot apps.
            return self._json(start_update())
        m = re.fullmatch(r"/api/slot/(\d+)/([a-z-]+)", self.path)
        if not m:
            return self._json({"ok": False, "error": "bad path"}, 404)
        n, action = int(m.group(1)), m.group(2)
        if not 1 <= n <= SLOTS:
            return self._json({"ok": False, "error": "bad slot"}, 400)
        if action == "stop-bot":
            return self._json({"ok": stop_bot(n)})
        if action not in ACTIONS:
            return self._json({"ok": False, "error": "unknown action"}, 400)
        res = subprocess.run(ACTIONS[action](n), capture_output=True, text=True)
        self._json({"ok": res.returncode == 0, "error": res.stderr.strip()})


def main():
    # Listen on localhost only; WSL forwards it to Windows' localhost.
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Fleet dashboard on http://localhost:{PORT} ({SLOTS} slots)", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
