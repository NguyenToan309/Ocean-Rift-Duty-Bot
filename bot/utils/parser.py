"""
parser.py — Parse text LOG DUTY từ tin nhắn forward hoặc kết quả OCR
Trả về ParsedDutyLog hoặc None nếu không hợp lệ

Hỗ trợ 2 định dạng:

V2 — CAPY TOWN LOGS (định dạng mới, có Discord handle + exit reason):
    CAPY TOWN LOGS
    👤 Tên: Ha Bibi (ACheen)
    💬 Discord: @Habibi
    🕒 Tổng thời gian: 1 Giờ 10 Phút
    🟢 Bắt đầu: 30/05/2026 22:43:00
    🔴 Kết thúc: 30/05/2026 23:01:58
    ❓ Lý do rời: Server->client connection timed out

V1 — LOG DUTY (định dạng cũ, giữ backward compat):
    LOG DUTY
    Tên: Nguyễn Văn A
    Thời gian làm việc: 120 phút
    Thời gian bắt đầu: 27/04/2026 08:00:00
    Thời gian kết thúc: 27/04/2026 10:00:00

Lưu ý validate():
- Cho phép ngày trong QUÁ KHỨ bất kỳ (không giới hạn)
- Không cho phép ca trực ở TƯƠNG LAI (check sau to_utc() trong _save_duty_log)
- Kiểm tra started_at < ended_at và duration khớp thực tế (±5 phút)
"""
import re
from datetime import datetime
from dataclasses import dataclass

DATE_FORMAT = "%d/%m/%Y %H:%M:%S"

# Date/time: cho phép cả /, -, . làm separator, năm 2-4 chữ số
_DATETIME_PAT = r"\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}\s+\d{1,2}[:\.]\d{1,2}[:\.]\d{1,2}"

# ─── V1: LOG DUTY (định dạng cũ) ─────────────────────────────────────────────

DUTY_LOG_PATTERN_V1 = re.compile(
    r"LOG\s*DUTY\s+"
    r"T\S{0,2}n\s*[:：]\s*(?P<name>[^\n:：]+?)\s+"
    r"Th\S{1,3}i\s*gian\s*l\S{1,3}m\s*vi\S{1,3}c\s*[:：]\s*(?P<duration>\d+)\s*ph\S{0,3}t\s+"
    r"Th\S{1,3}i\s*gian\s*b\S{1,3}t\s*[dđ]\S{1,3}u\s*[:：]\s*(?P<started_at>" + _DATETIME_PAT + r")\s+"
    r"Th\S{1,3}i\s*gian\s*k\S{1,3}t\s*th\S{1,3}c\s*[:：]\s*(?P<ended_at>" + _DATETIME_PAT + r")",
    re.IGNORECASE,
)

# V1 loose — fallback khi OCR sai ký tự
DUTY_LOG_LOOSE_PATTERN_V1 = re.compile(
    r"L[O0o].{0,3}D.{0,2}TY"
    r"[\s\S]{1,80}?[:：]\s*(?P<name>[^\n:：]{1,60}?)\s*\n"
    r"[\s\S]{1,150}?(?P<duration>\d{1,4})\s*ph[uúù]?t"
    r"[\s\S]{1,150}?(?P<started_at>\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}\s+\d{1,2}[:\.]\d{1,2}[:\.]\d{1,2})"
    r"[\s\S]{1,150}?(?P<ended_at>\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}\s+\d{1,2}[:\.]\d{1,2}[:\.]\d{1,2})",
    re.IGNORECASE,
)

# ─── V2: CAPY TOWN LOGS (định dạng mới) ──────────────────────────────────────
#
# Pattern này tách thành block search vì có thể có/không emoji + field "Lý do
# rời" optional. Dùng [\s\S]*? cross-line, không neo vào "CAPY TOWN" để
# tương thích với header khác (mỗi server có thể đặt tên khác).
#
# Field labels chấp nhận:
#   - "Tên" hoặc "👤 Tên" hoặc "👤Tên"
#   - "Discord", "Tên discord", "Tên Discord", "💬 Discord"
#   - "Tổng thời gian", "🕒 Tổng thời gian"
#   - "Bắt đầu", "🟢 Bắt đầu"
#   - "Kết thúc", "🔴 Kết thúc"
#   - "Lý do rời", "❓ Lý do rời" (optional)

# Sub-pattern dùng để extract từng field riêng — không gộp 1 regex dài vì
# thứ tự field trong OCR có thể không cố định (Discord có thể trước hoặc sau Tên)
_FIELD_NAME = re.compile(
    r"T[êéè]n\s*[:：]\s*(?P<name>[^\n]+)",
    re.IGNORECASE,
)
_FIELD_DISCORD = re.compile(
    # Match "Discord:" hoặc "Tên discord:" / "Tên Discord:"
    r"(?:T[êéè]n\s+)?Discord\s*[:：]\s*(?P<discord>[^\n]+)",
    re.IGNORECASE,
)
_FIELD_DURATION_V2 = re.compile(
    # "1 Giờ 10 Phút" hoặc "18 Phút" hoặc "1 Giờ" (group h và m optional)
    r"T[ổô]ng\s*th[ờo]i\s*gian\s*[:：]\s*"
    r"(?:(?P<hours>\d+)\s*Gi[ờo])?\s*"
    r"(?:(?P<minutes>\d+)\s*Ph[uúù]t)?",
    re.IGNORECASE,
)
_FIELD_START = re.compile(
    r"B[ắâ]t\s*[dđ][ầâ]u\s*[:：]\s*(?P<started_at>" + _DATETIME_PAT + r")",
    re.IGNORECASE,
)
_FIELD_END = re.compile(
    r"K[ếê]t\s*th[uú]c\s*[:：]\s*(?P<ended_at>" + _DATETIME_PAT + r")",
    re.IGNORECASE,
)
_FIELD_REASON = re.compile(
    r"L[yý]\s*do\s*r[ờo]i\s*[:：]\s*(?P<reason>[^\n]+)",
    re.IGNORECASE,
)


@dataclass
class ParsedDutyLog:
    username: str
    duration_minutes: int
    started_at: datetime   # naive — sẽ được to_utc() trước khi lưu DB
    ended_at: datetime     # naive — sẽ được to_utc() trước khi lưu DB
    raw_text: str
    is_loose_match: bool = False  # True nếu dùng regex lỏng
    # Format V2 fields — None nếu parse V1 hoặc field không có trong log
    discord_handle: str | None = None    # vd "@Habibi"
    exit_reason: str | None = None       # vd "Server->client connection timed out"
    format_version: int = 1              # 1 = LOG DUTY cũ, 2 = CAPY TOWN LOGS mới

    def validate(self) -> list[str]:
        """
        Kiểm tra tính hợp lệ của dữ liệu parse được.
        Trả về danh sách lỗi — rỗng = hợp lệ.

        LƯU Ý: validate() chạy trên naive datetime (chưa to_utc).
        Kiểm tra "không ở tương lai" được thực hiện SAU to_utc() trong _save_duty_log.
        Cho phép ngày bất kỳ trong quá khứ.
        """
        errors: list[str] = []

        if not self.username or len(self.username.strip()) == 0:
            errors.append("Tên người dùng không được để trống")
        elif len(self.username) > 100:
            errors.append("Tên người dùng quá dài (tối đa 100 ký tự)")

        if self.duration_minutes <= 0:
            errors.append(f"Thời gian làm việc không hợp lệ: {self.duration_minutes} phút")
        elif self.duration_minutes > 1440:
            errors.append(f"Thời gian làm việc quá dài: {self.duration_minutes} phút (tối đa 24 giờ/ca)")

        if self.started_at >= self.ended_at:
            errors.append("Thời gian bắt đầu phải trước thời gian kết thúc")
        else:
            # Cho phép sai lệch tối đa 5 phút giữa duration ghi và thực tế
            actual_minutes = int((self.ended_at - self.started_at).total_seconds() / 60)
            if abs(actual_minutes - self.duration_minutes) > 5:
                errors.append(
                    f"Thời gian không khớp: ghi {self.duration_minutes} phút "
                    f"nhưng thực tế {actual_minutes} phút "
                    f"(chênh lệch {abs(actual_minutes - self.duration_minutes)} phút)"
                )

        return errors


def _normalize_date_str(date_str: str) -> str:
    """Chuẩn hoá: dấu ngày (-, .) về /, dấu giờ (.) về :, năm 2 chữ số → 4 chữ số"""
    s = re.sub(r"\s+", " ", date_str.strip())
    # Tách phần ngày và giờ
    parts = s.split(" ", 1)
    date_part = re.sub(r"[.\-]", "/", parts[0])
    time_part = parts[1] if len(parts) > 1 else "00:00:00"
    time_part = re.sub(r"\.", ":", time_part)
    return f"{date_part} {time_part}"


def _parse_datetime(date_str: str) -> datetime:
    """Parse datetime, xử lý ngày 1 chữ số (1/1/2024), giờ 1 chữ số, năm 2 chữ số"""
    date_str = _normalize_date_str(date_str)
    parts = date_str.split(" ", 1)
    date_parts = parts[0].split("/")
    if len(date_parts) != 3:
        raise ValueError(f"Định dạng ngày không hợp lệ: {parts[0]}")
    # Pad ngày/tháng 1 chữ số
    date_parts[0] = date_parts[0].zfill(2)
    date_parts[1] = date_parts[1].zfill(2)
    # Năm 2 chữ số → 20xx
    if len(date_parts[2]) == 2:
        date_parts[2] = "20" + date_parts[2]
    elif len(date_parts[2]) != 4:
        raise ValueError(f"Năm không hợp lệ: {date_parts[2]}")

    # Pad giờ 1 chữ số
    time_parts = parts[1].split(":")
    if len(time_parts) != 3:
        raise ValueError(f"Định dạng giờ không hợp lệ: {parts[1]}")
    time_parts = [p.zfill(2) for p in time_parts]

    normalized = "/".join(date_parts) + " " + ":".join(time_parts)
    return datetime.strptime(normalized, DATE_FORMAT)


def _clean_field_value(s: str) -> str:
    """Strip whitespace + bỏ ký tự đặc biệt cuối dòng (icons, bullets)."""
    return re.sub(r"[•·●○◦▾▸▼►\s]+$", "", s.strip())


def _parse_v2(text: str) -> ParsedDutyLog | None:
    """Parse định dạng CAPY TOWN LOGS (V2).

    Trả None nếu thiếu 1 trong các field BẮT BUỘC: name, duration, start, end.
    Discord handle + exit reason là optional.
    """
    name_m = _FIELD_NAME.search(text)
    start_m = _FIELD_START.search(text)
    end_m = _FIELD_END.search(text)
    duration_m = _FIELD_DURATION_V2.search(text)
    if not (name_m and start_m and end_m and duration_m):
        return None

    # Duration: gộp "X Giờ Y Phút" → total minutes
    hours = duration_m.group("hours")
    minutes = duration_m.group("minutes")
    if not hours and not minutes:
        return None
    total_minutes = (int(hours) * 60 if hours else 0) + (int(minutes) if minutes else 0)
    if total_minutes <= 0:
        return None

    try:
        started_at = _parse_datetime(start_m.group("started_at"))
        ended_at = _parse_datetime(end_m.group("ended_at"))
    except ValueError:
        return None

    username = _clean_field_value(name_m.group("name"))
    if not username:
        return None

    # Optional fields
    discord_m = _FIELD_DISCORD.search(text)
    discord_handle = _clean_field_value(discord_m.group("discord")) if discord_m else None
    if discord_handle and not discord_handle.startswith("@"):
        # Đôi khi OCR mất ký tự @, thêm lại để chuẩn
        discord_handle = "@" + discord_handle

    reason_m = _FIELD_REASON.search(text)
    exit_reason = _clean_field_value(reason_m.group("reason")) if reason_m else None

    return ParsedDutyLog(
        username=username,
        duration_minutes=total_minutes,
        started_at=started_at,
        ended_at=ended_at,
        raw_text=text,
        is_loose_match=False,
        discord_handle=discord_handle,
        exit_reason=exit_reason,
        format_version=2,
    )


def _parse_v1(text: str) -> ParsedDutyLog | None:
    """Parse định dạng LOG DUTY cũ (V1) + fallback loose regex."""
    match = DUTY_LOG_PATTERN_V1.search(text)
    is_loose = False

    if not match:
        match = DUTY_LOG_LOOSE_PATTERN_V1.search(text)
        is_loose = True

    if not match:
        return None

    try:
        started_at = _parse_datetime(match.group("started_at"))
        ended_at = _parse_datetime(match.group("ended_at"))
        duration = int(match.group("duration"))
        username = match.group("name").strip()

        return ParsedDutyLog(
            username=username,
            duration_minutes=duration,
            started_at=started_at,
            ended_at=ended_at,
            raw_text=text,
            is_loose_match=is_loose,
            format_version=1,
        )
    except (ValueError, AttributeError) as e:
        import logging as _logging
        _logging.getLogger(__name__).warning(f"Parse V1 thất bại: {e} | text={text[:200]}")
        return None


def parse_duty_text(text: str) -> ParsedDutyLog | None:
    """
    Parse text LOG DUTY. Thử V2 (CAPY TOWN LOGS) trước, fallback V1 (LOG DUTY cũ).
    Trả về None nếu cả 2 đều thất bại.
    """
    if not text or len(text) > 5000:
        return None

    text = text.strip()
    # Chuẩn hoá: bỏ bullet ký tự thường gặp ở đầu/giữa
    text = re.sub(r"[•·●○◦▾▸▼►]+", " ", text)

    # Thử V2 trước vì có nhiều thông tin hơn (discord + reason)
    result = _parse_v2(text)
    if result:
        return result

    # Fallback V1
    return _parse_v1(text)


# ─── Backward compat alias ───────────────────────────────────────────────────
# Các module khác có thể đang import DUTY_LOG_PATTERN — giữ alias cho V1
DUTY_LOG_PATTERN = DUTY_LOG_PATTERN_V1
DUTY_LOG_LOOSE_PATTERN = DUTY_LOG_LOOSE_PATTERN_V1
