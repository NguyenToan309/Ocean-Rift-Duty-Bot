"""
dashboard.py — API trả dữ liệu cho web dashboard
Tất cả endpoint yêu cầu xác thực JWT
"""
import logging
from fastapi import APIRouter, Depends, HTTPException, Query, Path
from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession

from models.base import get_db
from models.duty_log import DutyLog
from models.guild import GuildConfig
from models.audit_log import AuditLog, AuditAction
from web.middleware.auth_guard import require_auth, require_guild_role, fetch_member_role_ids
from web.middleware.rate_limit import limiter
from bot.utils.time_utils import get_period_range, get_custom_range, minutes_to_hhmm, utcnow
from fastapi import Request

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/me")
@limiter.limit("30/minute")
async def get_me(
    request: Request,
    current_user: dict = Depends(require_auth),
):
    """Trả về user info từ JWT — dùng cho frontend hiển thị + check ownership"""
    return {
        "user_id": str(current_user.get("sub")),
        "username": current_user.get("username", ""),
    }


@router.get("/me/guilds")
@limiter.limit("10/minute")
async def get_my_guilds(
    request: Request,
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """
    Trả về danh sách guilds đã setup mà user là thành viên,
    kèm role level cao nhất của user trong guild đó.
    Dùng để frontend pick guild + biết quyền.
    """
    user_id = int(current_user["sub"])

    # Lấy tất cả guilds đang active từ DB
    rows = await session.execute(
        select(GuildConfig).where(GuildConfig.is_active == True)  # noqa: E712
    )
    configs = rows.scalars().all()

    HIERARCHY = ["DUTY_ADMIN", "DUTY_MOD", "DUTY_MEMBER"]
    result = []

    for cfg in configs:
        # Hỏi Discord user có trong guild không + roles của user
        user_role_ids = set(await fetch_member_role_ids(cfg.guild_id, user_id))
        if not user_role_ids:
            continue  # User không phải thành viên guild này

        # Tìm role level cao nhất
        highest_level = None
        for role_name in HIERARCHY:
            rid = cfg.role_map.get(role_name)
            if rid and int(rid) in user_role_ids:
                highest_level = role_name
                break

        if not highest_level:
            continue  # User trong guild nhưng không có role chấm công nào

        result.append({
            "guild_id": str(cfg.guild_id),
            "guild_name": cfg.guild_name,
            "timezone": cfg.timezone,
            "role_level": highest_level,
            "is_admin": highest_level == "DUTY_ADMIN",
            "is_mod": highest_level in ("DUTY_ADMIN", "DUTY_MOD"),
        })

    return {"guilds": result}


@router.get("/overview")
@limiter.limit("30/minute")
async def get_overview(
    request: Request,
    guild_id: int = Query(..., description="Discord Guild ID"),
    period: str = Query("week", description="day|week|month|quarter"),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """
    Tổng quan: tổng ca, tổng phút, số thành viên, top 5
    Guild isolation: chỉ trả dữ liệu của guild_id được request
    """
    await require_guild_role(guild_id, "DUTY_MEMBER", current_user, session)

    # Lấy timezone guild
    tz_result = await session.execute(
        select(GuildConfig.timezone).where(GuildConfig.guild_id == guild_id)
    )
    guild_tz = tz_result.scalar_one_or_none() or "Asia/Ho_Chi_Minh"

    if date_from and date_to:
        start, end = get_custom_range(date_from, date_to, guild_tz)
    else:
        start, end = get_period_range(period, tz_str=guild_tz)

    # Tổng ca và tổng phút
    totals = await session.execute(
        select(
            func.count(DutyLog.id).label("total_sessions"),
            func.coalesce(func.sum(DutyLog.duration_minutes), 0).label("total_minutes"),
            func.count(func.distinct(DutyLog.user_id)).label("total_members"),
        )
        .where(DutyLog.guild_id == guild_id)
        .where(DutyLog.started_at >= start)
        .where(DutyLog.started_at <= end)
    )
    row = totals.first()

    # Top 5
    top5 = await session.execute(
        select(
            DutyLog.username,
            func.sum(DutyLog.duration_minutes).label("total_minutes"),
            func.count(DutyLog.id).label("sessions"),
        )
        .where(DutyLog.guild_id == guild_id)
        .where(DutyLog.started_at >= start)
        .where(DutyLog.started_at <= end)
        .group_by(DutyLog.user_id, DutyLog.username)
        .order_by(func.sum(DutyLog.duration_minutes).desc())
        .limit(5)
    )

    return {
        "total_sessions": row.total_sessions,
        "total_minutes": row.total_minutes,
        "total_members": row.total_members,
        "total_hhmm": minutes_to_hhmm(row.total_minutes),
        "top5": [
            {
                "username": r.username,
                "total_minutes": r.total_minutes,
                "total_hhmm": minutes_to_hhmm(r.total_minutes),
                "sessions": r.sessions,
            }
            for r in top5.all()
        ],
    }


@router.get("/ranking")
@limiter.limit("30/minute")
async def get_ranking(
    request: Request,
    guild_id: int = Query(...),
    period: str = Query("week"),
    order: str = Query("desc", description="desc=nhiều nhất | asc=ít nhất"),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """Danh sách xếp hạng đầy đủ với phân trang"""
    await require_guild_role(guild_id, "DUTY_MEMBER", current_user, session)

    tz_result = await session.execute(
        select(GuildConfig.timezone).where(GuildConfig.guild_id == guild_id)
    )
    guild_tz = tz_result.scalar_one_or_none() or "Asia/Ho_Chi_Minh"

    if date_from and date_to:
        start, end = get_custom_range(date_from, date_to, guild_tz)
    else:
        start, end = get_period_range(period, tz_str=guild_tz)

    direction = func.sum(DutyLog.duration_minutes).desc() if order == "desc" else func.sum(DutyLog.duration_minutes).asc()

    offset = (page - 1) * page_size
    result = await session.execute(
        select(
            DutyLog.user_id,
            DutyLog.username,
            func.sum(DutyLog.duration_minutes).label("total_minutes"),
            func.count(DutyLog.id).label("sessions"),
        )
        .where(DutyLog.guild_id == guild_id)
        .where(DutyLog.started_at >= start)
        .where(DutyLog.started_at <= end)
        .group_by(DutyLog.user_id, DutyLog.username)
        .order_by(direction)
        .offset(offset)
        .limit(page_size)
    )

    return {
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "rank": offset + i + 1,
                "user_id": r.user_id,
                "username": r.username,
                "total_minutes": r.total_minutes,
                "total_hhmm": minutes_to_hhmm(r.total_minutes),
                "sessions": r.sessions,
            }
            for i, r in enumerate(result.all())
        ],
    }


@router.get("/chart")
@limiter.limit("20/minute")
async def get_chart_data(
    request: Request,
    guild_id: int = Query(...),
    period: str = Query("week"),
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """
    Dữ liệu biểu đồ: tổng phút mỗi ngày trong khoảng thời gian
    Frontend dùng để vẽ bar/line chart
    """
    await require_guild_role(guild_id, "DUTY_MEMBER", current_user, session)

    tz_result = await session.execute(
        select(GuildConfig.timezone).where(GuildConfig.guild_id == guild_id)
    )
    guild_tz = tz_result.scalar_one_or_none() or "Asia/Ho_Chi_Minh"
    start, end = get_period_range(period, tz_str=guild_tz)

    # Group by ngày (cast về date)
    from sqlalchemy import cast, Date
    result = await session.execute(
        select(
            cast(DutyLog.started_at, Date).label("day"),
            func.sum(DutyLog.duration_minutes).label("total_minutes"),
            func.count(DutyLog.id).label("sessions"),
        )
        .where(DutyLog.guild_id == guild_id)
        .where(DutyLog.started_at >= start)
        .where(DutyLog.started_at <= end)
        .group_by(cast(DutyLog.started_at, Date))
        .order_by(cast(DutyLog.started_at, Date))
    )

    # Lưu kết quả vào list trước — cursor chỉ đọc được 1 lần
    rows = result.all()
    return {
        "labels": [str(r.day) for r in rows],
        "data": [r.total_minutes for r in rows],
    }


@router.get("/logs")
@limiter.limit("30/minute")
async def list_logs(
    request: Request,
    guild_id: int = Query(...),
    period: str = Query("all"),
    user_id: int | None = Query(None, description="Filter theo Discord user ID"),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """
    Danh sách từng entry log (có ID).
    - DUTY_MEMBER: CHỈ xem log của chính mình (user_id bị force = sub trong JWT)
    - DUTY_MOD/ADMIN: xem tất cả, có thể filter theo user_id
    Chỉ MOD+ mới xóa được (xem endpoint DELETE).
    """
    await require_guild_role(guild_id, "DUTY_MEMBER", current_user, session)

    # Xác định user có phải MOD+ không để quyết định scope
    current_uid = int(current_user["sub"])
    cfg_row = await session.execute(
        select(GuildConfig).where(GuildConfig.guild_id == guild_id)
    )
    cfg = cfg_row.scalar_one_or_none()
    user_role_ids = set(await fetch_member_role_ids(guild_id, current_uid))
    is_mod_or_admin = False
    if cfg:
        for r in ("DUTY_MOD", "DUTY_ADMIN"):
            rid = cfg.role_map.get(r)
            if rid and int(rid) in user_role_ids:
                is_mod_or_admin = True
                break

    # MEMBER: force filter theo user_id của chính họ, bỏ qua tham số input
    if not is_mod_or_admin:
        user_id = current_uid

    tz_result = await session.execute(
        select(GuildConfig.timezone).where(GuildConfig.guild_id == guild_id)
    )
    guild_tz = tz_result.scalar_one_or_none() or "Asia/Ho_Chi_Minh"

    if date_from and date_to:
        start, end = get_custom_range(date_from, date_to, guild_tz)
    else:
        start, end = get_period_range(period, tz_str=guild_tz)

    base_q = (
        select(DutyLog)
        .where(DutyLog.guild_id == guild_id)
        .where(DutyLog.started_at >= start)
        .where(DutyLog.started_at <= end)
    )
    count_q = (
        select(func.count(DutyLog.id))
        .where(DutyLog.guild_id == guild_id)
        .where(DutyLog.started_at >= start)
        .where(DutyLog.started_at <= end)
    )
    if user_id is not None:
        base_q = base_q.where(DutyLog.user_id == user_id)
        count_q = count_q.where(DutyLog.user_id == user_id)

    total = (await session.execute(count_q)).scalar() or 0

    offset = (page - 1) * page_size
    rows = await session.execute(
        base_q.order_by(DutyLog.started_at.desc()).offset(offset).limit(page_size)
    )
    logs = rows.scalars().all()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "id": log.id,
                "user_id": log.user_id,
                "username": log.username,
                "started_at": log.started_at.isoformat() if log.started_at else None,
                "ended_at": log.ended_at.isoformat() if log.ended_at else None,
                "duration_minutes": log.duration_minutes,
                "duration_hhmm": minutes_to_hhmm(log.duration_minutes),
                "source": log.source,
                "submitted_by": log.submitted_by,
                "created_at": log.created_at.isoformat() if log.created_at else None,
            }
            for log in logs
        ],
    }


@router.delete("/logs/{log_id}")
@limiter.limit("30/minute")
async def delete_log(
    request: Request,
    log_id: int = Path(..., gt=0),
    guild_id: int = Query(...),
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """
    Xóa 1 duty log. Quyền: CHỈ DUTY_ADMIN (không có ngoại lệ — kể cả MOD và chủ log).
    Ghi audit log với chi tiết entry bị xóa.
    """
    user_id = int(current_user["sub"])

    # Quyền ADMIN check TRƯỚC khi query — fail fast
    await require_guild_role(guild_id, "DUTY_ADMIN", current_user, session)

    # Lấy log cần xóa, đảm bảo thuộc đúng guild
    row = await session.execute(
        select(DutyLog).where(DutyLog.id == log_id).where(DutyLog.guild_id == guild_id)
    )
    log = row.scalar_one_or_none()
    if log is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy log với ID này trong guild")

    # Snapshot trước khi xóa để ghi audit
    snapshot = {
        "log_id": log.id,
        "for_user_id": log.user_id,
        "for_username": log.username,
        "started_at": log.started_at.isoformat() if log.started_at else None,
        "ended_at": log.ended_at.isoformat() if log.ended_at else None,
        "duration_minutes": log.duration_minutes,
        "source": log.source,
    }

    # Xóa
    await session.execute(delete(DutyLog).where(DutyLog.id == log_id))

    # Audit log — username người thực hiện lấy từ JWT (sub) — không lưu trong JWT, ta dùng "web_user"
    session.add(AuditLog(
        guild_id=guild_id,
        user_id=user_id,
        username=current_user.get("username", f"user_{user_id}"),
        action=AuditAction.LOG_DELETED,
        detail=snapshot,
        ip_address=request.client.host if request.client else None,
        created_at=utcnow(),
    ))
    await session.commit()

    return {"success": True, "deleted_id": log_id}
