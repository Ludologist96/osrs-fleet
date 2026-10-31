"""Offline check of the Tutorial Island step rules on instructions OCR'd in live runs.

Run: DISPLAY=:99 python tests/test_tutorial_rules.py   (needs an X display for pyautogui;
in the cloud start `Xvfb :99` first and stub `mouseinfo`). Add every newly seen
instruction (with the step it should pick) to tutorial_rules_cases.json.
"""
import json, os, sys, types
sys.modules.setdefault("mouseinfo", types.ModuleType("mouseinfo"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import bots.tutorial_island as T  # noqa: E402

cases = json.load(open(os.path.join(os.path.dirname(__file__), "tutorial_rules_cases.json")))
bot = T.BotExecutor.__new__(T.BotExecutor)
bad = 0
for text, want in cases:
    got = bot._rule(text.lower())[0]
    if got != want:
        bad += 1
        print(f"FAIL want {want!r} got {got!r}: {text[:90]}")
print(f"{len(cases) - bad}/{len(cases)} ok")
sys.exit(1 if bad else 0)
