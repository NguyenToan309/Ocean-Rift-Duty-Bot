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


# ─── POST / (Admin tạo ca trực từ web) ────────────────────────────────────────

@router.post("")
@limiter.limit("20/minute")
async def create_schedule(
    request: Request,
    guild_id: int = Query(...),
    body: dict = Body(...),
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """
    Admin tạo ca trực mới cho 1 user. Body:
      {
        "user_id": "1119880453671899196",
        "weekday": 0,         # 0=T2 .. 6=CN
        "start_time": "08:00",
        "end_time": "12:00",
        "note": "Tạo ca trực mới"   # bắt buộc ≥3 chars
      }
    """
    await require_guild_role(guild_id, "DUTY_ADMIN", current_user, session)

    note = (body.get("note") or "").strip()
    if len(note) < 3:
        raise HTTPException(status_code=400, detail="Bắt buộc lý do tạo ca (≥3 ký tự).")

    try:
        user_id = int(body.get("user_id"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="user_id phải là số nguyên (Discord ID).")

    weekday = body.get("weekday")
    if not isinstance(weekday, int) or not 0 <= weekday <= 6:
        raise HTTPException(status_code=400, detail="weekday phải là 0-6 (0=Thứ 2 ... 6=Chủ nhật).")

    try:
        sh, sm = map(int, str(body.get("start_time", "")).split(":"))
        eh, em = map(int, str(body.get("end_time", "")).split(":"))
        start_t = time(sh, sm)
        end_t = time(eh, em)
    except Exception:
        raise HTTPException(status_code=400, detail="start_time/end_time phải dạng HH:MM (24h).")

    crosses_midnight = start_t >= end_t

    new_sched = MemberSchedule(
        guild_id=guild_id,
        user_id=user_id,
        weekday=weekday,
        start_time=start_t,
        end_time=end_t,
        crosses_midnight=crosses_midnight,
        is_active=True,
    )
    session.add(new_sched)
    await session.flush()

    session.add(AuditLog(
        guild_id=guild_id,
        user_id=int(current_user["sub"]),
        username=current_user.get("username", f"user_{current_user['sub']}"),
        action=AuditAction.SCHEDULE_CREATED,
        detail={
            "schedule_id": new_sched.id,
            "for_user": str(user_id),
            "weekday": weekday,
            "start": start_t.strftime("%H:%M"),
            "end": end_t.strftime("%H:%M"),
            "note": note,
            "via": "web",
        },
        created_at=utcnow(),
    ))
    await session.commit()
    await session.refresh(new_sched)

    # Realtime broadcast
    try:
        from web.realtime import broadcaster
        await broadcaster.publish(guild_id, {"type": "schedule_updated"})
    except Exception:
        pass

    return {"success": True, "schedule": _serialize_schedule(new_sched)}


# ─── POST /bulk-replace (Admin set toàn bộ lịch của 1 user cho 1 khung giờ) ───

@router.post("/bulk-replace")
@limiter.limit("10/minute")
async def bulk_replace_schedule(
    request: Request,
    guild_id: int = Query(...),
    body: dict = Body(...),
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """
    Admin set lại toàn bộ lịch của 1 user cho 1 KHUNG GIỜ cụ thể.
    REPLACE semantics: ngày KHÔNG có trong `weekdays` sẽ bị DEACTIVATE.
    Các khung giờ KHÁC của user KHÔNG bị động đến.

    Body:
      {
        "user_id": "1119880453671899196",
        "weekdays": [0, 2, 3, 4, 5, 6],   # 0=T2 .. 6=CN
        "start_time": "20:50",
        "end_time": "23:15",
        "note": "Sửa lịch trực"           # bắt buộc ≥3 chars
      }
    """
    await require_guild_role(guild_id, "DUTY_ADMIN", current_user, session)

    note = (body.get("note") or "").strip()
    if len(note) < 3:
        raise HTTPException(status_code=400, detail="Bắt buộc lý do (≥3 ký tự).")

    try:
        user_id = int(body.get("user_id"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="user_id phải là số nguyên (Discord ID).")

    weekdays_raw = body.get("weekdays")
    if not isinstance(weekdays_raw, list) or not weekdays_raw:
        raise HTTPException(status_code=400, detail="weekdays phải là list số 0-6 không rỗng.")
    weekdays = set()
    for w in weekdays_raw:
        try:
            wi = int(w)
            if 0 <= wi <= 6:
                weekdays.add(wi)
        except (TypeError, ValueError):
            continue
    if not weekdays:
        raise HTTPException(status_code=400, detail="Không có weekday hợp lệ.")

    try:
        sh, sm = map(int, str(body.get("start_time", "")).split(":"))
        eh, em = map(int, str(body.get("end_time", "")).split(":"))
        start_t = time(sh, sm)
        end_t = time(eh, em)
    except Exception:
        raise HTTPException(status_code=400, detail="start_time/end_time phải dạng HH:MM.")

    crosses_midnight = start_t >= end_t

    # Lấy tất cả entry active có CÙNG start_time
    rows = await session.execute(
        select(MemberSchedule)
        .where(MemberSchedule.guild_id == guild_id)
        .where(MemberSchedule.user_id == user_id)
        .where(MemberSchedule.start_time == start_t)
        .where(MemberSchedule.is_active == True)  # noqa: E712
    )
    existing_map = {s.weekday: s for s in rows.scalars().all()}

    created: list[int] = []
    updated: list[int] = []
    removed: list[int] = []

    for wd in weekdays:
        if wd in existing_map:
            s = existing_map[wd]
            s.end_time = end_t
            s.crosses_midnight = crosses_midnight
            s.is_active = True
            s.updated_at = utcnow()
            updated.append(wd)
        else:
            new_s = MemberSchedule(
                guild_id=guild_id,
                user_id=user_id,
                weekday=wd,
                start_time=start_t,
                end_time=end_t,
                crosses_midnight=crosses_midnight,
                is_active=True,
            )
            session.add(new_s)
            created.append(wd)

    for wd, s in existing_map.items():
        if wd not in weekdays:
            s.is_active = False
            s.updated_at = utcnow()
            removed.append(wd)

    session.add(AuditLog(
        guild_id=guild_id,
        user_id=int(current_user["sub"]),
        username=current_user.get("username", f"user_{current_user['sub']}"),
        action=AuditAction.SCHEDULE_UPDATED,
        detail={
            "for_user": str(user_id),
            "start": start_t.strftime("%H:%M"),
            "end": end_t.strftime("%H:%M"),
            "crosses_midnight": crosses_midnight,
            "created_weekdays": sorted(created),
            "updated_weekdays": sorted(updated),
            "removed_weekdays": sorted(removed),
            "note": note,
            "via": "web",
        },
        created_at=utcnow(),
    ))
    await session.commit()

    try:
        from web.realtime import broadcaster
        await broadcaster.publish(guild_id, {"type": "schedule_updated"})
    except Exception:
        pass

    return {
        "success": True,
        "created": sorted(created),
        "updated": sorted(updated),
        "removed": sorted(removed),
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

    # Batch resolve avatars cho schedule grid
    from web.utils.discord_resolver import batch_resolve_user_info
    _grid_uids = {int(it["user_id"]) for it in items if it.get("user_id")}
    _grid_info = await batch_resolve_user_info(_grid_uids) if _grid_uids else {}
    for it in items:
        try:
            uid_int = int(it["user_id"])
            it["avatar_url"] = (_grid_info.get(uid_int) or {}).get("avatar_url")
        except (TypeError, ValueError):
            it["avatar_url"] = None

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
    Sửa lịch trực.
    Body: {"start_time": "HH:MM", "end_time": "HH:MM", "weekday": int 0-6, "role_name": str}

    Quyền:
      - DUTY_MEMBER: chỉ sửa được lịch của CHÍNH MÌNH
      - DUTY_MOD:    giữ nguyên quy tắc — chỉ sửa được lịch của chính mình (xoá thì
                     được, qua DELETE endpoint)
      - DUTY_ADMIN:  có quyền cao nhất — sửa được lịch của BẤT KỲ ai
    """
    from web.middleware.auth_guard import has_guild_role
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
    is_admin = False
    note = (body.get("note") or "").strip() or None
    if not is_owner:
        # Chỉ DUTY_ADMIN được bypass ownership. MOD vẫn không sửa được lịch người khác.
        is_admin = await has_guild_role(guild_id, "DUTY_ADMIN", current_user, session)
        if not is_admin:
            raise HTTPException(
                status_code=403,
                detail="Chỉ chủ lịch mới sửa được. Mod có thể xoá qua DELETE — chỉ Admin mới sửa lịch người khác.",
            )
    # Audit policy nghiêm ngặt: MỌI thay đổi đều cần lý do (kể cả tự sửa)
    if not note:
        raise HTTPException(
            status_code=400,
            detail="Mọi thay đổi lịch trực đều phải ghi LÝ DO (field 'note').",
        )

    # Snapshot trước khi sửa — để audit có before vs after
    before_snapshot = {
        "weekday": sched.weekday,
        "start": sched.start_time.strftime("%H:%M"),
        "end": sched.end_time.strftime("%H:%M"),
    }

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

    after_snapshot = {
        "weekday": sched.weekday,
        "start": sched.start_time.strftime("%H:%M"),
        "end": sched.end_time.strftime("%H:%M"),
    }
    # Chỉ ghi field nào thực sự đổi
    changes: dict[str, dict] = {}
    for k in ("weekday", "start", "end"):
        if before_snapshot[k] != after_snapshot[k]:
            changes[k] = {"before": before_snapshot[k], "after": after_snapshot[k]}

    audit_detail: dict = {
        "schedule_id": schedule_id,
        "for_user": str(sched.user_id),
        "via": "web",
        "by_role": "ADMIN" if (not is_owner and is_admin) else "OWNER",
        **after_snapshot,
    }
    if changes:
        audit_detail["changes"] = changes
    if note:
        audit_detail["note"] = note

    session.add(AuditLog(
        guild_id=guild_id,
        user_id=user_id,
        username=current_user.get("username", f"user_{user_id}"),
        action=AuditAction.SCHEDULE_UPDATED,
        detail=audit_detail,
        created_at=utcnow(),
    ))
    await session.commit()

    # Publish realtime event
    from web.realtime import broadcaster
    await broadcaster.publish(guild_id, {
        "type": "schedule_updated",
        "schedule_id": schedule_id,
        "user_id": str(sched.user_id),
    })

    return {"success": True, "schedule": _serialize_schedule(sched)}


# ─── DELETE /api/schedule/{id} — owner hoặc ADMIN xoá ─────────────────────────

@router.delete("/{schedule_id}")
@limiter.limit("20/minute")
async def delete_schedule(
    request: Request,
    schedule_id: int = Path(..., gt=0),
    guild_id: int = Query(...),
    note: str | None = Query(None, description="Lý do (bắt buộc khi Admin xoá lịch người khác)"),
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """
    Xoá lịch trực.
    Quyền:
      - DUTY_MEMBER: chỉ xoá được lịch của CHÍNH MÌNH
      - DUTY_MOD:    chỉ xoá được lịch của CHÍNH MÌNH (KHÔNG xoá người khác)
      - DUTY_ADMIN:  xoá được lịch của BẤT KỲ ai
    """
    from web.middleware.auth_guard import has_guild_role
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
    is_admin = False
    note_clean = (note or "").strip() or None
    if not is_owner:
        # CHỈ DUTY_ADMIN được xoá lịch người khác. MOD bị block.
        is_admin = await has_guild_role(guild_id, "DUTY_ADMIN", current_user, session)
        if not is_admin:
            raise HTTPException(
                status_code=403,
                detail="Chỉ chủ lịch hoặc Admin mới xoá được. Mod chỉ xoá được lịch của chính mình.",
            )
    # Audit policy nghiêm ngặt: MỌI lệnh xoá đều cần lý do
    if not note_clean:
        raise HTTPException(
            status_code=400,
            detail="Xoá lịch trực phải ghi LÝ DO (query param 'note').",
        )

    snapshot = {
        "schedule_id": sched.id,
        "user_id": str(sched.user_id),
        "weekday": sched.weekday,
        "start": sched.start_time.strftime("%H:%M"),
        "end": sched.end_time.strftime("%H:%M"),
    }
    await session.delete(sched)
    audit_detail = {
        **snapshot,
        "via": "web",
        "by_role": "ADMIN" if (not is_owner and is_admin) else "OWNER",
    }
    if note_clean:
        audit_detail["note"] = note_clean
    session.add(AuditLog(
        guild_id=guild_id,
        user_id=user_id,
        username=current_user.get("username", f"user_{user_id}"),
        action=AuditAction.SCHEDULE_DELETED,
        detail=audit_detail,
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
