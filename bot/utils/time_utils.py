"""
time_utils.py — Tiện ích xử lý thời gian, ISO week, quý, quy đổi
Tất cả datetime nội bộ dùng UTC, chỉ convert sang timezone local khi hiển thị
"""
from datetime import datetime, timedelta, timezone
import pytz
from bot.config import settings


def get_local_tz() -> pytz.BaseTzInfo:
    return pytz.timezone(settings.DEFAULT_TIMEZONE)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def to_utc(dt: datetime, from_tz: str | None = None) -> datetime:
    """Chuyển datetime sang UTC. Nếu dt naive, giả định là from_tz (hoặc DEFAULT_TIMEZONE)."""
    tz = pytz.timezone(from_tz or settings.DEFAULT_TIMEZONE)
    if dt.tzinfo is None:
        dt = tz.localize(dt)
    return dt.astimezone(pytz.utc)


def to_local(dt: datetime, tz_str: str | None = None) -> datetime:
    """Chuyển UTC datetime sang timezone hiển thị"""
    tz = pytz.timezone(tz_str or settings.DEFAULT_TIMEZONE)
    if dt.tzinfo is None:
        dt = pytz.utc.localize(dt)
    return dt.astimezone(tz)


def get_period_range(
    period: str,
    ref_date: datetime | None = None,
    tz_str: str | None = None,
) -> tuple[datetime, datetime]:
    """
    Trả về (start_utc, end_utc) cho period: 'day' | 'week' | 'month' | 'quarter' | 'all'
    'all' = từ 1970 đến tương lai xa, dùng để xem toàn bộ dữ liệu.
    ref_date nên là UTC. Tính toán dựa theo timezone của guild.
    """
    if period == "all":
        # 1970 → 2099 — khoảng đủ rộng cho mọi dữ liệu thực tế
        return (
            datetime(1970, 1, 1, tzinfo=pytz.utc),
            datetime(2099, 12, 31, 23, 59, 59, tzinfo=pytz.utc),
        )

    tz = pytz.timezone(tz_str or settings.DEFAULT_TIMEZONE)
    now = (ref_date or utcnow()).astimezone(tz)

    if period == "day":
        start_local = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end_local = start_local + timedelta(days=1) - timedelta(seconds=1)

    elif period == "week":
        # ISO week: Thứ 2 (weekday=0) → Chủ nhật (weekday=6)
        start_local = now - timedelta(days=now.weekday())
        start_local = start_local.replace(hour=0, minute=0, second=0, microsecond=0)
        end_local = start_local + timedelta(days=7) - timedelta(seconds=1)

    elif period == "month":
        start_local = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        # Tháng tiếp theo ngày 1 - 1 giây = cuối tháng hiện tại
        if now.month == 12:
            next_month_start = start_local.replace(year=now.year + 1, month=1)
        else:
            next_month_start = start_local.replace(month=now.month + 1)
        end_local = next_month_start - timedelta(seconds=1)

    elif period == "quarter":
        quarter_start_month = ((now.month - 1) // 3) * 3 + 1
        start_local = now.replace(
            month=quarter_start_month, day=1,
            hour=0, minute=0, second=0, microsecond=0
        )
        # Cuối quý = đầu quý tiếp - 1 giây
        end_month = quarter_start_month + 2
        if end_month >= 12:
            next_quarter_start = start_local.replace(year=now.year + 1, month=1)
        else:
            next_quarter_start = start_local.replace(month=end_month + 1)
        end_local = next_quarter_start - timedelta(seconds=1)

    else:
        raise ValueError(f"Period không hợp lệ: {period}. Dùng: day|week|month|quarter|all")

    return (
        start_local.astimezone(pytz.utc),
        end_local.astimezone(pytz.utc),
    )


def get_custom_range(
    date_from: str, date_to: str, tz_str: str | None = None
) -> tuple[datetime, datetime]:
    """
    Parse khoảng thời gian tùy chỉnh từ chuỗi DD/MM/YYYY.
    Trả về (start_utc, end_utc) đã convert về UTC.
    """
    tz = pytz.timezone(tz_str or settings.DEFAULT_TIMEZONE)
    try:
        start_local = datetime.strptime(date_from.strip(), "%d/%m/%Y")
        end_local = datetime.strptime(date_to.strip(), "%d/%m/%Y")
    except ValueError:
        raise ValueError("Định dạng ngày không hợp lệ. Dùng: DD/MM/YYYY")

    start_local = tz.localize(start_local.replace(hour=0, minute=0, second=0))
    end_local = tz.localize(end_local.replace(hour=23, minute=59, second=59))

    if start_local > end_local:
        raise ValueError("Ngày bắt đầu phải trước ngày kết thúc")

    return (
        start_local.astimezone(pytz.utc),
        end_local.astimezone(pytz.utc),
    )


def minutes_to_hhmm(minutes: int) -> str:
    """Ví dụ: 135 → '2 giờ 15 phút' | 45 → '45 phút'"""
    if minutes < 0:
        return "0 phút"
    h, m = divmod(minutes, 60)
    if h == 0:
        return f"{m} phút"
    if m == 0:
        return f"{h} giờ"
    return f"{h} giờ {m} phút"


def get_quarter_label(month: int) -> str:
    """Tháng → label quý. VD: 4 → 'Q2'"""
    return f"Q{(month - 1) // 3 + 1}"


def format_datetime_vn(dt: datetime, tz_str: str | None = None) -> str:
    """Format datetime sang chuỗi tiếng Việt: '14:30 Thứ 3, 27/04/2026'

    Convention:
    - Naive datetime → giả định ĐÃ ở target tz (parser output, local time)
      → KHÔNG convert, format trực tiếp
    - Aware datetime → convert qua to_local (DB output là UTC aware)
    """
    weekdays = ["Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7", "Chủ nhật"]
    if dt.tzinfo is None:
        # Naive: assume already in display tz (e.g. parser output từ LOG DUTY text)
        local_dt = dt
    else:
        local_dt = to_local(dt, tz_str)
    day_name = weekdays[local_dt.weekday()]
    return f"{local_dt.strftime('%H:%M')} {day_name}, {local_dt.strftime('%d/%m/%Y')}"


# ─── Period choices dùng chung cho slash commands ─────────────────────────────

PERIOD_LABEL_MAP: dict[str, str] = {
    "day":     "Hôm nay",
    "week":    "Tuần này",
    "month":   "Tháng này",
    "quarter": "Quý này",
    "all":     "Toàn bộ thời gian",
    "custom":  "Khoảng tùy chỉnh",
}


def get_period_label(period: str) -> str:
    """Trả về nhãn tiếng Việt của period code."""
    return PERIOD_LABEL_MAP.get(period, period)


def make_period_choices():
    """
    Tạo list app_commands.Choice dùng cho mọi slash command có tham số `ky`.
    Tránh duplicate ở 5 cogs (export, ranking, stats, log_view).
    Import lười: `from discord import app_commands` để time_utils không hard-depend discord.
    """
    from discord import app_commands
    return [
        app_commands.Choice(name="📅 Hôm nay",         value="day"),
        app_commands.Choice(name="📆 Tuần này",        value="week"),
        app_commands.Choice(name="🗓️ Tháng này",       value="month"),
        app_commands.Choice(name="📊 Quý này",         value="quarter"),
        app_commands.Choice(name="🔧 Tùy chỉnh ngày",  value="custom"),
    ]
