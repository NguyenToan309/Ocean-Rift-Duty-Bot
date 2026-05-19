"""
auth_guard.py — FastAPI dependency để bảo vệ endpoint bằng JWT
Inject vào mọi route cần xác thực

Role cache:
- fetch_member_role_ids() kết quả được cache in-memory 60 giây
- Phân biệt 2 trường hợp: None = lỗi mạng, [] = không phải member
- Cache giúp tránh gọi Discord API mỗi request (tránh rate limit 429)
"""
import asyncio
import logging
import time
import json
import httpx
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from models.base import get_db
from models.guild import GuildConfig
from bot.config import settings
from web.routers.auth import decode_token

logger = logging.getLogger(__name__)
DISCORD_API = "https://discord.com/api/v10"

# In-memory cache: key = "guild_id:user_id" → (role_ids: list[int] | None, timestamp: float)
# None = lỗi mạng/rate-limit (bảo toàn access thay vì reject oan)
# [] = không phải member
#
# ⚠️ MULTI-WORKER WARNING: Cache này lưu in-memory per-process. Nếu chạy uvicorn
# với nhiều worker (--workers N > 1), mỗi worker có cache riêng → request
# round-robin sang worker khác sẽ miss cache → vẫn đúng nhưng tốn API call.
# Production multi-worker: thay bằng Redis (key = f"role:{guild_id}:{user_id}").
_ROLE_CACHE: dict[str, tuple[list[int] | None, float]] = {}
_ROLE_CACHE_TTL = 60.0  # 60 giây
# Lock cho mỗi (guild_id, user_id) để tránh thundering herd: nếu 10 request đồng thời
# cùng user vào → chỉ 1 request hit Discord API, các request khác đợi và dùng cache.
_ROLE_LOCKS: dict[str, asyncio.Lock] = {}
_LOCKS_GUARD = asyncio.Lock()


async def _get_role_lock(key: str) -> asyncio.Lock:
    """Lấy/tạo lock cho key cụ thể, atomic dưới _LOCKS_GUARD"""
    async with _LOCKS_GUARD:
        lock = _ROLE_LOCKS.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _ROLE_LOCKS[key] = lock
            # Cleanup nếu locks dict quá lớn
            if len(_ROLE_LOCKS) > 1000:
                # Xoá các lock không bị giữ
                for k in list(_ROLE_LOCKS.keys()):
                    if not _ROLE_LOCKS[k].locked():
                        _ROLE_LOCKS.pop(k, None)
        return lock


def _get_cached_roles(guild_id: int, user_id: int) -> list[int] | None | str:
    """
    Trả về:
    - list[int]: cached role IDs (có thể [])
    - None: cached "lỗi mạng" result
    - "miss": cache miss, cần fetch
    """
    key = f"{guild_id}:{user_id}"
    entry = _ROLE_CACHE.get(key)
    if entry is None:
        return "miss"
    roles, ts = entry
    if time.monotonic() - ts > _ROLE_CACHE_TTL:
        del _ROLE_CACHE[key]
        return "miss"
    return roles


def _set_cached_roles(guild_id: int, user_id: int, roles: list[int] | None) -> None:
    key = f"{guild_id}:{user_id}"
    _ROLE_CACHE[key] = (roles, time.monotonic())
    # Cleanup expired entries khi cache lớn hơn 500 entries
    if len(_ROLE_CACHE) > 500:
        now = time.monotonic()
        expired = [k for k, (_, ts) in _ROLE_CACHE.items() if now - ts > _ROLE_CACHE_TTL]
        for k in expired:
            del _ROLE_CACHE[k]


async def get_current_user(
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> dict:
    """
    Dependency: lấy JWT từ HttpOnly cookie, decode, trả về payload.
    Raise 401 nếu token thiếu hoặc không hợp lệ.
    """
    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=401, detail="Chưa đăng nhập")
    return await decode_token(token, session, expected_type="access")


async def require_auth(user: dict = Depends(get_current_user)) -> dict:
    """Shortcut dependency — dùng trong route params"""
    return user


async def fetch_member_role_ids(guild_id: int, user_id: int) -> list[int] | None:
    """
    Lấy danh sách role ID của user trong guild từ Discord API.

    Trả về:
    - list[int]: danh sách role IDs ([] nếu user không phải member)
    - None: lỗi mạng / rate limit / Discord API down

    Có cache in-memory 60 giây để tránh gọi Discord API mỗi request.
    KHÔNG bao giờ raise — luôn trả giá trị để caller xử lý.
    """
    # Check cache trước (fast path, không cần lock)
    cached = _get_cached_roles(guild_id, user_id)
    if cached != "miss":
        return cached  # Có thể là list hoặc None (cached error)

    # Slow path: lock per-key để tránh thundering herd
    key = f"{guild_id}:{user_id}"
    lock = await _get_role_lock(key)
    async with lock:
        # Double-check trong critical section: có thể request khác đã fetch xong
        cached = _get_cached_roles(guild_id, user_id)
        if cached != "miss":
            return cached

    headers = {"Authorization": f"Bot {settings.DISCORD_BOT_TOKEN}"}
    url = f"{DISCORD_API}/guilds/{guild_id}/members/{user_id}"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url, headers=headers)

        if resp.status_code == 404:
            # User không phải member guild — cache []
            _set_cached_roles(guild_id, user_id, [])
            return []

        if resp.status_code == 401:
            logger.error("Discord API 401 — bot token sai hoặc bị revoke!")
            _set_cached_roles(guild_id, user_id, None)
            return None

        if resp.status_code == 429:
            logger.warning(f"Discord API rate limit cho {user_id}@{guild_id}")
            # Không cache rate-limit (retry sẽ thành công)
            return None

        if resp.status_code != 200:
            logger.warning(
                f"Discord API trả {resp.status_code} cho member {user_id}@{guild_id}: "
                f"{resp.text[:200]}"
            )
            _set_cached_roles(guild_id, user_id, None)
            return None

        roles = [int(r) for r in resp.json().get("roles", [])]
        _set_cached_roles(guild_id, user_id, roles)
        return roles

    except httpx.TimeoutException:
        logger.warning(f"Discord API timeout khi fetch roles {user_id}@{guild_id}")
        return None
    except Exception as e:
        logger.error(f"Lỗi fetch_member_role_ids({guild_id}, {user_id}): {type(e).__name__}: {e}")
        return None


def invalidate_role_cache(guild_id: int, user_id: int) -> None:
    """Xoá cache khi role của user thay đổi (VD: sau /setup role)"""
    key = f"{guild_id}:{user_id}"
    _ROLE_CACHE.pop(key, None)


async def has_guild_role(
    guild_id: int,
    role_name: str,
    user_payload: dict,
    session: AsyncSession,
) -> bool:
    """
    Check user có role `role_name` (hoặc cao hơn) trong guild — KHÔNG raise.
    Trả True/False. Discord API lỗi → False (an toàn).

    Dùng khi cần optional check (vd: cho phép admin bypass ownership).
    """
    user_id = int(user_payload["sub"])
    config_row = await session.execute(
        select(GuildConfig).where(GuildConfig.guild_id == guild_id)
    )
    config = config_row.scalar_one_or_none()
    if not config or not config.is_active:
        return False

    user_role_ids_raw = await fetch_member_role_ids(guild_id, user_id)
    if user_role_ids_raw is None or not user_role_ids_raw:
        return False

    user_role_ids = set(user_role_ids_raw)
    HIERARCHY = ["DUTY_ADMIN", "DUTY_MOD", "DUTY_MEMBER"]
    try:
        required_level = HIERARCHY.index(role_name)
    except ValueError:
        return False

    for r in HIERARCHY[:required_level + 1]:
        rid = config.role_map.get(r)
        if rid and int(rid) in user_role_ids:
            return True
    return False


async def require_guild_role(
    guild_id: int,
    role_name: str,
    user_payload: dict,
    session: AsyncSession,
) -> None:
    """
    Kiểm tra user có role `role_name` (DUTY_ADMIN/MOD/MEMBER) trong guild.
    Áp dụng hierarchy ADMIN ≥ MOD ≥ MEMBER.

    Phân biệt 3 trường hợp:
    - roles = None → Discord API lỗi → 503 (tạm thời không check được, thử lại sau)
    - roles = [] → user không phải member → 403
    - roles != [] nhưng không có role phù hợp → 403
    """
    user_id = int(user_payload["sub"])

    config_row = await session.execute(
        select(GuildConfig).where(GuildConfig.guild_id == guild_id)
    )
    config = config_row.scalar_one_or_none()
    if not config or not config.is_active:
        raise HTTPException(status_code=404, detail="Guild chưa setup hoặc không active")

    user_role_ids_raw = await fetch_member_role_ids(guild_id, user_id)

    # None = lỗi mạng — không reject oan, trả 503
    if user_role_ids_raw is None:
        raise HTTPException(
            status_code=503,
            detail="Không thể xác thực quyền hạn lúc này (Discord API không phản hồi). Thử lại sau."
        )

    # [] = không phải member
    if not user_role_ids_raw:
        raise HTTPException(status_code=403, detail="Bạn không phải thành viên guild này")

    user_role_ids = set(user_role_ids_raw)

    HIERARCHY = ["DUTY_ADMIN", "DUTY_MOD", "DUTY_MEMBER"]
    try:
        required_level = HIERARCHY.index(role_name)
    except ValueError:
        raise HTTPException(status_code=500, detail=f"Role không hợp lệ: {role_name}")

    # Kiểm tra user có role nào từ level cao nhất đến required_level
    for r in HIERARCHY[:required_level + 1]:
        rid = config.role_map.get(r)
        if rid and int(rid) in user_role_ids:
            return  # Có quyền

    raise HTTPException(
        status_code=403,
        detail=f"Cần role {role_name} hoặc cao hơn để truy cập",
    )
