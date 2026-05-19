"""
schedule_engine.py — Logic xử lý lịch trực:
- find_matching_schedule: tìm lịch khớp với 1 ca log đã chấm (auto-link)
- list_upcoming_occurrences: liệt kê các lần ca trực sắp tới (cho reminder loop)
- compute_compliance: tính tuân thủ trong 1 khoảng thời gian
- is_user_on_leave: check user có xin nghỉ đã duyệt trong ngày X không
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, date, time, timedelta, timezone
from typing import Iterable

import pytz
from sqlalchemy import select, and_, or_, func
from sqlalchemy.ext.asyncio import AsyncSession

from models.schedule import MemberSchedule
from models.duty_log import DutyLog
from models.leave import LeaveRequest, LeaveRequestType, LeaveRequestStatus

from bot.utils.time_utils import to_local, utcnow

# ─── Hằng số ──────────────────────────────────────────────────────────────────

# Tối thiểu phải trực bao nhiêu phút trong khoảng đăng ký để tính "đúng giờ"
COMPLIANCE_MIN_MINUTES = 60   # 1 giờ

# Phân loại compliance
STATUS_ON_TIME = "on_time"        # ✅ Đúng giờ (overlap ≥ 60p)
STATUS_LATE = "late"              # ⏰ Có log nhưng < 60p
STATUS_MISSED = "missed"          # 🚫 Không có log
STATUS_OFF_SCHEDULE = "off_schedule"  # 🆓 Có log ngoài lịch
STATUS_ON_LEAVE = "on_leave"      # 🏖 Đang nghỉ phép (không tính)


# ─── Schedule occurrence (1 lần ca cụ thể trong tuần) ─────────────────────────

@dataclass
class ScheduleOccurrence:
    """1 lần xuất hiện cụ thể của 1 lịch lặp — vd 'lịch T2 18-20h, ngày 27/04'"""
    schedule: MemberSchedule
    occurrence_date: date          # ngày local cụ thể
    start_dt_utc: datetime         # bắt đầu thực tế (UTC, đã convert từ guild tz)
    end_dt_utc: datetime           # kết thúc thực tế (UTC)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _combine_in_tz(d: date, t: time, tz_str: str) -> datetime:
    """Ghép date + time → datetime aware trong timezone đã cho"""
    tz = pytz.timezone(tz_str)
    naive = datetime.combine(d, t)
    return tz.localize(naive)


def schedule_occurrence_to_utc(
    schedule: MemberSchedule,
    occurrence_date: date,
    guild_tz: str,
) -> tuple[datetime, datetime]:
    """
    Trả về (start_utc, end_utc) cho 1 lần xảy ra của schedule vào ngày `occurrence_date`.
    Ca qua đêm (crosses_midnight) → end thuộc ngày HÔM SAU.
    """
    start_local = _combine_in_tz(occurrence_date, schedule.start_time, guild_tz)
    if schedule.crosses_midnight or schedule.end_time <= schedule.start_time:
        end_local = _combine_in_tz(
            occurrence_date + timedelta(days=1), schedule.end_time, guild_tz
        )
    else:
        end_local = _combine_in_tz(occurrence_date, schedule.end_time, guild_tz)
    return start_local.astimezone(pytz.utc), end_local.astimezone(pytz.utc)


# ─── Tìm lịch khớp với 1 ca log (cho auto-link) ───────────────────────────────

async def find_matching_schedule(
    session: AsyncSession,
    guild_id: int,
    user_id: int,
    log_started_at: datetime,
    log_ended_at: datetime,
    guild_tz: str = "Asia/Ho_Chi_Minh",
) -> MemberSchedule | None:
    """
    Tìm MemberSchedule khớp với log đã chấm:
    - Cùng user_id
    - Cùng thứ (weekday của log.started_at trong guild_tz)
    - Khoảng giờ schedule overlap với log

    Trả về schedule khớp NHẤT (hoặc None nếu log "ngoài lịch").
    """
    # Convert log times sang local để lấy weekday + time
    if log_started_at.tzinfo is None:
        log_started_at = log_started_at.replace(tzinfo=timezone.utc)
    log_local = to_local(log_started_at, guild_tz)
    weekday = log_local.weekday()

    rows = await session.execute(
        select(MemberSchedule)
        .where(MemberSchedule.guild_id == guild_id)
        .where(MemberSchedule.user_id == user_id)
        .where(MemberSchedule.weekday == weekday)
        .where(MemberSchedule.is_active == True)  # noqa: E712
    )
    candidates = rows.scalars().all()
    if not candidates:
        return None

    # Tìm schedule có khoảng giờ overlap với log
    for sched in candidates:
        sched_start_utc, sched_end_utc = schedule_occurrence_to_utc(
            sched, log_local.date(), guild_tz
        )
        # overlap: A.start < B.end AND A.end > B.start
        if log_started_at < sched_end_utc and log_ended_at > sched_start_utc:
            return sched

    return None


# ─── Liệt kê các occurrence sắp tới (cho reminder loop) ───────────────────────

async def list_upcoming_occurrences(
    session: AsyncSession,
    guild_id: int,
    guild_tz: str,
    now_utc: datetime,
    horizon_minutes: int = 75,
) -> list[ScheduleOccurrence]:
    """
    Liệt kê các occurrence lịch trực sắp xảy ra trong cửa sổ [now, now + horizon].
    Dùng cho reminder loop: "có ai sắp đến giờ trong 75 phút tới không?"

    Lưu ý: 1 schedule = lặp hằng tuần; cần tính ra các occurrence cụ thể.
    Window 75p đủ cover mốc 60 phút trước.
    """
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)

    horizon_end = now_utc + timedelta(minutes=horizon_minutes)

    # Lấy tất cả schedules active của guild
    rows = await session.execute(
        select(MemberSchedule)
        .where(MemberSchedule.guild_id == guild_id)
        .where(MemberSchedule.is_active == True)  # noqa: E712
    )
    schedules = rows.scalars().all()

    out: list[ScheduleOccurrence] = []
    tz = pytz.timezone(guild_tz)
    now_local = now_utc.astimezone(tz)

    # Mỗi schedule có thể xảy ra hôm nay hoặc ngày mai (nếu cross-midnight horizon)
    candidate_dates = [now_local.date(), now_local.date() + timedelta(days=1)]

    for sched in schedules:
        for d in candidate_dates:
            # Kiểm tra weekday khớp với schedule.weekday
            if d.weekday() != sched.weekday:
                continue
            start_utc, end_utc = schedule_occurrence_to_utc(sched, d, guild_tz)
            # Lấy occurrence nếu start nằm trong window [now, horizon] HOẶC đang chạy
            if start_utc <= horizon_end and end_utc > now_utc:
                out.append(ScheduleOccurrence(
                    schedule=sched,
                    occurrence_date=d,
                    start_dt_utc=start_utc,
                    end_dt_utc=end_utc,
                ))
    return out


# ─── Liệt kê các occurrence trong 1 khoảng (cho compliance report) ───────────

def list_occurrences_in_range(
    schedules: Iterable[MemberSchedule],
    range_start_local_date: date,
    range_end_local_date: date,
    guild_tz: str,
) -> list[ScheduleOccurrence]:
    """
    Cho danh sách schedules + khoảng ngày, expand thành các occurrence cụ thể.
    Mỗi schedule (vd "T2 18-20h") xảy ra 1 lần mỗi tuần trong khoảng.
    """
    out: list[ScheduleOccurrence] = []
    days_count = (range_end_local_date - range_start_local_date).days + 1
    for sched in schedules:
        if not sched.is_active:
            continue
        # Duyệt từng ngày trong khoảng, chỉ lấy ngày khớp weekday
        for offset in range(days_count):
            d = range_start_local_date + timedelta(days=offset)
            if d.weekday() != sched.weekday:
                continue
            start_utc, end_utc = schedule_occurrence_to_utc(sched, d, guild_tz)
            out.append(ScheduleOccurrence(
                schedule=sched,
                occurrence_date=d,
                start_dt_utc=start_utc,
                end_dt_utc=end_utc,
            ))
    return out


# ─── Tính tuân thủ (compliance) ───────────────────────────────────────────────

@dataclass
class ComplianceEntry:
    """1 dòng compliance: 1 user + 1 occurrence + status"""
    user_id: int
    username: str          # tên hiển thị (lấy từ schedule.user_id → query Discord nếu cần)
    schedule: MemberSchedule
    occurrence_date: date
    occurrence_start_utc: datetime
    occurrence_end_utc: datetime
    overlap_minutes: int   # số phút log overlap với occurrence
    status: str            # STATUS_*


async def is_user_on_leave(
    session: AsyncSession,
    guild_id: int,
    user_id: int,
    check_date: date,
) -> bool:
    """User có xin nghỉ đã được duyệt cho ngày check_date không?

    NOTE: User có thể có NHIỀU đơn approved overlap (VD nghỉ phép + nghỉ ốm
    cùng ngày, hoặc đơn cũ + đơn revert+resubmit). Dùng .first() tránh crash.
    """
    rows = await session.execute(
        select(LeaveRequest.id)
        .where(LeaveRequest.guild_id == guild_id)
        .where(LeaveRequest.user_id == user_id)
        .where(LeaveRequest.status == LeaveRequestStatus.APPROVED)
        .where(LeaveRequest.start_date <= check_date)
        .where(or_(
            LeaveRequest.end_date == None,  # noqa: E711 — RESIGN không có end_date
            LeaveRequest.end_date >= check_date,
        ))
        .limit(1)
    )
    return rows.first() is not None


async def compute_compliance(
    session: AsyncSession,
    guild_id: int,
    user_id: int | None,           # None = tất cả user
    range_start_utc: datetime,
    range_end_utc: datetime,
    guild_tz: str = "Asia/Ho_Chi_Minh",
) -> list[ComplianceEntry]:
    """
    Tính compliance cho 1 user (hoặc tất cả nếu None) trong khoảng [start, end] UTC.

    Workflow:
    1. Lấy tất cả MemberSchedule của user (hoặc cả guild)
    2. Expand thành list occurrences trong khoảng
    3. Cho mỗi occurrence:
       - Check is_user_on_leave → STATUS_ON_LEAVE
       - Query duty_logs khớp user + occurrence overlap
       - Tính overlap_minutes
       - Phân loại: ≥ 60p = on_time, > 0p = late, = 0 = missed
    4. Cũng tìm các log "ngoài lịch" (schedule_id IS NULL) → STATUS_OFF_SCHEDULE
    """
    # Convert range về local date
    tz = pytz.timezone(guild_tz)
    start_local = range_start_utc.astimezone(tz).date()
    end_local = range_end_utc.astimezone(tz).date()

    # Lấy schedules
    q = select(MemberSchedule).where(MemberSchedule.guild_id == guild_id)
    if user_id is not None:
        q = q.where(MemberSchedule.user_id == user_id)
    schedules = (await session.execute(q)).scalars().all()

    occurrences = list_occurrences_in_range(schedules, start_local, end_local, guild_tz)

    # Lấy tất cả logs trong khoảng (để map nhanh)
    log_q = (
        select(DutyLog)
        .where(DutyLog.guild_id == guild_id)
        .where(DutyLog.started_at < range_end_utc)
        .where(DutyLog.ended_at > range_start_utc)
    )
    if user_id is not None:
        log_q = log_q.where(DutyLog.user_id == user_id)
    logs = (await session.execute(log_q)).scalars().all()

    # Map user_id → list[DutyLog]
    logs_by_user: dict[int, list[DutyLog]] = {}
    for log in logs:
        logs_by_user.setdefault(log.user_id, []).append(log)

    # Tên user (lấy từ log gần nhất nếu có, hoặc tag user_id)
    name_cache: dict[int, str] = {}
    for log in logs:
        if log.user_id not in name_cache:
            name_cache[log.user_id] = log.username

    out: list[ComplianceEntry] = []

    # 1. Process occurrences
    for occ in occurrences:
        uid = occ.schedule.user_id
        username = name_cache.get(uid, f"User#{uid}")

        # Check on leave
        if await is_user_on_leave(session, guild_id, uid, occ.occurrence_date):
            out.append(ComplianceEntry(
                user_id=uid, username=username,
                schedule=occ.schedule, occurrence_date=occ.occurrence_date,
                occurrence_start_utc=occ.start_dt_utc,
                occurrence_end_utc=occ.end_dt_utc,
                overlap_minutes=0, status=STATUS_ON_LEAVE,
            ))
            continue

        # Tính overlap với các log của user
        user_logs = logs_by_user.get(uid, [])
        overlap = _max_overlap_minutes(user_logs, occ.start_dt_utc, occ.end_dt_utc)

        if overlap >= COMPLIANCE_MIN_MINUTES:
            status = STATUS_ON_TIME
        elif overlap > 0:
            status = STATUS_LATE
        else:
            status = STATUS_MISSED

        out.append(ComplianceEntry(
            user_id=uid, username=username,
            schedule=occ.schedule, occurrence_date=occ.occurrence_date,
            occurrence_start_utc=occ.start_dt_utc, occurrence_end_utc=occ.end_dt_utc,
            overlap_minutes=overlap, status=status,
        ))

    # 2. Logs ngoài lịch (schedule_id IS NULL trong khoảng)
    off_log_q = log_q.where(DutyLog.schedule_id == None)  # noqa: E711
    off_logs = (await session.execute(off_log_q)).scalars().all()
    for log in off_logs:
        # Tạo entry "off_schedule" — không có schedule object thật
        out.append(ComplianceEntry(
            user_id=log.user_id,
            username=log.username,
            schedule=None,  # type: ignore[arg-type]
            occurrence_date=log.started_at.astimezone(tz).date(),
            occurrence_start_utc=log.started_at,
            occurrence_end_utc=log.ended_at,
            overlap_minutes=log.duration_minutes,
            status=STATUS_OFF_SCHEDULE,
        ))

    return out


def _max_overlap_minutes(
    logs: list[DutyLog],
    occ_start_utc: datetime,
    occ_end_utc: datetime,
) -> int:
    """
    Tính tổng phút overlap GIỮA các logs và occurrence (không double-count).
    Cộng dồn các overlap riêng lẻ (không tính phần ngoài occurrence).
    """
    total = 0
    for log in logs:
        s = log.started_at if log.started_at.tzinfo else log.started_at.replace(tzinfo=timezone.utc)
        e = log.ended_at if log.ended_at.tzinfo else log.ended_at.replace(tzinfo=timezone.utc)
        # Overlap = max(0, min(e, occ_end) - max(s, occ_start))
        overlap_start = max(s, occ_start_utc)
        overlap_end = min(e, occ_end_utc)
        if overlap_end > overlap_start:
            total += int((overlap_end - overlap_start).total_seconds() // 60)
    return total
