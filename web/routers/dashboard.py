"""
dashboard.py — API trả dữ liệu cho web dashboard
Tất cả endpoint yêu cầu xác thực JWT
"""
import logging
from fastapi import APIRouter, Depends, HTTPException, Query, Path, Body
from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession

from models.base import get_db
from models.duty_log import DutyLog
from models.guild import GuildConfig
from models.audit_log import AuditLog, AuditAction
from models.schedule import MemberSchedule
from models.leave import LeaveRequest, LeaveRequestStatus
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
    """Trả về user info từ JWT — dùng cho frontend hiển thị + check ownership.

    Field `is_bot_owner` cho frontend biết user có quyền vào /admin/* không
    để hiển thị/ẩn link "Admin" trong navigation.
    """
    from web.middleware.auth_guard import is_bot_owner
    return {
        "user_id": str(current_user.get("sub")),
        "username": current_user.get("username", ""),
        "is_bot_owner": is_bot_owner(current_user),
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
        # fetch_member_role_ids trả None khi Discord API lỗi/timeout — KHÔNG được set(None)
        raw_role_ids = await fetch_member_role_ids(cfg.guild_id, user_id)
        if raw_role_ids is None:
            # Discord API tạm thời không phản hồi — bỏ qua guild này thay vì crash
            # User có thể refresh để thử lại sau
            continue
        user_role_ids = set(raw_role_ids)
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

    # Top 5 — dùng shared helper để gộp theo discord_user_id
    from utils.ranking_utils import aggregate_ranking
    top5_rows = await aggregate_ranking(
        session, guild_id=guild_id, start=start, end=end, order="desc", limit=5,
    )
    _top5_uids = {r.user_id for r in top5_rows}

    # Batch resolve Discord avatars cho top5
    from web.utils.discord_resolver import batch_resolve_user_info
    _top5_info = await batch_resolve_user_info(_top5_uids) if _top5_uids else {}

    return {
        "total_sessions": row.total_sessions,
        "total_minutes": row.total_minutes,
        "total_members": row.total_members,
        "total_hhmm": minutes_to_hhmm(row.total_minutes),
        "top5": [
            {
                "user_id": str(r.user_id) if r.user_id else None,
                "username": r.display_name,
                "avatar_url": (_top5_info.get(r.user_id) or {}).get("avatar_url"),
                "total_minutes": r.total_minutes,
                "total_hhmm": minutes_to_hhmm(r.total_minutes),
                "sessions": r.sessions,
            }
            for r in top5_rows
        ],
    }


@router.get("/attendance")
@limiter.limit("20/minute")
async def get_attendance_dashboard(
    request: Request,
    guild_id: int = Query(...),
    period: str = Query("week"),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """
    Dashboard chấm công TOÀN BỘ nhân viên trong guild.
    Trả về 1 row/user với stats đầy đủ:
      - session_count, total_minutes, total_hhmm
      - avg/longest/shortest session
      - first_log_at, last_log_at
      - compliance: rate (%), on_time, late, missed (nếu user có lịch trực)
      - has_schedule: bool
      - last_log_age_days: số ngày từ log gần nhất tới giờ

    Permission Q3=(b):
      - Member: thấy bảng đầy đủ; Discord ID ẩn (server trả None cho non-mod)
      - Mod+: thấy đủ Discord ID
    """
    await require_guild_role(guild_id, "DUTY_MEMBER", current_user, session)
    current_uid = int(current_user["sub"])

    # Detect mod+ để quyết định trả Discord ID
    cfg_row = await session.execute(select(GuildConfig).where(GuildConfig.guild_id == guild_id))
    cfg = cfg_row.scalar_one_or_none()
    raw_role_ids = await fetch_member_role_ids(guild_id, current_uid)
    user_role_ids = set(raw_role_ids) if raw_role_ids is not None else set()
    is_mod = bool(cfg) and any(
        cfg.role_map.get(r) and int(cfg.role_map[r]) in user_role_ids
        for r in ("DUTY_MOD", "DUTY_ADMIN")
    )

    # Resolve range
    tz = (cfg.timezone if cfg else "Asia/Ho_Chi_Minh") or "Asia/Ho_Chi_Minh"
    try:
        if date_from and date_to:
            start, end = get_custom_range(date_from, date_to, tz)
        else:
            start, end = get_period_range(period, tz_str=tz)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Aggregate query: session_count + total + avg + max + min + first + last cho mỗi user
    rows = await session.execute(
        select(
            DutyLog.user_id,
            DutyLog.username,
            func.count(DutyLog.id).label("session_count"),
            func.coalesce(func.sum(DutyLog.duration_minutes), 0).label("total_minutes"),
            func.max(DutyLog.duration_minutes).label("longest"),
            func.min(DutyLog.duration_minutes).label("shortest"),
            func.min(DutyLog.started_at).label("first_log_at"),
            func.max(DutyLog.started_at).label("last_log_at"),
        )
        .where(DutyLog.guild_id == guild_id)
        .where(DutyLog.started_at >= start)
        .where(DutyLog.started_at <= end)
        .group_by(DutyLog.user_id, DutyLog.username)
        .order_by(func.sum(DutyLog.duration_minutes).desc())
    )
    log_data = rows.all()

    # Lấy compliance entries để đếm on_time/late/missed per user
    from bot.utils.schedule_engine import (
        compute_compliance,
        STATUS_ON_TIME, STATUS_LATE, STATUS_MISSED, STATUS_ON_LEAVE,
    )
    compliance_entries = await compute_compliance(session, guild_id, None, start, end, tz)
    compl_per_user: dict[int, dict] = {}
    for e in compliance_entries:
        c = compl_per_user.setdefault(e.user_id, {
            "on_time": 0, "late": 0, "missed": 0, "on_leave": 0, "has_schedule": False,
        })
        if e.schedule:
            c["has_schedule"] = True
        if e.status == STATUS_ON_TIME:
            c["on_time"] += 1
        elif e.status == STATUS_LATE:
            c["late"] += 1
        elif e.status == STATUS_MISSED:
            c["missed"] += 1
        elif e.status == STATUS_ON_LEAVE:
            c["on_leave"] += 1

    # Lấy users có schedule nhưng chưa log (không có trong log_data) — để bao gồm trong attendance
    sched_users = await session.execute(
        select(MemberSchedule.user_id, func.min(MemberSchedule.user_id).label("uid"))
        .where(MemberSchedule.guild_id == guild_id)
        .where(MemberSchedule.is_active == True)  # noqa: E712
        .group_by(MemberSchedule.user_id)
    )
    users_with_schedule = {row.user_id for row in sched_users.all()}

    # Set of users đã trong log_data
    users_with_logs = {row.user_id for row in log_data}

    # Merge: users có log + users có schedule nhưng chưa log
    items: list[dict] = []
    now_utc = utcnow()

    def _make_compl(uid: int) -> dict:
        c = compl_per_user.get(uid, {"on_time": 0, "late": 0, "missed": 0, "on_leave": 0, "has_schedule": False})
        countable = c["on_time"] + c["late"] + c["missed"]
        rate = (c["on_time"] / countable * 100) if countable else None
        return {
            "rate": round(rate, 1) if rate is not None else None,
            "on_time": c["on_time"],
            "late": c["late"],
            "missed": c["missed"],
            "on_leave": c["on_leave"],
        }

    for row in log_data:
        uid = row.user_id
        last_log = row.last_log_at
        days_since = (now_utc - last_log).days if last_log else None
        avg = int(row.total_minutes / row.session_count) if row.session_count else 0

        items.append({
            "user_id": str(uid),  # luôn trả Discord ID — endpoint /daily đã enforce permission riêng
            "username": row.username,
            "session_count": row.session_count,
            "total_minutes": row.total_minutes,
            "total_hhmm": minutes_to_hhmm(row.total_minutes),
            "avg_minutes": avg,
            "longest_minutes": row.longest or 0,
            "shortest_minutes": row.shortest or 0,
            "first_log_at": row.first_log_at.isoformat() if row.first_log_at else None,
            "last_log_at": last_log.isoformat() if last_log else None,
            "last_log_age_days": days_since,
            "has_schedule": uid in users_with_schedule,
            "compliance": _make_compl(uid),
        })

    # Add users có schedule nhưng KHÔNG log trong kỳ → status "vắng hoàn toàn"
    for uid in users_with_schedule - users_with_logs:
        # Username từ duty_logs gần nhất ngoài kỳ
        name_row = await session.execute(
            select(DutyLog.username)
            .where(DutyLog.guild_id == guild_id)
            .where(DutyLog.user_id == uid)
            .order_by(DutyLog.id.desc())
            .limit(1)
        )
        username = name_row.scalar_one_or_none() or f"User#{uid}"

        items.append({
            "user_id": str(uid),  # luôn trả Discord ID — endpoint /daily đã enforce permission riêng
            "username": username,
            "session_count": 0,
            "total_minutes": 0,
            "total_hhmm": "0 phút",
            "avg_minutes": 0,
            "longest_minutes": 0,
            "shortest_minutes": 0,
            "first_log_at": None,
            "last_log_at": None,
            "last_log_age_days": None,
            "has_schedule": True,
            "compliance": _make_compl(uid),
        })

    # Tổng hợp summary toàn server
    total_sessions = sum(it["session_count"] for it in items)
    total_minutes = sum(it["total_minutes"] for it in items)
    active_members = sum(1 for it in items if it["session_count"] > 0)

    # Batch resolve Discord avatars cho mọi user trong attendance
    from web.utils.discord_resolver import batch_resolve_user_info
    _att_uids: set[int] = set()
    for it in items:
        try:
            _att_uids.add(int(it["user_id"]))
        except (TypeError, ValueError):
            pass
    _att_info = await batch_resolve_user_info(_att_uids) if _att_uids else {}
    for it in items:
        try:
            uid_int = int(it["user_id"])
            it["avatar_url"] = (_att_info.get(uid_int) or {}).get("avatar_url")
        except (TypeError, ValueError):
            it["avatar_url"] = None

    return {
        "is_mod_view": is_mod,
        "period": period,
        "range": {"from": start.isoformat(), "to": end.isoformat()},
        "summary": {
            "total_members": len(items),
            "active_members": active_members,
            "total_sessions": total_sessions,
            "total_minutes": total_minutes,
            "total_hhmm": minutes_to_hhmm(total_minutes),
            "avg_minutes_per_member": int(total_minutes / active_members) if active_members else 0,
        },
        "items": items,
    }


@router.get("/attendance/daily")
@limiter.limit("30/minute")
async def get_attendance_daily(
    request: Request,
    guild_id: int = Query(...),
    user_id: int = Query(..., description="Discord user ID xem chi tiết"),
    period: str = Query("week"),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """
    Chi tiết chấm công TỪNG NGÀY của 1 nhân viên trong khoảng kỳ.

    Trả về list day-by-day với:
      - schedules: lịch trực hôm đó (nếu có)
      - logs: danh sách log đã chấm trong ngày
      - leave_record: nếu user xin nghỉ duyệt cho ngày đó
      - status: on_time / late / missed / off_schedule / on_leave / no_schedule
      - total_minutes_worked, scheduled_minutes, compliance_pct

    Permission:
      - Member chỉ xem được của chính mình
      - Mod+ xem được mọi user
    """
    current_uid = int(current_user["sub"])
    if user_id == current_uid:
        await require_guild_role(guild_id, "DUTY_MEMBER", current_user, session)
    else:
        await require_guild_role(guild_id, "DUTY_MOD", current_user, session)

    # Resolve range
    cfg_row = await session.execute(select(GuildConfig).where(GuildConfig.guild_id == guild_id))
    cfg = cfg_row.scalar_one_or_none()
    tz = (cfg.timezone if cfg else "Asia/Ho_Chi_Minh") or "Asia/Ho_Chi_Minh"

    try:
        if date_from and date_to:
            range_start, range_end = get_custom_range(date_from, date_to, tz)
        else:
            range_start, range_end = get_period_range(period, tz_str=tz)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    import pytz
    from datetime import timedelta, datetime as dt
    from bot.utils.schedule_engine import (
        schedule_occurrence_to_utc, is_user_on_leave,
        STATUS_ON_TIME, STATUS_LATE, STATUS_MISSED, STATUS_OFF_SCHEDULE, STATUS_ON_LEAVE,
        COMPLIANCE_MIN_MINUTES,
    )
    tz_obj = pytz.timezone(tz)
    start_local_date = range_start.astimezone(tz_obj).date()
    end_local_date = range_end.astimezone(tz_obj).date()
    today_local = utcnow().astimezone(tz_obj).date()

    # Lấy tất cả schedule của user
    sched_rows = await session.execute(
        select(MemberSchedule)
        .where(MemberSchedule.guild_id == guild_id)
        .where(MemberSchedule.user_id == user_id)
        .where(MemberSchedule.is_active == True)  # noqa: E712
    )
    user_schedules = sched_rows.scalars().all()

    # Lấy tất cả log của user trong khoảng (mở rộng thêm 1 ngày để bắt ca qua đêm)
    log_rows = await session.execute(
        select(DutyLog)
        .where(DutyLog.guild_id == guild_id)
        .where(DutyLog.user_id == user_id)
        .where(DutyLog.started_at < range_end + timedelta(days=1))
        .where(DutyLog.ended_at > range_start - timedelta(days=1))
        .order_by(DutyLog.started_at.asc())
    )
    user_logs = log_rows.scalars().all()

    # Lấy LeaveRequest approved trong khoảng
    leave_rows = await session.execute(
        select(LeaveRequest)
        .where(LeaveRequest.guild_id == guild_id)
        .where(LeaveRequest.user_id == user_id)
        .where(LeaveRequest.status == LeaveRequestStatus.APPROVED)
    )
    user_leaves = leave_rows.scalars().all()

    # Username (lấy từ log gần nhất, ngoài kỳ cũng được)
    name_row = await session.execute(
        select(DutyLog.username)
        .where(DutyLog.guild_id == guild_id)
        .where(DutyLog.user_id == user_id)
        .order_by(DutyLog.id.desc())
        .limit(1)
    )
    username = name_row.scalar_one_or_none() or f"User#{user_id}"

    weekday_labels = ["Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7", "Chủ nhật"]
    weekday_short = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"]

    days_count = (end_local_date - start_local_date).days + 1
    days_out: list[dict] = []

    # Aggregate counts cho summary
    sum_counters = {
        "on_time": 0, "late": 0, "missed": 0,
        "off_schedule": 0, "on_leave": 0, "no_schedule": 0,
    }
    total_worked_minutes = 0
    total_scheduled_minutes = 0

    for offset in range(days_count):
        d = start_local_date + timedelta(days=offset)
        wd = d.weekday()

        # Find schedules cho ngày này
        day_schedules = [s for s in user_schedules if s.weekday == wd]

        # Find logs có overlap với ngày này (UTC range của ngày local)
        day_start_utc = tz_obj.localize(dt.combine(d, dt.min.time())).astimezone(pytz.utc)
        day_end_utc = day_start_utc + timedelta(days=1)
        day_logs = [
            log for log in user_logs
            if log.started_at < day_end_utc and log.ended_at > day_start_utc
        ]

        # Find leave covers ngày này
        leave_record = None
        for lr in user_leaves:
            if lr.start_date <= d and (lr.end_date is None or lr.end_date >= d):
                leave_record = lr
                break

        # Tính minutes worked trong ngày = sum overlap của logs với day window
        worked_minutes = 0
        for log in day_logs:
            ovl_start = max(log.started_at, day_start_utc)
            ovl_end = min(log.ended_at, day_end_utc)
            if ovl_end > ovl_start:
                worked_minutes += int((ovl_end - ovl_start).total_seconds() // 60)

        # Tính scheduled minutes của ngày này
        scheduled_minutes = 0
        for s in day_schedules:
            s_start_utc, s_end_utc = schedule_occurrence_to_utc(s, d, tz)
            scheduled_minutes += int((s_end_utc - s_start_utc).total_seconds() // 60)

        # Quyết định status
        if leave_record:
            status = STATUS_ON_LEAVE
        elif not day_schedules:
            status = STATUS_NO_SCHEDULE if not day_logs else STATUS_OFF_SCHEDULE
        else:
            # Có lịch — tính overlap với schedule
            overlap_with_schedule = 0
            for s in day_schedules:
                s_start_utc, s_end_utc = schedule_occurrence_to_utc(s, d, tz)
                for log in day_logs:
                    ovl_start = max(log.started_at, s_start_utc)
                    ovl_end = min(log.ended_at, s_end_utc)
                    if ovl_end > ovl_start:
                        overlap_with_schedule += int((ovl_end - ovl_start).total_seconds() // 60)

            if overlap_with_schedule >= COMPLIANCE_MIN_MINUTES:
                status = STATUS_ON_TIME
            elif overlap_with_schedule > 0:
                status = STATUS_LATE
            else:
                status = STATUS_MISSED

        sum_counters[status] = sum_counters.get(status, 0) + 1
        total_worked_minutes += worked_minutes
        total_scheduled_minutes += scheduled_minutes

        # Compliance pct: worked / scheduled * 100 (capped 100)
        if scheduled_minutes > 0:
            compliance_pct = min(100.0, worked_minutes / scheduled_minutes * 100)
        elif worked_minutes > 0:
            compliance_pct = None    # ngoài lịch
        else:
            compliance_pct = 0.0

        days_out.append({
            "date": d.isoformat(),
            "weekday": wd,
            "weekday_label": weekday_labels[wd],
            "weekday_short": weekday_short[wd],
            "is_today": d == today_local,
            "is_future": d > today_local,
            "schedules": [{
                "id": s.id,
                "start_time": s.start_time.strftime("%H:%M"),
                "end_time": s.end_time.strftime("%H:%M"),
                "crosses_midnight": s.crosses_midnight,
            } for s in day_schedules],
            "logs": [{
                "id": log.id,
                "started_at": log.started_at.isoformat(),
                "ended_at": log.ended_at.isoformat(),
                "duration_minutes": log.duration_minutes,
                "source": log.source,
                "schedule_id": log.schedule_id,
            } for log in day_logs],
            "leave": ({
                "id": leave_record.id,
                "type": leave_record.request_type,
                "start_date": leave_record.start_date.isoformat(),
                "end_date": leave_record.end_date.isoformat() if leave_record.end_date else None,
                "reason": leave_record.reason,
            } if leave_record else None),
            "status": status,
            "worked_minutes": worked_minutes,
            "scheduled_minutes": scheduled_minutes,
            "compliance_pct": round(compliance_pct, 1) if compliance_pct is not None else None,
        })

    return {
        "user_id": str(user_id),
        "username": username,
        "period": period,
        "range": {"from": start_local_date.isoformat(), "to": end_local_date.isoformat()},
        "summary": {
            "counters": sum_counters,
            "total_worked_minutes": total_worked_minutes,
            "total_worked_hhmm": minutes_to_hhmm(total_worked_minutes),
            "total_scheduled_minutes": total_scheduled_minutes,
            "total_scheduled_hhmm": minutes_to_hhmm(total_scheduled_minutes),
            "overall_compliance_pct": (
                round(min(100.0, total_worked_minutes / total_scheduled_minutes * 100), 1)
                if total_scheduled_minutes > 0 else None
            ),
        },
        "days": days_out,
    }


# ─── Constants used by /attendance/daily — không trùng với schedule_engine ──
STATUS_NO_SCHEDULE = "no_schedule"


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

    offset = (page - 1) * page_size

    # Gộp theo discord_user_id qua shared helper.
    # Cùng 1 user có thể có nhiều tên ingame (đổi character/Steam name).
    # Helper trả display_name đã ưu tiên DutyIdentityBinding.current_ingame_name
    # rồi fallback username log gần nhất trong period.
    from utils.ranking_utils import aggregate_ranking
    rank_rows = await aggregate_ranking(
        session, guild_id=guild_id, start=start, end=end,
        order=order, limit=page_size, offset=offset,
    )
    user_ids_in_page = [r.user_id for r in rank_rows]

    # Batch resolve Discord avatars
    from web.utils.discord_resolver import batch_resolve_user_info
    info_map = await batch_resolve_user_info(set(user_ids_in_page)) if user_ids_in_page else {}

    return {
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "rank": offset + i + 1,
                "user_id": str(r.user_id) if r.user_id else None,
                "username": r.display_name,
                "avatar_url": (info_map.get(r.user_id) or {}).get("avatar_url"),
                "total_minutes": r.total_minutes,
                "total_hhmm": minutes_to_hhmm(r.total_minutes),
                "sessions": r.sessions,
            }
            for i, r in enumerate(rank_rows)
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
    raw_role_ids = await fetch_member_role_ids(guild_id, current_uid)
    user_role_ids = set(raw_role_ids) if raw_role_ids is not None else set()
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
    logs = list(rows.scalars().all())

    # Batch resolve avatars cho duty logs
    from web.utils.discord_resolver import batch_resolve_user_info
    _log_uids = {log.user_id for log in logs if log.user_id}
    _log_info = await batch_resolve_user_info(_log_uids) if _log_uids else {}

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "id": log.id,
                "user_id": log.user_id,
                "username": log.username,
                "avatar_url": (_log_info.get(log.user_id) or {}).get("avatar_url"),
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


@router.post("/logs/rebind")
@limiter.limit("10/minute")
async def rebind_user(
    request: Request,
    payload: dict,
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """Đổi current_ingame_name trong binding của 1 user.

    Body: {guild_id, target_user_id, new_ingame_name, note}
    KHÔNG đổi username trong duty_logs cũ — chỉ binding.
    Quyền: DUTY_ADMIN. Phân biệt hoa thường.
    """
    from models.duty_identity_binding import DutyIdentityBinding

    try:
        guild_id = int(payload.get("guild_id") or 0)
        target_user_id = int(payload.get("target_user_id") or 0)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="guild_id và target_user_id phải là số")
    new_name = (payload.get("new_ingame_name") or "").strip() if isinstance(payload.get("new_ingame_name"), str) else ""
    note = (payload.get("note") or "").strip() if isinstance(payload.get("note"), str) else ""

    if guild_id <= 0 or target_user_id <= 0:
        raise HTTPException(status_code=400, detail="guild_id và target_user_id không hợp lệ")
    if not new_name:
        raise HTTPException(status_code=400, detail="new_ingame_name không được rỗng")
    if len(note) < 3:
        raise HTTPException(status_code=400, detail="Lý do tối thiểu 3 ký tự")
    if len(new_name) > 100:
        raise HTTPException(status_code=400, detail="Tên mới quá dài (tối đa 100 ký tự)")

    user_id = int(current_user["sub"])
    username = current_user.get("username", f"user_{user_id}")

    await require_guild_role(guild_id, "DUTY_ADMIN", current_user, session)

    row = await session.execute(
        select(DutyIdentityBinding)
        .where(DutyIdentityBinding.guild_id == guild_id)
        .where(DutyIdentityBinding.discord_user_id == target_user_id)
    )
    binding = row.scalar_one_or_none()
    if binding is None:
        raise HTTPException(
            status_code=404,
            detail=f"User {target_user_id} chưa có binding (chưa từng chấm công).",
        )

    old_name = binding.current_ingame_name
    if old_name == new_name:
        raise HTTPException(status_code=400, detail="Tên mới giống tên hiện tại")

    # Conflict check
    conflict_row = await session.execute(
        select(DutyIdentityBinding)
        .where(DutyIdentityBinding.guild_id == guild_id)
        .where(DutyIdentityBinding.current_ingame_name == new_name)
        .where(DutyIdentityBinding.discord_user_id != target_user_id)
    )
    conflict = conflict_row.scalar_one_or_none()
    if conflict is not None:
        raise HTTPException(
            status_code=409,
            detail=f"Tên '{new_name}' đã thuộc user khác (ID {conflict.discord_user_id})",
        )

    history = list(binding.rebind_history or [])
    history.append({
        "from": old_name,
        "to": new_name,
        "by": str(user_id),
        "by_name": username,
        "at": utcnow().isoformat(),
        "reason": note,
        "via": "web",
    })
    binding.current_ingame_name = new_name
    binding.rebind_count = (binding.rebind_count or 0) + 1
    binding.rebind_history = history

    session.add(AuditLog(
        guild_id=guild_id,
        user_id=user_id,
        username=username,
        action=AuditAction.LOG_REBIND,
        detail={
            "target_user_id": str(target_user_id),
            "original_ingame_name": binding.original_ingame_name,
            "from": old_name,
            "to": new_name,
            "reason": note,
            "via": "web",
        },
        ip_address=request.client.host if request.client else None,
        created_at=utcnow(),
    ))
    await session.commit()

    return {
        "success": True,
        "original_ingame_name": binding.original_ingame_name,
        "old_name": old_name,
        "new_name": new_name,
    }


@router.get("/logs/bindings")
@limiter.limit("30/minute")
async def list_bindings(
    request: Request,
    guild_id: int = Query(...),
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """Liệt kê tất cả binding trong guild (cho UI admin xem/so sánh).

    Trả: list[{discord_user_id, original_ingame_name, current_ingame_name,
    rebind_count, log_count, first_seen_at, last_seen_at, history[]}]
    Quyền: DUTY_MEMBER trở lên (member tự xem được).
    """
    from models.duty_identity_binding import DutyIdentityBinding
    await require_guild_role(guild_id, "DUTY_MEMBER", current_user, session)

    rows = await session.execute(
        select(DutyIdentityBinding)
        .where(DutyIdentityBinding.guild_id == guild_id)
        .order_by(DutyIdentityBinding.last_seen_at.desc())
    )
    items = []
    for b in rows.scalars().all():
        items.append({
            "discord_user_id": str(b.discord_user_id),
            "original_ingame_name": b.original_ingame_name,
            "current_ingame_name": b.current_ingame_name,
            "is_renamed": b.original_ingame_name != b.current_ingame_name,
            "rebind_count": b.rebind_count or 0,
            "log_count": b.log_count or 0,
            "first_seen_at": b.first_seen_at.isoformat() if b.first_seen_at else None,
            "last_seen_at": b.last_seen_at.isoformat() if b.last_seen_at else None,
            "history": list(b.rebind_history or []),
        })
    return {"items": items}


@router.post("/logs/rename")
@limiter.limit("10/minute")
async def rename_logs(
    request: Request,
    payload: dict,
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """Mass-rename log: đổi username tất cả log của 1 tên cũ → tên mới trong
    1 guild. Use case: user đổi tên character → đồng bộ lại log cũ.

    Body: {guild_id: int, old_name: str, new_name: str, note: str}

    Quyền: DUTY_ADMIN. Trả {affected_logs, affected_user_ids[]}.

    Chặn conflict: nếu tên mới đã thuộc về user_id khác (theo username lock)
    → 409 Conflict; admin phải xử lý owner cũ trước khi rename.
    """
    guild_id_raw = payload.get("guild_id")
    old_name_raw = payload.get("old_name")
    new_name_raw = payload.get("new_name")
    note_raw = payload.get("note")

    if not isinstance(guild_id_raw, int) and not (isinstance(guild_id_raw, str) and guild_id_raw.isdigit()):
        raise HTTPException(status_code=400, detail="guild_id không hợp lệ")
    guild_id = int(guild_id_raw)

    old_name = (old_name_raw or "").strip() if isinstance(old_name_raw, str) else ""
    new_name = (new_name_raw or "").strip() if isinstance(new_name_raw, str) else ""
    note = (note_raw or "").strip() if isinstance(note_raw, str) else ""

    if not old_name or not new_name:
        raise HTTPException(status_code=400, detail="old_name và new_name không được rỗng")
    if len(note) < 3:
        raise HTTPException(status_code=400, detail="Phải ghi lý do tối thiểu 3 ký tự (note)")
    if old_name.lower() == new_name.lower():
        raise HTTPException(status_code=400, detail="Tên cũ và tên mới giống nhau (case-insensitive)")
    if len(new_name) > 100:
        raise HTTPException(status_code=400, detail="Tên mới quá dài (tối đa 100 ký tự)")

    user_id = int(current_user["sub"])
    username = current_user.get("username", f"user_{user_id}")

    await require_guild_role(guild_id, "DUTY_ADMIN", current_user, session)

    # Tìm log khớp tên cũ
    matched = await session.execute(
        select(DutyLog)
        .where(DutyLog.guild_id == guild_id)
        .where(func.lower(func.trim(DutyLog.username)) == old_name.lower())
    )
    logs = list(matched.scalars().all())
    if not logs:
        raise HTTPException(
            status_code=404,
            detail=f"Không có log nào của '{old_name}' trong guild này.",
        )

    # Verify tên mới chưa thuộc user_id khác
    current_owner_id = logs[0].user_id
    new_owner_row = await session.execute(
        select(DutyLog.user_id)
        .where(DutyLog.guild_id == guild_id)
        .where(func.lower(func.trim(DutyLog.username)) == new_name.lower())
        .limit(1)
    )
    new_owner_id = new_owner_row.scalar_one_or_none()
    if new_owner_id is not None and new_owner_id != current_owner_id:
        raise HTTPException(
            status_code=409,
            detail=f"Tên mới '{new_name}' đã thuộc user khác (ID {new_owner_id}). "
                   "Xử lý owner cũ trước khi rename.",
        )

    affected_user_ids = sorted({l.user_id for l in logs})
    affected_count = len(logs)
    for log in logs:
        log.username = new_name

    session.add(AuditLog(
        guild_id=guild_id,
        user_id=user_id,
        username=username,
        action=AuditAction.LOG_RENAMED,
        detail={
            "old_name": old_name,
            "new_name": new_name,
            "affected_logs": affected_count,
            "affected_user_ids": [str(u) for u in affected_user_ids],
            "note": note,
            "via": "web",
        },
        ip_address=request.client.host if request.client else None,
        created_at=utcnow(),
    ))
    await session.commit()

    return {
        "success": True,
        "affected_logs": affected_count,
        "affected_user_ids": [str(u) for u in affected_user_ids],
    }


@router.delete("/logs/{log_id}")
@limiter.limit("30/minute")
async def delete_log(
    request: Request,
    log_id: int = Path(..., gt=0),
    guild_id: int = Query(...),
    note: str = Query(..., min_length=3, description="Lý do xoá (BẮT BUỘC, ≥3 ký tự)"),
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """
    Xóa 1 duty log. Quyền: CHỈ DUTY_ADMIN (không có ngoại lệ — kể cả MOD và chủ log).
    Audit policy nghiêm ngặt: MỌI lệnh xoá đều phải kèm lý do.
    """
    user_id = int(current_user["sub"])
    note_clean = (note or "").strip()
    if len(note_clean) < 3:
        raise HTTPException(
            status_code=400,
            detail="Xoá log phải ghi LÝ DO (tối thiểu 3 ký tự, query param 'note').",
        )

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
        "for_user": str(log.user_id),
        "for_username": log.username,
        "started_at": log.started_at.isoformat() if log.started_at else None,
        "ended_at": log.ended_at.isoformat() if log.ended_at else None,
        "duration_minutes": log.duration_minutes,
        "source": log.source,
    }

    # Xóa — verify rowcount để bắt race condition (log bị xoá bởi tiến trình
    # khác giữa lúc query select ở trên và delete ở đây). Tránh ghi audit log
    # giả "đã xoá X" khi thực ra delete no-op.
    delete_result = await session.execute(delete(DutyLog).where(DutyLog.id == log_id))
    if delete_result.rowcount == 0:
        raise HTTPException(
            status_code=404,
            detail="Log đã bị xoá bởi tiến trình khác giữa lúc kiểm tra và xoá. Vui lòng tải lại trang.",
        )

    session.add(AuditLog(
        guild_id=guild_id,
        user_id=user_id,
        username=current_user.get("username", f"user_{user_id}"),
        action=AuditAction.LOG_DELETED,
        detail={**snapshot, "note": note_clean, "via": "web"},
        ip_address=request.client.host if request.client else None,
        created_at=utcnow(),
    ))
    await session.commit()

    return {"success": True, "deleted_id": log_id}


# ─── Notification Settings ────────────────────────────────────────────────────

DEFAULT_NOTIFY = {
    "remind_register_shift": True,
    "remind_before_shift": True,
    "alert_late": True,
    "alert_burnout": True,
    "daily_digest": False,
}


@router.get("/notification-settings")
@limiter.limit("30/minute")
async def get_notification_settings(
    request: Request,
    guild_id: int = Query(...),
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """Lấy cấu hình bật/tắt các loại nhắc nhở. Mod+ xem được."""
    await require_guild_role(guild_id, "DUTY_MOD", current_user, session)
    row = await session.execute(select(GuildConfig).where(GuildConfig.guild_id == guild_id))
    config = row.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="Guild chưa setup")
    settings_obj = {**DEFAULT_NOTIFY, **(config.notification_settings or {})}
    return {"notification_settings": settings_obj}


@router.put("/notification-settings")
@limiter.limit("10/minute")
async def update_notification_settings(
    request: Request,
    guild_id: int = Query(...),
    body: dict = Body(...),
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """
    Cập nhật cấu hình thông báo (Admin). Body:
      {"settings": {...}, "note": "Lý do (≥3 chars)"}
    """
    await require_guild_role(guild_id, "DUTY_ADMIN", current_user, session)
    note = (body.get("note") or "").strip()
    if len(note) < 3:
        raise HTTPException(status_code=400, detail="Bắt buộc lý do thay đổi (≥3 ký tự).")

    new_settings = body.get("settings") or {}
    if not isinstance(new_settings, dict):
        raise HTTPException(status_code=400, detail="Field 'settings' phải là object.")

    # Validate keys: chỉ accept các key trong DEFAULT_NOTIFY
    clean: dict[str, bool] = {}
    for k, v in new_settings.items():
        if k in DEFAULT_NOTIFY:
            clean[k] = bool(v)

    row = await session.execute(select(GuildConfig).where(GuildConfig.guild_id == guild_id))
    config = row.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="Guild chưa setup")

    before = {**DEFAULT_NOTIFY, **(config.notification_settings or {})}
    merged = {**before, **clean}
    config.notification_settings = merged

    session.add(AuditLog(
        guild_id=guild_id,
        user_id=int(current_user["sub"]),
        username=current_user.get("username", f"user_{current_user['sub']}"),
        action="NOTIFICATION_SETTINGS_CHANGED",
        detail={
            "before": before,
            "after": merged,
            "note": note,
            "via": "web",
        },
        created_at=utcnow(),
    ))
    await session.commit()

    return {"success": True, "notification_settings": merged}


# ─── Batch Resolve Discord User Info ──────────────────────────────────────────

@router.post("/resolve-users")
@limiter.limit("60/minute")
async def resolve_users(
    request: Request,
    body: dict = Body(...),
    current_user: dict = Depends(require_auth),
):
    """
    Batch resolve Discord user info (avatar + username) cho nhiều user_id.

    Body: {"user_ids": ["1119880453671899196", "833685979147534416", ...]}
    Return: {"results": {"id1": {"username", "global_name", "avatar_url"}, ...}}

    Backend cache 10 phút (xem discord_resolver.py). Frontend dùng để hiển thị
    avatar thật cho user_id không nằm trong Staff list (VD: từ duty log, ranking).
    """
    user_ids_raw = body.get("user_ids") or []
    if not isinstance(user_ids_raw, list):
        raise HTTPException(status_code=400, detail="user_ids phải là list of strings.")
    # Limit tối đa 100 IDs/request để tránh abuse
    if len(user_ids_raw) > 100:
        raise HTTPException(status_code=400, detail="Tối đa 100 user_id/request.")

    valid_ids: set[int] = set()
    for x in user_ids_raw:
        try:
            n = int(x)
            if 10**14 <= n < 10**20:    # Discord snowflake range
                valid_ids.add(n)
        except (TypeError, ValueError):
            continue

    if not valid_ids:
        return {"results": {}}

    from web.utils.discord_resolver import batch_resolve_user_info
    info_map = await batch_resolve_user_info(valid_ids)

    return {
        "results": {str(uid): info for uid, info in info_map.items() if info},
    }
