"""
discord_role_sync.py — Tự động cấp/gỡ Discord role khi staff đổi chức vụ.

Luồng:
1. Đọc GuildConfig.position_role_map[new_position] → system_role (DUTY_ADMIN/MOD/MEMBER)
2. Đọc GuildConfig.role_map[system_role] → Discord role ID thực tế
3. Gọi Discord REST API: gỡ role cũ (nếu có) + cấp role mới
4. Ghi audit log riêng cho mỗi hành động role

Dùng được từ cả web (FastAPI) lẫn bot (discord.py) — đều dùng httpx + bot token.
KHÔNG raise — luôn trả dict {success, added, removed, errors} để caller xử lý.
"""
from __future__ import annotations
import logging
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.guild import GuildConfig
from models.audit_log import AuditLog, AuditAction
from bot.config import settings
from bot.utils.time_utils import utcnow

logger = logging.getLogger(__name__)

DISCORD_API = "https://discord.com/api/v10"


async def sync_staff_position_role(
    *,
    session: AsyncSession,
    guild_id: int,
    user_id: int,
    new_position: str | None,
    old_position: str | None = None,
    actor_id: int | None = None,
    actor_username: str | None = None,
    reason: str = "Đồng bộ role theo chức vụ",
    write_audit: bool = True,
) -> dict[str, Any]:
    """
    Sync Discord role của user theo chức vụ trong DB.

    Args:
        session: SQLAlchemy session (CHƯA commit ngoài)
        guild_id: Discord guild ID
        user_id: Discord user ID cần đổi role
        new_position: Chức vụ mới (VD: "VIEN_TRUONG"). None = không cấp role mới.
        old_position: Chức vụ cũ. None = không gỡ role cũ.
        actor_id: User ID người thực hiện (để audit)
        actor_username: Username người thực hiện
        reason: Lý do (sẽ gửi qua X-Audit-Log-Reason header)
        write_audit: Có ghi AuditLog không (default True)

    Returns:
        {
          "success": bool,
          "skipped_reason": str | None,
          "added_role_id": str | None,
          "removed_role_id": str | None,
          "errors": list[str],
        }
    """
    result: dict[str, Any] = {
        "success": False,
        "skipped_reason": None,
        "added_role_id": None,
        "removed_role_id": None,
        "errors": [],
    }

    if not settings.DISCORD_BOT_TOKEN:
        result["skipped_reason"] = "DISCORD_BOT_TOKEN không có"
        result["errors"].append(result["skipped_reason"])
        logger.warning(f"[role-sync] skip: {result['skipped_reason']}")
        return result

    # Load guild config
    cfg_row = await session.execute(
        select(GuildConfig).where(GuildConfig.guild_id == guild_id)
    )
    config = cfg_row.scalar_one_or_none()
    if not config:
        result["skipped_reason"] = "Guild config không tồn tại"
        result["errors"].append(result["skipped_reason"])
        return result

    position_role_map: dict = config.position_role_map or {}
    role_map: dict = config.role_map or {}

    # Resolve new role
    new_discord_role_id = None
    if new_position:
        new_system_role = position_role_map.get(new_position)
        if new_system_role:
            rid = role_map.get(new_system_role)
            if rid:
                try:
                    new_discord_role_id = int(rid)
                except (TypeError, ValueError):
                    pass

    # Resolve old role
    old_discord_role_id = None
    if old_position:
        old_system_role = position_role_map.get(old_position)
        if old_system_role:
            rid = role_map.get(old_system_role)
            if rid:
                try:
                    old_discord_role_id = int(rid)
                except (TypeError, ValueError):
                    pass

    # Same role on both sides → không cần làm gì
    if old_discord_role_id and new_discord_role_id and old_discord_role_id == new_discord_role_id:
        result["success"] = True
        result["skipped_reason"] = "Role giống nhau giữa chức vụ cũ và mới"
        return result

    # Không có gì để map → skip (admin chưa config)
    if not new_discord_role_id and not old_discord_role_id:
        result["success"] = True
        result["skipped_reason"] = "Chưa config position_role_map cho chức vụ này"
        return result

    headers = {
        "Authorization": f"Bot {settings.DISCORD_BOT_TOKEN}",
        "X-Audit-Log-Reason": (reason or "Homie Medic auto-sync")[:512],
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        # 1) Gỡ role cũ (nếu có và khác role mới)
        if old_discord_role_id:
            try:
                url = f"{DISCORD_API}/guilds/{guild_id}/members/{user_id}/roles/{old_discord_role_id}"
                resp = await client.delete(url, headers=headers)
                if resp.status_code in (200, 204):
                    result["removed_role_id"] = str(old_discord_role_id)
                    logger.info(
                        f"[role-sync] Removed role {old_discord_role_id} from user {user_id} "
                        f"in guild {guild_id} (old position={old_position})"
                    )
                elif resp.status_code == 404:
                    # User đã rời guild hoặc role không tồn tại — không phải lỗi
                    logger.info(f"[role-sync] Remove role 404 (user/role không tồn tại)")
                elif resp.status_code == 403:
                    msg = f"Bot không có quyền gỡ role {old_discord_role_id} (role cao hơn bot?)"
                    result["errors"].append(msg)
                    logger.warning(f"[role-sync] {msg}")
                else:
                    msg = f"Gỡ role {old_discord_role_id} thất bại: HTTP {resp.status_code} {resp.text[:200]}"
                    result["errors"].append(msg)
                    logger.warning(f"[role-sync] {msg}")
            except Exception as e:
                msg = f"Exception khi gỡ role: {type(e).__name__}: {e}"
                result["errors"].append(msg)
                logger.error(f"[role-sync] {msg}", exc_info=True)

        # 2) Cấp role mới (nếu có)
        if new_discord_role_id:
            try:
                url = f"{DISCORD_API}/guilds/{guild_id}/members/{user_id}/roles/{new_discord_role_id}"
                resp = await client.put(url, headers=headers)
                if resp.status_code in (200, 204):
                    result["added_role_id"] = str(new_discord_role_id)
                    result["success"] = True
                    logger.info(
                        f"[role-sync] Added role {new_discord_role_id} to user {user_id} "
                        f"in guild {guild_id} (new position={new_position})"
                    )
                elif resp.status_code == 404:
                    msg = "User không phải member guild hoặc role không tồn tại"
                    result["errors"].append(msg)
                    logger.warning(f"[role-sync] Add role 404: {msg}")
                elif resp.status_code == 403:
                    msg = f"Bot không có quyền cấp role {new_discord_role_id} (role cao hơn bot?)"
                    result["errors"].append(msg)
                    logger.warning(f"[role-sync] {msg}")
                else:
                    msg = f"Cấp role {new_discord_role_id} thất bại: HTTP {resp.status_code} {resp.text[:200]}"
                    result["errors"].append(msg)
                    logger.warning(f"[role-sync] {msg}")
            except Exception as e:
                msg = f"Exception khi cấp role: {type(e).__name__}: {e}"
                result["errors"].append(msg)
                logger.error(f"[role-sync] {msg}", exc_info=True)
        else:
            # Chỉ gỡ, không cấp → coi như success nếu không có lỗi
            if not result["errors"]:
                result["success"] = True

    # 3) Ghi audit log riêng cho role sync (không commit — caller chịu trách nhiệm)
    if write_audit and (result["added_role_id"] or result["removed_role_id"] or result["errors"]):
        session.add(AuditLog(
            guild_id=guild_id,
            user_id=actor_id or 0,
            username=actor_username or "system",
            action="STAFF_ROLE_SYNCED",
            detail={
                "staff_user_id": str(user_id),
                "old_position": old_position,
                "new_position": new_position,
                "added_role_id": result["added_role_id"],
                "removed_role_id": result["removed_role_id"],
                "errors": result["errors"],
                "reason": reason[:500] if reason else None,
            },
            created_at=utcnow(),
        ))

    return result


def is_auto_sync_enabled(config: GuildConfig) -> bool:
    """Auto-sync chỉ enable nếu position_role_map có ít nhất 1 entry."""
    if not config or not config.is_active:
        return False
    return bool(config.position_role_map)
