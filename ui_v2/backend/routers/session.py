"""Game session API: is the slot in game, and log it in (Play Now) - /api/session/*."""

from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from ui_v2.backend.services.bot_manager import BotManagerService

router = APIRouter(prefix="/api/session", tags=["session"])


@router.get("/state")
def session_state() -> Dict[str, Any]:
    from core import login
    try:
        return login.state()
    except Exception as e:
        return {"state": "unknown", "error": f"{type(e).__name__}: {e}"}


@router.post("/login")
def session_login(only_play_now: bool = False) -> Dict[str, Any]:
    if BotManagerService().current_bot:
        raise HTTPException(status_code=409, detail="A bot is running in this slot")
    from core import login
    from core.control import ScriptControl
    ScriptControl().reset()  # clear a stop flag left by the last bot, or clicks refuse
    try:
        return login.login(only_play_now=only_play_now)
    except Exception as e:
        return {"state": "unknown", "error": f"{type(e).__name__}: {e}"}


@router.get("/inventory")
def session_inventory() -> Dict[str, Any]:
    """Which inventory slots hold something (for checking the slot detection)."""
    from core import login, inventory
    try:
        sc = login._screenshot(login._window())
        sd = [round(v, 1) for _, v in inventory.slots(sc)]
        return {"used": sum(1 for v in sd if v > inventory.ITEM_STDDEV), "stddev": sd}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


@router.get("/screen_text")
def session_screen_text() -> Dict[str, Any]:
    """OCR of the message in the middle of the login screen."""
    from core import login
    try:
        return {"text": login.dialog_text(login._screenshot(login._window()))}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


# ------------------------------------------------------------ a remote hand (no bot running)
# For setting up / checking an account by hand from the fleet dashboard: read the words on
# the screen, click a point (humanlike move + press), press a key, type text.
def _idle_slot():
    if BotManagerService().current_bot:
        raise HTTPException(status_code=409, detail="A bot is running in this slot")


@router.get("/words")
def session_words(box: str = "") -> Dict[str, Any]:
    """OCR words with boxes (window coords). box=x1,y1,x2,y2 (default: whole window)."""
    from core import login
    from core.screen_words import words, lines
    try:
        sc = login._screenshot(login._window())
        b = tuple(int(v) for v in box.split(",")) if box else None
        return {"lines": [{k: v for k, v in ln.items() if k != "words"} for ln in lines(words(sc, b))]}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


@router.post("/click")
def session_click(x: int, y: int, button: str = "left") -> Dict[str, Any]:
    """Move to (x, y) in window coords like a hand would, then press."""
    _idle_slot()
    import random, time
    from core import login
    from core.input import mouse_control
    from core.control import ScriptControl
    ScriptControl().reset()
    win = login._window()
    win.bring_to_focus()
    mouse_control.move_to(win.left + x, win.top + y)
    time.sleep(random.uniform(0.08, 0.2))
    mouse_control.press(mouse_control.ClickType.RIGHT if button == "right" else mouse_control.ClickType.LEFT)
    return {"ok": True}


@router.post("/key")
def session_key(key: str = "", text: str = "") -> Dict[str, Any]:
    """Press one key (key=esc, enter, ...) or type text."""
    _idle_slot()
    from core import login
    from core.input import keys
    login._window().bring_to_focus()
    if text:
        keys.write(text, delay=0.08)
    if key:
        keys.press_and_release(key)
    return {"ok": True}


@router.post("/tab")
def session_tab(name: str) -> Dict[str, Any]:
    """Click a side-panel tab by its icon (inventory, settings, logout, skills)."""
    _idle_slot()
    from core import login, account_setup
    from core.control import ScriptControl
    ScriptControl().reset()
    return {"ok": account_setup.tab(login._window(), name)}


@router.post("/setup")
def session_setup(what: str = "levelup") -> Dict[str, Any]:
    """One-time account settings (no bot running): what=levelup -> level-up pop-ups off."""
    _idle_slot()
    from core import login, account_setup
    from core.control import ScriptControl
    ScriptControl().reset()
    if what != "levelup":
        raise HTTPException(status_code=400, detail="unknown setup")
    try:
        return account_setup.disable_levelup_popup(login._window())
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
