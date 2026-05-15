"""
realtime.py router — endpoint WebSocket /ws cho client lắng nghe events.

Auth: client phải đính kèm cookie access_token (HttpOnly tự động gửi).
Filter theo guild_id query param.
"""
from __future__ import annotations
import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from sqlalchemy import select

from models.base import AsyncSessionLocal
from web.realtime import broadcaster
from web.routers.auth import decode_token
from web.middleware.auth_guard import fetch_member_role_ids

logger = logging.getLogger(__name__)
router = APIRouter()


@router.websocket("/ws")
async def ws_endpoint(
    websocket: WebSocket,
    guild_id: int = Query(...),
):
    """
    WebSocket endpoint cho real-time updates.
    Client phải có cookie access_token + là thành viên guild_id.
    Server push events khi schedule/leave thay đổi.
    """
    # Auth qua cookie
    token = websocket.cookies.get("access_token")
    if not token:
        await websocket.close(code=4401, reason="Missing access token")
        return

    async with AsyncSessionLocal() as session:
        try:
            payload = await decode_token(token, session, expected_type="access")
        except Exception as e:
            logger.info(f"[WS] Auth fail: {e}")
            await websocket.close(code=4401, reason="Invalid token")
            return

    user_id = int(payload["sub"])

    # Verify member của guild
    role_ids = await fetch_member_role_ids(guild_id, user_id)
    if role_ids is None:
        await websocket.close(code=4503, reason="Discord API not responding")
        return
    if not role_ids:
        await websocket.close(code=4403, reason="Not a member of guild")
        return

    await broadcaster.connect(websocket, guild_id)
    try:
        # Giữ connection alive — chờ disconnect hoặc client gửi ping
        while True:
            # Receive (block) — nếu client disconnect → exception
            data = await websocket.receive_text()
            # Optional: respond to "ping" with "pong"
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.debug(f"[WS] Loop exited: {e}")
    finally:
        await broadcaster.disconnect(websocket, guild_id)
