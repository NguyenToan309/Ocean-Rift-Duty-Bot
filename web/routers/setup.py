"""
setup.py — Endpoint xem cấu hình setup của guild (role_map, channel_ids, timezone).

Hiện chỉ có GET (read-only). Edit qua slash command `/setup role/channel/timezone`
để giữ audit log nhất quán và check Discord permission của bot.
"""
import logging
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.base import get_db
from models.guild import GuildConfig
from web.middleware.auth_guard import require_auth, require_guild_role
from web.middleware.rate_limit import limiter
from web.utils.discord_resolver import resolve_role_name

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/setup", tags=["setup"])


@router.get("/roles")
@limiter.limit("30/minute")
async def get_role_map(
    request: Request,
    guild_id: int = Query(...),
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """Trả role_map của guild kèm Discord role name đã resolve.

    Quyền: bất kỳ thành viên có role DUTY_MEMBER trở lên trong guild.

    Response:
    {
      "role_map": {
        "DUTY_ADMIN": {"role_id": "123", "role_name": "Cốc Chủ Thần Y"} | null,
        "DUTY_MOD":   {...} | null,
        "DUTY_MEMBER": {...} | null
      },
      "guild_id": 123,
      "guild_name": "Capy Medic"
    }

    Discord API fail (rate limit/perm) → role_name = null nhưng role_id vẫn có.
    """
    await require_guild_role(guild_id, "DUTY_MEMBER", current_user, session)

    cfg_row = await session.execute(
        select(GuildConfig).where(GuildConfig.guild_id == guild_id)
    )
    cfg = cfg_row.scalar_one_or_none()
    if not cfg:
        raise HTTPException(status_code=404, detail="Guild chưa setup")

    raw = cfg.role_map or {}
    result: dict[str, dict | None] = {}
    for system_role in ("DUTY_ADMIN", "DUTY_MOD", "DUTY_MEMBER"):
        rid = raw.get(system_role)
        if not rid:
            result[system_role] = None
            continue
        try:
            role_id_int = int(rid)
        except (TypeError, ValueError):
            result[system_role] = None
            continue
        role_name = await resolve_role_name(guild_id, role_id_int)
        result[system_role] = {
            "role_id": str(role_id_int),
            # resolve_role_name trả "@role-name" — strip @ cho display sạch
            "role_name": role_name[1:] if role_name and role_name.startswith("@") else role_name,
        }

    return {
        "guild_id": str(guild_id),
        "guild_name": cfg.guild_name,
        "role_map": result,
    }
