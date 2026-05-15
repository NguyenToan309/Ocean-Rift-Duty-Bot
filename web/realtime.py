"""
realtime.py — In-memory pub/sub + WebSocket broadcaster.

Single-process (single uvicorn worker) → dict in-memory đủ dùng.
Multi-worker production → cần Redis pubsub thay thế (xem comment).

Cách dùng:
  # Trong endpoint update DB:
  from web.realtime import broadcaster
  await broadcaster.publish(guild_id, {"type": "schedule_updated", ...})

  # Client connect WebSocket /ws?guild_id=X → nhận events filter theo guild_id.
"""
from __future__ import annotations
import asyncio
import json
import logging
from typing import Any
from collections import defaultdict
from fastapi import WebSocket

logger = logging.getLogger(__name__)


class RealtimeBroadcaster:
    """
    Quản lý connections + pub/sub theo guild_id.
    Mỗi guild có 1 list các WebSocket connections của mod/admin/member.
    """

    def __init__(self):
        # guild_id → set of WebSocket
        self._connections: dict[int, set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket, guild_id: int):
        await ws.accept()
        async with self._lock:
            self._connections[guild_id].add(ws)
        logger.info(f"[WS] Client connected guild={guild_id}, total={len(self._connections[guild_id])}")

    async def disconnect(self, ws: WebSocket, guild_id: int):
        async with self._lock:
            self._connections[guild_id].discard(ws)
            if not self._connections[guild_id]:
                self._connections.pop(guild_id, None)
        logger.info(f"[WS] Client disconnected guild={guild_id}")

    async def publish(self, guild_id: int, event: dict[str, Any]):
        """
        Broadcast event tới tất cả client của guild_id.
        Lỗi từng client không ảnh hưởng client khác.
        """
        async with self._lock:
            conns = list(self._connections.get(guild_id, set()))

        if not conns:
            return

        msg = json.dumps(event, default=str)
        dead: list[WebSocket] = []
        for ws in conns:
            try:
                await ws.send_text(msg)
            except Exception as e:
                logger.debug(f"[WS] Send fail (will remove): {e}")
                dead.append(ws)

        # Remove dead connections
        if dead:
            async with self._lock:
                for ws in dead:
                    self._connections[guild_id].discard(ws)


# Global singleton
broadcaster = RealtimeBroadcaster()
