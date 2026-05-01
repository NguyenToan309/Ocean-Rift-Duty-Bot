"""
auth_guard.py — FastAPI dependency để bảo vệ endpoint bằng JWT
Inject vào mọi route cần xác thực
"""
import logging
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


async def fetch_member_role_ids(guild_id: int, user_id: int) -> list[int]:
    """
    Gọi Discord API bằng bot token để lấy danh sách role ID của user trong guild.
    Trả [] nếu user không phải member, lỗi network, rate limit, hoặc bất kỳ exception nào.
    KHÔNG bao giờ raise — luôn trả list (rỗng nếu lỗi) để gọi an toàn.
    """
    headers = {"Authorization": f"Bot {settings.DISCORD_BOT_TOKEN}"}
    url = f"{DISCORD_API}/guilds/{guild_id}/members/{user_id}"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url, headers=headers)
        if resp.status_code == 404:
            return []  # Member không thuộc guild
        if resp.status_code == 401:
            logger.error("Discord API 401 — bot token sai hoặc bị revoke!")
            return []
        if resp.status_code == 429:
            logger.warning(f"Discord API rate limit cho {user_id}@{guild_id}")
            return []
        if resp.status_code != 200:
            logger.warning(f"Discord API trả {resp.status_code} cho member {user_id}@{guild_id}: {resp.text[:200]}")
            return []
        return [int(r) for r in resp.json().get("roles", [])]
    except Exception as e:
        # Network error, timeout, SSL, parse JSON, etc. — KHÔNG bubble lên
        logger.error(f"Lỗi fetch_member_role_ids({guild_id}, {user_id}): {type(e).__name__}: {e}")
        return []


async def require_guild_role(
    guild_id: int,
    role_name: str,
    user_payload: dict,
    session: AsyncSession,
) -> None:
    """
    Kiểm tra user (từ JWT payload) có role `role_name` (DUTY_ADMIN/MOD/MEMBER) trong guild.
    Áp dụng hierarchy ADMIN ≥ MOD ≥ MEMBER. Raise 403 nếu không đủ quyền.
    """
    user_id = int(user_payload["sub"])

    config_row = await session.execute(
        select(GuildConfig).where(GuildConfig.guild_id == guild_id)
    )
    config = config_row.scalar_one_or_none()
    if not config or not config.is_active:
        raise HTTPException(status_code=404, detail="Guild chưa setup hoặc không active")

    user_role_ids = set(await fetch_member_role_ids(guild_id, user_id))
    if not user_role_ids:
        raise HTTPException(status_code=403, detail="Bạn không phải thành viên guild này")

    # Hierarchy: ADMIN ≥ MOD ≥ MEMBER
    HIERARCHY = ["DUTY_ADMIN", "DUTY_MOD", "DUTY_MEMBER"]
    try:
        required_level = HIERARCHY.index(role_name)
    except ValueError:
        raise HTTPException(status_code=500, detail=f"Role không hợp lệ: {role_name}")

    for r in HIERARCHY[:required_level + 1]:
        rid = config.role_map.get(r)
        if rid and int(rid) in user_role_ids:
            return

    raise HTTPException(
        status_code=403,
        detail=f"Cần role {role_name} hoặc cao hơn để truy cập",
    )
