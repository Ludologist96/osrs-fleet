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
