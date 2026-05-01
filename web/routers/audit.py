"""
audit.py — Xem audit log (chỉ DUTY_ADMIN)
Không expose endpoint xóa — audit log là immutable
"""
import logging
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Request

from models.base import get_db
from models.audit_log import AuditLog
from web.middleware.auth_guard import require_auth, require_guild_role
from web.middleware.rate_limit import limiter

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("/logs")
@limiter.limit("20/minute")
async def get_audit_logs(
    request: Request,
    guild_id: int = Query(...),
    action: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """
    Lấy danh sách audit log — DUTY_MOD hoặc DUTY_ADMIN.
    Web gọi Discord API bằng bot token để verify role của user trong guild.
    """
    await require_guild_role(guild_id, "DUTY_MOD", current_user, session)

    offset = (page - 1) * page_size
    query = (
        select(AuditLog)
        .where(AuditLog.guild_id == guild_id)
        .order_by(AuditLog.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )

    if action:
        query = query.where(AuditLog.action == action)

    result = await session.execute(query)
    logs = result.scalars().all()

    # Đếm tổng
    count_query = select(func.count(AuditLog.id)).where(AuditLog.guild_id == guild_id)
    if action:
        count_query = count_query.where(AuditLog.action == action)
    total = (await session.execute(count_query)).scalar() or 0

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "id": log.id,
                "user_id": log.user_id,
                "username": log.username,
                "action": log.action,
                "detail": log.detail,
                "ip_address": log.ip_address,
                "created_at": log.created_at.isoformat() if log.created_at else None,
            }
            for log in logs
        ],
    }
