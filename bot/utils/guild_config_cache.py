"""
guild_config_cache.py — TTL cache cho GuildConfig.

Bot có on_message listener chạy với MỌI tin nhắn trong MỌI channel của
guild. Mỗi lần listener gọi `select GuildConfig where guild_id=?` là 1
round-trip DB. Trong guild active (vài msg/s) → DB load tỉ lệ trực tiếp
với chat activity.

Cache này:
- TTL 60s (đủ ngắn để admin đổi config qua web thấy hiệu lực)
- Per-guild key
- Trả `None` cũng cache (để không spam DB khi guild chưa setup)
- Thread-safe qua asyncio.Lock per-key

Invalidate khi:
- Web admin gọi POST /api/setup → invalidate_guild_cache(guild_id)
- Bot tự gọi /setup → invalidate_guild_cache(guild_id)
"""
from __future__ import annotations
import time
import asyncio
from typing import TYPE_CHECKING

from sqlalchemy import select

from models.base import AsyncSessionLocal
from models.guild import GuildConfig

if TYPE_CHECKING:
    pass

_TTL_SECONDS = 60.0

# {guild_id: (cached_at_monotonic, cfg_or_None)}
_cache: dict[int, tuple[float, "GuildConfig | None"]] = {}
_locks: dict[int, asyncio.Lock] = {}


def _get_lock(guild_id: int) -> asyncio.Lock:
    lk = _locks.get(guild_id)
    if lk is None:
        lk = asyncio.Lock()
        _locks[guild_id] = lk
    return lk


async def get_guild_config(guild_id: int) -> "GuildConfig | None":
    """Lấy GuildConfig với TTL cache 60s. Đảm bảo single-flight per guild."""
    now = time.monotonic()
    cached = _cache.get(guild_id)
    if cached and (now - cached[0]) < _TTL_SECONDS:
        return cached[1]

    lock = _get_lock(guild_id)
    async with lock:
        # Double-check sau khi acquire lock
        cached = _cache.get(guild_id)
        if cached and (time.monotonic() - cached[0]) < _TTL_SECONDS:
            return cached[1]

        async with AsyncSessionLocal() as session:
            row = await session.execute(
                select(GuildConfig).where(GuildConfig.guild_id == guild_id)
            )
            cfg = row.scalar_one_or_none()
            # Expunge để khỏi giữ session ref
            if cfg is not None:
                session.expunge(cfg)

        _cache[guild_id] = (time.monotonic(), cfg)
        return cfg


def invalidate_guild_cache(guild_id: int) -> None:
    """Gọi sau khi update GuildConfig để cache tự refresh ở request tiếp theo."""
    _cache.pop(guild_id, None)


def clear_cache() -> None:
    """Xoá toàn bộ cache — dùng trong test hoặc reload."""
    _cache.clear()


# ─── Auto-invalidate qua SQLAlchemy event ────────────────────────────────────
# Bất kỳ chỗ nào trong code làm INSERT/UPDATE/DELETE GuildConfig đều tự động
# trigger invalidate — không cần dev nhớ gọi tay sau commit.
def _register_invalidation_hook() -> None:
    from sqlalchemy import event

    def _on_after_flush_instance(_session, _ctx, instance, _is_modified):
        if isinstance(instance, GuildConfig):
            invalidate_guild_cache(instance.guild_id)

    def _on_after_delete(_mapper, _connection, instance):
        if isinstance(instance, GuildConfig):
            invalidate_guild_cache(instance.guild_id)

    def _on_after_insert(_mapper, _connection, instance):
        if isinstance(instance, GuildConfig):
            invalidate_guild_cache(instance.guild_id)

    def _on_after_update(_mapper, _connection, instance):
        if isinstance(instance, GuildConfig):
            invalidate_guild_cache(instance.guild_id)

    event.listen(GuildConfig, "after_insert", _on_after_insert)
    event.listen(GuildConfig, "after_update", _on_after_update)
    event.listen(GuildConfig, "after_delete", _on_after_delete)


_register_invalidation_hook()
