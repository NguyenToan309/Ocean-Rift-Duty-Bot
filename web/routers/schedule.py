"""
schedule.py — Web API cho lịch trực + báo cáo tuân thủ + CRUD.
Endpoints:
  GET    /api/schedule/my             — lịch của tôi
  GET    /api/schedule/all            — tất cả lịch trong guild (mod+)
  GET    /api/schedule/grid           — view "theo người" (group by user) (member xem all theo Q3)
  GET    /api/schedule/calendar       — view calendar 1 tuần
  GET    /api/schedule/compliance     — báo cáo compliance chi tiết
  GET    /api/schedule/missed         — danh sách ngày bỏ ca + xin nghỉ
  PUT    /api/schedule/{id}           — owner sửa lịch
  DELETE /api/schedule/{id}           — owner hoặc mod+ xoá
"""
from __future__ import annotations
import logging
from datetime import date, datetime, time, timedelta, timezone
from collections import defaultdict

from fastapi import APIRouter, Depends, Query, Path, Request, HTTPException, Body
from sqlalchemy import select, delete, func
from sqlalchemy.ext.asyncio import AsyncSession

from models.base import get_db
from models.schedule import MemberSchedule, WEEKDAY_LABELS, WEEKDAY_SHORT
from models.guild import GuildConfig
from models.duty_log import DutyLog
from models.leave import LeaveRequest, LeaveRequestStatus
from models.audit_log import AuditLog, AuditAction
from web.middleware.auth_guard import (
    require_auth, require_guild_role, fetch_member_role_ids,
)
from web.middleware.rate_limit import limiter
from bot.utils.time_utils import get_period_range, get_custom_range, utcnow
from bot.utils.schedule_engine import (
    compute_compliance, list_occurrences_in_range,
    schedule_occurrence_to_utc, is_user_on_leave,
    STATUS_ON_TIME, STATUS_LATE, STATUS_MISSED, STATUS_OFF_SCHEDULE, STATUS_ON_LEAVE,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/schedule", tags=["schedule"])


def _serialize_schedule(s: MemberSchedule) -> dict:
    return {
        "id": s.id,
        "user_id": str(s.user_id),
        "weekday": s.weekday,
        "weekday_label": WEEKDAY_LABELS[s.weekday],
        "weekday_short": WEEKDAY_SHORT[s.weekday],
        "start_time": s.start_time.strftime("%H:%M"),
        "end_time": s.end_time.strftime("%H:%M"),
        "crosses_midnight": s.crosses_midnight,
        "custom_remind_offsets": s.custom_remind_offsets,
        "is_active": s.is_active,
    }


# ─── /my ──────────────────────────────────────────────────────────────────────

@router.get("/my")
@limiter.limit("30/minute")
async def get_my_schedule(
    request: Request,
    guild_id: int = Query(...),
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """Lịch trực của tôi trong guild"""
    await require_guild_role(guild_id, "DUTY_MEMBER", current_user, session)
    user_id = int(current_user["sub"])

    rows = await session.execute(
        select(MemberSchedule)
        .where(MemberSchedule.guild_id == guild_id)
        .where(MemberSchedule.user_id == user_id)
        .where(MemberSchedule.is_active == True)  # noqa: E712
        .order_by(MemberSchedule.weekday, MemberSchedule.start_time)
    )
    return {"items": [_serialize_schedule(s) for s in rows.scalars().all()]}


# ─── /all (mod+) ──────────────────────────────────────────────────────────────

@router.get("/all")
@limiter.limit("20/minute")
async def get_all_schedules(
    request: Request,
    guild_id: int = Query(...),
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    await require_guild_role(guild_id, "DUTY_MOD", current_user, session)
    rows = await session.execute(
        select(MemberSchedule)
        .where(MemberSchedule.guild_id == guild_id)
        .where(MemberSchedule.is_active == True)  # noqa: E712
        .order_by(MemberSchedule.weekday, MemberSchedule.start_time)
    )
    return {"items": [_serialize_schedule(s) for s in rows.scalars().all()]}


# ─── /grid: view "theo người" group by user ──────────────────────────────────

@router.get("/grid")
@limiter.limit("20/minute")
async def get_schedule_grid(
    request: Request,
    guild_id: int = Query(...),
    period: str = Query("week", description="week/month/quarter/all/custom"),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """
    Grid view: 1 row/user, hiển thị:
      - user_id, username, avatar_url (nếu có thông tin từ duty_logs)
      - schedules: list các entry (T2-CN)
      - total_minutes_per_week
      - missed_count: số ca vắng trong khoảng filter
      - on_leave_today: bool
      - leave_dates: list ngày đang trong leave_request approved
    Member chỉ thấy Discord ID khi là Mod+ (Q5=c).
    """
    await require_guild_role(guild_id, "DUTY_MEMBER", current_user, session)
    current_uid = int(current_user["sub"])

    # Check is_mod để quyết định show Discord ID
    cfg_row = await session.execute(select(GuildConfig).where(GuildConfig.guild_id == guild_id))
    cfg = cfg_row.scalar_one_or_none()
    raw_role_ids = await fetch_member_role_ids(guild_id, current_uid)
    user_role_ids = set(raw_role_ids) if raw_role_ids is not None else set()
    is_mod = False
    if cfg:
        for r in ("DUTY_MOD", "DUTY_ADMIN"):
            rid = cfg.role_map.get(r)
            if rid and int(rid) in user_role_ids:
                is_mod = True
                break

    tz = (cfg.timezone if cfg else "Asia/Ho_Chi_Minh") or "Asia/Ho_Chi_Minh"

    # Resolve range cho missed/leave count
    try:
        if date_from and date_to:
            range_start, range_end = get_custom_range(date_from, date_to, tz)
        else:
            range_start, range_end = get_period_range(period, tz_str=tz)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Lấy compliance entries cho khoảng → đếm missed per user
    entries = await compute_compliance(session, guild_id, None, range_start, range_end, tz)

    missed_per_user: dict[int, int] = defaultdict(int)
    on_leave_today_users: set[int] = set()
    leave_dates_per_user: dict[int, set[date]] = defaultdict(set)
    today_local = utcnow().astimezone(__import__("pytz").timezone(tz)).date()
    for e in entries:
        if e.status == STATUS_MISSED:
            missed_per_user[e.user_id] += 1
        if e.status == STATUS_ON_LEAVE:
            leave_dates_per_user[e.user_id].add(e.occurrence_date)
            if e.occurrence_date == today_local:
                on_leave_today_users.add(e.user_id)

    # Lấy schedules trong guild
    rows = await session.execute(
        select(MemberSchedule)
        .where(MemberSchedule.guild_id == guild_id)
        .where(MemberSchedule.is_active == True)  # noqa: E712
        .order_by(MemberSchedule.user_id, MemberSchedule.weekday, MemberSchedule.start_time)
    )
    schedules = rows.scalars().all()

    # Lấy username gần nhất từ duty_logs
    name_rows = await session.execute(
        select(DutyLog.user_id, DutyLog.username)
        .where(DutyLog.guild_id == guild_id)
        .order_by(DutyLog.user_id, DutyLog.id.desc())
    )
    name_cache: dict[int, str] = {}
    for uid, uname in name_rows.all():
        if uid not in name_cache:
            name_cache[uid] = uname

    # Group schedules by user
    by_user: dict[int, list[MemberSchedule]] = defaultdict(list)
    for s in schedules:
        by_user[s.user_id].append(s)

    items = []
    for uid, scheds in by_user.items():
        total_mins = 0
        for s in scheds:
            if s.crosses_midnight or s.end_time <= s.start_time:
                start_dt = datetime.combine(date.today(), s.start_time)
                end_dt = datetime.combine(date.today() + timedelta(days=1), s.end_time)
            else:
                start_dt = datetime.combine(date.today(), s.start_time)
                end_dt = datetime.combine(date.today(), s.end_time)
            total_mins += int((end_dt - start_dt).total_seconds() // 60)

        items.append({
            "user_id": str(uid),    # luôn trả; permission enforce ở endpoint con (/missed, /update, …)
            "username": name_cache.get(uid, f"User#{uid}"),
            "schedules": [_serialize_schedule(s) for s in scheds],
            "total_minutes_per_week": total_mins,
            "missed_count": missed_per_user.get(uid, 0),
            "on_leave_today": uid in on_leave_today_users,
            "leave_dates": sorted(d.isoformat() for d in leave_dates_per_user.get(uid, set())),
        })

    # Sort theo username asc
    items.sort(key=lambda x: x["username"].lower())

    return {
        "is_mod_view": is_mod,
        "period": period,
        "range": {"from": range_start.isoformat(), "to": range_end.isoformat()},
        "items": items,
    }


# ─── /calendar: view tuần ─────────────────────────────────────────────────────

@router.get("/calendar")
@limiter.limit("20/minute")
async def get_schedule_calendar(
    request: Request,
    guild_id: int = Query(...),
    week_offset: int = Query(0, description="0=tuần này, 1=tuần sau, -1=tuần trước"),
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """
    Calendar view: trả 7 ngày (T2-CN), mỗi ngày list schedule đang chạy hôm đó.
    """
    await require_guild_role(guild_id, "DUTY_MEMBER", current_user, session)
    current_uid = int(current_user["sub"])

    cfg_row = await session.execute(select(GuildConfig).where(GuildConfig.guild_id == guild_id))
    cfg = cfg_row.scalar_one_or_none()
    raw_role_ids = await fetch_member_role_ids(guild_id, current_uid)
    user_role_ids = set(raw_role_ids) if raw_role_ids is not None else set()
    is_mod = bool(cfg) and any(
        cfg.role_map.get(r) and int(cfg.role_map[r]) in user_role_ids
        for r in ("DUTY_MOD", "DUTY_ADMIN")
    )

    tz = (cfg.timezone if cfg else "Asia/Ho_Chi_Minh") or "Asia/Ho_Chi_Minh"

    # Tính tuần này (T2 → CN) trong timezone guild
    import pytz
    tz_obj = pytz.timezone(tz)
    now_local = utcnow().astimezone(tz_obj).date()
    monday = now_local - timedelta(days=now_local.weekday()) + timedelta(weeks=week_offset)

    rows = await session.execute(
        select(MemberSchedule)
        .where(MemberSchedule.guild_id == guild_id)
        .where(MemberSchedule.is_active == True)  # noqa: E712
        .order_by(MemberSchedule.weekday, MemberSchedule.start_time)
    )
    schedules = rows.scalars().all()

    # Tên user
    name_rows = await session.execute(
        select(DutyLog.user_id, DutyLog.username)
        .where(DutyLog.guild_id == guild_id)
        .order_by(DutyLog.user_id, DutyLog.id.desc())
    )
    name_cache: dict[int, str] = {}
    for uid, uname in name_rows.all():
        if uid not in name_cache:
            name_cache[uid] = uname

    # Group theo weekday
    days = []
    for offset in range(7):
        d = monday + timedelta(days=offset)
        wd = d.weekday()
        day_scheds = [s for s in schedules if s.weekday == wd]
        items_for_day = []
        for s in day_scheds:
            on_leave = await is_user_on_leave(session, guild_id, s.user_id, d)
            items_for_day.append({
                "schedule_id": s.id,
                "user_id": str(s.user_id),  # luôn trả Discord ID
                "username": name_cache.get(s.user_id, f"User#{s.user_id}"),
                "start_time": s.start_time.strftime("%H:%M"),
                "end_time": s.end_time.strftime("%H:%M"),
                "crosses_midnight": s.crosses_midnight,
                "on_leave": on_leave,
            })
        days.append({
            "date": d.isoformat(),
            "weekday": wd,
            "weekday_label": WEEKDAY_LABELS[wd],
            "weekday_short": WEEKDAY_SHORT[wd],
            "is_today": d == now_local,
            "schedules": items_for_day,
        })

    return {
        "week_offset": week_offset,
        "monday": monday.isoformat(),
        "is_mod_view": is_mod,
        "days": days,
    }


# ─── /missed: ngày bỏ ca + xin nghỉ của 1 user ──────────────────────────────

@router.get("/missed")
@limiter.limit("20/minute")
async def get_missed_and_leaves(
    request: Request,
    guild_id: int = Query(...),
    user_id: int | None = Query(None, description="Mod+ mới được nhập user khác"),
    period: str = Query("month"),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """
    Trả về danh sách:
      - missed_dates: ngày user có lịch nhưng KHÔNG có log duty (kể cả không nghỉ)
      - leave_dates: ngày được duyệt nghỉ phép
    """
    current_uid = int(current_user["sub"])
    if user_id is None or user_id == current_uid:
        await require_guild_role(guild_id, "DUTY_MEMBER", current_user, session)
        target_uid = current_uid
    else:
        await require_guild_role(guild_id, "DUTY_MOD", current_user, session)
        target_uid = user_id

    cfg_row = await session.execute(select(GuildConfig).where(GuildConfig.guild_id == guild_id))
    cfg = cfg_row.scalar_one_or_none()
    tz = (cfg.timezone if cfg else "Asia/Ho_Chi_Minh") or "Asia/Ho_Chi_Minh"

    try:
        if date_from and date_to:
            start, end = get_custom_range(date_from, date_to, tz)
        else:
            start, end = get_period_range(period, tz_str=tz)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    entries = await compute_compliance(session, guild_id, target_uid, start, end, tz)
    missed = []
    leaves = []
    for e in entries:
        if e.status == STATUS_MISSED:
            missed.append({
                "date": e.occurrence_date.isoformat(),
                "weekday_short": WEEKDAY_SHORT[e.schedule.weekday] if e.schedule else None,
                "scheduled_start": e.occurrence_start_utc.isoformat(),
                "scheduled_end": e.occurrence_end_utc.isoformat(),
            })
        elif e.status == STATUS_ON_LEAVE:
            leaves.append({
                "date": e.occurrence_date.isoformat(),
            })

    # Lấy luôn list LeaveRequest đã duyệt trong khoảng (chi tiết hơn)
    lr_rows = await session.execute(
        select(LeaveRequest)
        .where(LeaveRequest.guild_id == guild_id)
        .where(LeaveRequest.user_id == target_uid)
        .where(LeaveRequest.status == LeaveRequestStatus.APPROVED)
        .order_by(LeaveRequest.start_date.desc())
    )
    leave_records = []
    for lr in lr_rows.scalars().all():
        leave_records.append({
            "id": lr.id,
            "type": lr.request_type,
            "start_date": lr.start_date.isoformat(),
            "end_date": lr.end_date.isoformat() if lr.end_date else None,
            "reason": lr.reason,
        })

    return {
        "user_id": str(target_uid),
        "missed_dates": missed,
        "on_leave_dates": leaves,
        "leave_records": leave_records,
    }


# ─── /compliance ─────────────────────────────────────────────────────────────

@router.get("/compliance")
@limiter.limit("10/minute")
async def get_compliance_report(
    request: Request,
    guild_id: int = Query(...),
    period: str = Query("week"),
    user_id: int | None = Query(None),
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    current_uid = int(current_user["sub"])
    if user_id is None or user_id == current_uid:
        await require_guild_role(guild_id, "DUTY_MEMBER", current_user, session)
        target_uid = current_uid
    else:
        await require_guild_role(guild_id, "DUTY_MOD", current_user, session)
        target_uid = user_id

    tz_row = await session.execute(
        select(GuildConfig.timezone).where(GuildConfig.guild_id == guild_id)
    )
    tz = tz_row.scalar_one_or_none() or "Asia/Ho_Chi_Minh"

    try:
        start, end = get_period_range(period, tz_str=tz)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    entries = await compute_compliance(session, guild_id, target_uid, start, end, tz)

    counters: dict[str, int] = {}
    for e in entries:
        counters[e.status] = counters.get(e.status, 0) + 1

    countable = sum(
        v for k, v in counters.items() if k in ("on_time", "late", "missed")
    )
    rate = (counters.get(STATUS_ON_TIME, 0) / countable * 100) if countable else 0.0
    in_schedule_total = countable + counters.get("on_leave", 0)

    return {
        "period": period,
        "summary": {
            "rate_on_time": round(rate, 1),
            "counters": counters,
            "total_in_schedule": in_schedule_total,
        },
        "items": [
            {
                "user_id": str(e.user_id),
                "username": e.username,
                "occurrence_date": e.occurrence_date.isoformat(),
                "schedule_id": e.schedule.id if e.schedule else None,
                "weekday_short": WEEKDAY_SHORT[e.schedule.weekday] if e.schedule else None,
                "scheduled_start": e.occurrence_start_utc.isoformat(),
                "scheduled_end": e.occurrence_end_utc.isoformat(),
                "overlap_minutes": e.overlap_minutes,
                "status": e.status,
            }
            for e in entries
        ],
    }


# ─── PUT /api/schedule/{id} — owner sửa ──────────────────────────────────────

@router.put("/{schedule_id}")
@limiter.limit("20/minute")
async def update_schedule(
    request: Request,
    schedule_id: int = Path(..., gt=0),
    guild_id: int = Query(...),
    body: dict = Body(...),
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """
    Member sửa lịch của mình (Q4=d).
    Body: {"start_time": "HH:MM", "end_time": "HH:MM", "weekday": int 0-6}
    """
    user_id = int(current_user["sub"])
    await require_guild_role(guild_id, "DUTY_MEMBER", current_user, session)

    row = await session.execute(
        select(MemberSchedule)
        .where(MemberSchedule.id == schedule_id)
        .where(MemberSchedule.guild_id == guild_id)
    )
    sched = row.scalar_one_or_none()
    if not sched:
        raise HTTPException(status_code=404, detail="Lịch không tồn tại")
    if sched.user_id != user_id:
        # Mod+ không sửa được lịch người khác qua web (chỉ owner sửa)
        # — Mod+ có thể XOÁ qua DELETE endpoint thôi
        raise HTTPException(status_code=403, detail="Chỉ chủ lịch mới sửa được. Mod chỉ có quyền xoá.")

    # Parse body
    try:
        start_str = body.get("start_time")
        end_str = body.get("end_time")
        weekday = body.get("weekday")
        if start_str is not None:
            h, m = start_str.split(":")
            sched.start_time = time(int(h), int(m))
        if end_str is not None:
            h, m = end_str.split(":")
            sched.end_time = time(int(h), int(m))
        if weekday is not None:
            wd = int(weekday)
            if not 0 <= wd <= 6:
                raise ValueError("weekday phải 0-6")
            sched.weekday = wd
    except (ValueError, AttributeError) as e:
        raise HTTPException(status_code=400, detail=f"Sai định dạng: {e}")

    if sched.start_time == sched.end_time:
        raise HTTPException(status_code=400, detail="start_time == end_time không hợp lệ")
    sched.crosses_midnight = sched.end_time <= sched.start_time
    sched.updated_at = utcnow()

    session.add(AuditLog(
        guild_id=guild_id,
        user_id=user_id,
        username=current_user.get("username", f"user_{user_id}"),
        action=AuditAction.SCHEDULE_UPDATED,
        detail={
            "schedule_id": schedule_id,
            "via": "web",
            "weekday": sched.weekday,
            "start": sched.start_time.strftime("%H:%M"),
            "end": sched.end_time.strftime("%H:%M"),
        },
        created_at=utcnow(),
    ))
    await session.commit()

    # Publish realtime event
    from web.realtime import broadcaster
    await broadcaster.publish(guild_id, {
        "type": "schedule_updated",
        "schedule_id": schedule_id,
        "user_id": str(user_id),
    })

    return {"success": True, "schedule": _serialize_schedule(sched)}


# ─── DELETE /api/schedule/{id} — owner hoặc mod xoá ──────────────────────────

@router.delete("/{schedule_id}")
@limiter.limit("20/minute")
async def delete_schedule(
    request: Request,
    schedule_id: int = Path(..., gt=0),
    guild_id: int = Query(...),
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    user_id = int(current_user["sub"])
    await require_guild_role(guild_id, "DUTY_MEMBER", current_user, session)

    row = await session.execute(
        select(MemberSchedule)
        .where(MemberSchedule.id == schedule_id)
        .where(MemberSchedule.guild_id == guild_id)
    )
    sched = row.scalar_one_or_none()
    if not sched:
        raise HTTPException(status_code=404, detail="Lịch không tồn tại")

    is_owner = sched.user_id == user_id
    if not is_owner:
        # Mod+ mới xoá được của người khác
        await require_guild_role(guild_id, "DUTY_MOD", current_user, session)

    snapshot = {
        "schedule_id": sched.id,
        "user_id": str(sched.user_id),
        "weekday": sched.weekday,
        "start": sched.start_time.strftime("%H:%M"),
        "end": sched.end_time.strftime("%H:%M"),
    }
    await session.delete(sched)
    session.add(AuditLog(
        guild_id=guild_id,
        user_id=user_id,
        username=current_user.get("username", f"user_{user_id}"),
        action=AuditAction.SCHEDULE_DELETED,
        detail={**snapshot, "via": "web"},
        created_at=utcnow(),
    ))
    await session.commit()

    from web.realtime import broadcaster
    await broadcaster.publish(guild_id, {
        "type": "schedule_deleted",
        "schedule_id": schedule_id,
        "user_id": snapshot["user_id"],
    })

    return {"success": True, "deleted": snapshot}
