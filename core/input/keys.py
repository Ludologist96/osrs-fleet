"""
Keyboard output that works both on a normal Windows desktop and on a Linux
virtual display (one RuneLite per Xvfb screen on the fleet VM).

Drop-in replacement for the parts of the `keyboard` package the bots use:

    from core.input import keys as keyboard
    keyboard.press('shift'); ...; keyboard.release('shift')
    keyboard.press_and_release('space')
    keyboard.write('Iron ore', delay=.2)

Windows: forwards straight to the `keyboard` package (unchanged behavior).

Linux: the `keyboard` package writes to the kernel input device and needs
root, so its keys would never reach the bot's own virtual screen. Instead we
send XTest events through pyautogui, which talks to the X display named in
$DISPLAY, so every bot types only into its own screen.

On Linux, press() of a non-modifier key (enter, space, letters, numbers, ...)
is sent as a full tap (down + up). Several call sites call press('enter') or
press('space') without a matching release(); holding those keys down on an X
display would leave them stuck. Modifiers (shift/ctrl/alt) and arrow keys
are held until release(), which is how the bots use them (shift-drop, camera
rotation).
"""

from __future__ import annotations

import sys

IS_LINUX = sys.platform.startswith("linux")

if not IS_LINUX:
    import keyboard as _kb

    def press(key: str) -> None:
        _kb.press(key)

    def release(key: str) -> None:
        _kb.release(key)

    def press_and_release(key: str) -> None:
        _kb.press_and_release(key)

    def write(text: str, delay: float = 0) -> None:
        _kb.write(text, delay=delay)

    def is_pressed(key: str) -> bool:
        return _kb.is_pressed(key)

else:
    import pyautogui

    from core.logger import get_logger

    _log = get_logger("Keys")

    # `keyboard` package names -> pyautogui names
    _ALIASES = {
        "page up": "pageup",
        "page down": "pagedown",
        "escape": "esc",
        "return": "enter",
        "spacebar": "space",
        "control": "ctrl",
        "left ctrl": "ctrlleft",
        "right ctrl": "ctrlright",
        "left shift": "shiftleft",
        "right shift": "shiftright",
        "left alt": "altleft",
        "right alt": "altright",
        "windows": "win",
        "left windows": "winleft",
        "right windows": "winright",
        "up arrow": "up",
        "down arrow": "down",
        "left arrow": "left",
        "right arrow": "right",
        "caps lock": "capslock",
        "num lock": "numlock",
        "print screen": "printscreen",
        "delete": "del",
    }

    _HOLDABLE = {
        "shift", "shiftleft", "shiftright",
        "ctrl", "ctrlleft", "ctrlright",
        "alt", "altleft", "altright",
        "win", "winleft", "winright",
        "up", "down", "left", "right",
    }

    _held: set[str] = set()

    def _name(key) -> str:
        k = str(key).strip().lower()
        k = _ALIASES.get(k, k)
        if k not in pyautogui.KEYBOARD_KEYS:
            _log.warning(f"Unknown key name '{key}' (sending as '{k}')")
        return k

    def _parts(key) -> list[str]:
        return [_name(p) for p in str(key).split("+") if p.strip()]

    def press(key: str) -> None:
        parts = _parts(key)
        if len(parts) > 1:
            pyautogui.hotkey(*parts)
            return
        k = parts[0]
        if k in _HOLDABLE:
            pyautogui.keyDown(k)
            _held.add(k)
        else:
            pyautogui.press(k)

    def release(key: str) -> None:
        for k in reversed(_parts(key)):
            if k in _held or k in _HOLDABLE:
                pyautogui.keyUp(k)
                _held.discard(k)
            # non-holdable keys were already released by press()

    def press_and_release(key: str) -> None:
        parts = _parts(key)
        if len(parts) > 1:
            pyautogui.hotkey(*parts)
        else:
            pyautogui.press(parts[0])

    def write(text: str, delay: float = 0) -> None:
        pyautogui.write(str(text), interval=delay)

    def is_pressed(key: str) -> bool:
        # No global key listening on the virtual displays.
        return _name(key) in _held
