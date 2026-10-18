"""
RAM and CPU use of the fleet VM, per slot and in total (dashboard /api/stats).

Every slot's processes (screen, window manager, VNC, RuneLite, bot app) run as
Linux user botN, so a slot's use = the sum over that user's processes.
A background thread samples /proc every few seconds and keeps the last
HISTORY_S seconds, so the numbers are averages, plus peaks since the start.
Only the standard library.
"""

from __future__ import annotations

import glob
import os
import pwd
import re
import subprocess
import threading
import time
from collections import deque

SAMPLE_EVERY = 5          # seconds between samples
HISTORY_S = 15 * 60       # averages over this long
CLK = os.sysconf("SC_CLK_TCK")
PAGE = os.sysconf("SC_PAGE_SIZE")
NCPU = os.cpu_count() or 1


def _meminfo() -> dict:
    out = {}
    with open("/proc/meminfo") as f:
        for line in f:
            k, v = line.split(":", 1)
            out[k] = int(v.split()[0]) * 1024
    return out


def _cpu_total() -> tuple[int, int]:
    """(busy, total) jiffies of the whole VM."""
    with open("/proc/stat") as f:
        vals = [int(x) for x in f.readline().split()[1:]]
    idle = vals[3] + (vals[4] if len(vals) > 4 else 0)
    return sum(vals) - idle, sum(vals)


def _procs() -> dict[int, tuple[int, int]]:
    """uid -> (cpu jiffies, rss bytes) summed over that user's processes."""
    per: dict[int, list[int]] = {}
    for d in glob.glob("/proc/[0-9]*"):
        try:
            uid = os.stat(d).st_uid
            with open(d + "/stat") as f:
                st = f.read()
            parts = st[st.rindex(")") + 2:].split()
            jiffies = int(parts[11]) + int(parts[12])          # utime + stime
            rss = int(parts[21]) * PAGE
        except (OSError, ValueError, IndexError):
            continue
        a = per.setdefault(uid, [0, 0])
        a[0] += jiffies
        a[1] += rss
    return {k: (v[0], v[1]) for k, v in per.items()}


def _windows_info() -> dict:
    """What Windows gave the VM (.wslconfig) and the PC's total RAM, if readable."""
    info: dict = {}
    for f in glob.glob("/mnt/c/Users/*/.wslconfig"):
        try:
            txt = open(f, errors="replace").read()
        except OSError:
            continue
        if m := re.search(r"^\s*memory\s*=\s*(\d+)\s*GB", txt, re.M | re.I):
            info["wsl_memory_gb"] = int(m.group(1))
        if m := re.search(r"^\s*processors\s*=\s*(\d+)", txt, re.M | re.I):
            info["wsl_processors"] = int(m.group(1))
        if m := re.search(r"^\s*swap\s*=\s*(\d+)\s*GB", txt, re.M | re.I):
            info["wsl_swap_gb"] = int(m.group(1))
        info["wslconfig"] = f
        break
    ps = "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"
    if os.path.exists(ps):
        try:
            out = subprocess.run(
                [ps, "-NoProfile", "-Command",
                 "$c=Get-CimInstance Win32_ComputerSystem; $o=Get-CimInstance Win32_OperatingSystem;"
                 "$p=Get-CimInstance Win32_Processor | Select-Object -First 1;"
                 "\"$($c.TotalPhysicalMemory)|$($o.FreePhysicalMemory)|$($c.NumberOfLogicalProcessors)|$($p.Name)\""],
                capture_output=True, text=True, timeout=20).stdout.strip()
            tot, free_kb, lp, name = out.split("|", 3)
            info.update(pc_ram_bytes=int(tot), pc_free_bytes=int(free_kb) * 1024,
                        pc_threads=int(lp), cpu_name=name.strip())
        except Exception:
            pass
    return info


class Stats:
    def __init__(self, slots: int):
        self.slots = slots
        self.uids: dict[int, int] = {}
        for n in range(1, slots + 1):
            try:
                self.uids[n] = pwd.getpwnam(f"bot{n}").pw_uid
            except KeyError:
                pass
        self.hist: deque = deque()          # (t, {slot: (cpu%, rss)}, vm_cpu%, used_bytes)
        self.peak_rss: dict[int, int] = {}
        self.peak_used = 0
        self.win: dict = {}
        self.win_at = 0.0
        self._lock = threading.Lock()
        threading.Thread(target=self._loop, daemon=True, name="stats").start()

    def _loop(self):
        prev_p, prev_c, prev_t = _procs(), _cpu_total(), time.time()
        while True:
            time.sleep(SAMPLE_EVERY)
            if time.time() - self.win_at > 600:   # Windows side, slow (PowerShell): here, not in a request
                self.win_at = time.time()
                try:
                    self.win = _windows_info()
                except Exception:
                    pass
            try:
                p, c, t = _procs(), _cpu_total(), time.time()
                dt = max(0.1, t - prev_t)
                per = {}
                for n, uid in self.uids.items():
                    j0 = prev_p.get(uid, (0, 0))[0]
                    j1, rss = p.get(uid, (0, 0))
                    # % of ONE cpu thread (100 = one full thread)
                    per[n] = (max(0.0, (j1 - j0) / CLK / dt * 100), rss)
                busy = c[0] - prev_c[0]
                total = max(1, c[1] - prev_c[1])
                m = _meminfo()
                used = m["MemTotal"] - m["MemAvailable"]
                with self._lock:
                    self.hist.append((t, per, busy / total * 100, used))
                    while self.hist and t - self.hist[0][0] > HISTORY_S:
                        self.hist.popleft()
                    for n, (_, rss) in per.items():
                        self.peak_rss[n] = max(self.peak_rss.get(n, 0), rss)
                    self.peak_used = max(self.peak_used, used)
                prev_p, prev_c, prev_t = p, c, t
            except Exception as e:
                print(f"stats sample failed: {e!r}", flush=True)

    def windows(self) -> dict:
        return self.win

    def snapshot(self, minutes: float = 10) -> dict:
        m = _meminfo()
        with self._lock:
            hist = list(self.hist)
            peaks = dict(self.peak_rss)
            peak_used = self.peak_used
        now = time.time()
        recent = [h for h in hist if now - h[0] <= minutes * 60] or hist[-1:]
        slots = {}
        for n in self.uids:
            vals = [h[1].get(n, (0.0, 0)) for h in recent]
            if not vals:
                continue
            slots[n] = {
                "cpu_now": round(vals[-1][0], 1),
                "cpu_avg": round(sum(v[0] for v in vals) / len(vals), 1),
                "cpu_max": round(max(v[0] for v in vals), 1),
                "ram_now": vals[-1][1],
                "ram_avg": int(sum(v[1] for v in vals) / len(vals)),
                "ram_peak": peaks.get(n, 0),
            }
        vm_cpu = [h[2] for h in recent]
        return {
            "window_min": round((recent[-1][0] - recent[0][0]) / 60, 1) if len(recent) > 1 else 0,
            "samples": len(recent),
            "vm": {
                "ram_total": m["MemTotal"], "ram_used": m["MemTotal"] - m["MemAvailable"],
                "ram_peak": peak_used, "swap_total": m.get("SwapTotal", 0),
                "swap_used": m.get("SwapTotal", 0) - m.get("SwapFree", 0),
                "cpu_threads": NCPU,
                "cpu_now": round(vm_cpu[-1], 1) if vm_cpu else None,
                "cpu_avg": round(sum(vm_cpu) / len(vm_cpu), 1) if vm_cpu else None,
                "cpu_max": round(max(vm_cpu), 1) if vm_cpu else None,
                "load": os.getloadavg(),
            },
            "slots": slots,
            "windows": self.windows(),
        }
