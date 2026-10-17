"""Logging API router + WebSocket bridge to core logger."""

from typing import Any, Dict
from fastapi import APIRouter

router = APIRouter(tags=["logging"])


@router.get("/api/logging/port")
def get_logging_port() -> Dict[str, Any]:
    from core.logger import get_websocket_port
    port = get_websocket_port()
    return {"port": port}


@router.get("/api/logging/recent")
def get_recent_logs(n: int = 200) -> Dict[str, Any]:
    from core.logger import get_recent_logs as _recent
    return {"lines": _recent(max(1, min(n, 1000)))}
