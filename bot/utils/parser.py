"""
parser.py — Parse text LOG DUTY từ tin nhắn forward hoặc kết quả OCR
Trả về ParsedDutyLog hoặc None nếu không hợp lệ

Lưu ý validate():
- Cho phép ngày trong QUÁ KHỨ bất kỳ (không giới hạn)
- Không cho phép ca trực ở TƯƠNG LAI (check sau to_utc() trong _save_duty_log)
- Kiểm tra started_at < ended_at và duration khớp thực tế (±5 phút)
"""
import re
from datetime import datetime
from dataclasses import dataclass

DATE_FORMAT = "%d/%m/%Y %H:%M:%S"

# Regex parse LOG DUTY — dùng \S{1,3} cho ký tự tiếng Việt OCR hay đọc sai dấu
# (ầ→ẩ, ờ→ơ, ặ→ậ, etc). \S khớp bất kỳ chữ nào không phải whitespace.
# Date/time: cho phép cả /, -, . làm separator, năm 2-4 chữ số
_DATETIME_PAT = r"\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}\s+\d{1,2}[:\.]\d{1,2}[:\.]\d{1,2}"

DUTY_LOG_PATTERN = re.compile(
    r"LOG\s*DUTY\s+"
    r"T\S{0,2}n\s*[:：]\s*(?P<name>[^\n:：]+?)\s+"
    r"Th\S{1,3}i\s*gian\s*l\S{1,3}m\s*vi\S{1,3}c\s*[:：]\s*(?P<duration>\d+)\s*ph\S{0,3}t\s+"
    r"Th\S{1,3}i\s*gian\s*b\S{1,3}t\s*[dđ]\S{1,3}u\s*[:：]\s*(?P<started_at>" + _DATETIME_PAT + r")\s+"
    r"Th\S{1,3}i\s*gian\s*k\S{1,3}t\s*th\S{1,3}c\s*[:：]\s*(?P<ended_at>" + _DATETIME_PAT + r")",
    re.IGNORECASE,
)

# Regex lỏng — không phụ thuộc keyword Tiếng Việt, chỉ tìm STRUCTURE:
# "LOG DUTY" → tên → số phút → 2 ngày giờ
# Dùng [\s\S]*? để cross-line match khi OCR sai bét keyword
DUTY_LOG_LOOSE_PATTERN = re.compile(
    r"L[O0o].{0,3}D.{0,2}TY"                                        # "LOG DUTY" mờ
    r"[\s\S]{1,80}?[:：]\s*(?P<name>[^\n:：]{1,60}?)\s*\n"          # tên (sau dấu : đầu tiên)
    r"[\s\S]{1,150}?(?P<duration>\d{1,4})\s*ph[uúù]?t"              # X phút
    r"[\s\S]{1,150}?(?P<started_at>\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}\s+\d{1,2}[:\.]\d{1,2}[:\.]\d{1,2})"
    r"[\s\S]{1,150}?(?P<ended_at>\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}\s+\d{1,2}[:\.]\d{1,2}[:\.]\d{1,2})",
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


def parse_duty_text(text: str) -> ParsedDutyLog | None:
    """
    Parse text LOG DUTY.
    Thử regex chuẩn trước, fallback sang regex lỏng nếu thất bại.
    Trả về None nếu cả hai đều thất bại.
    """
    if not text or len(text) > 5000:
        return None

    text = text.strip()
    # Chuẩn hoá: thay 1 số ký tự OCR hay đọc nhầm thành tương đương
    # Bỏ ký tự đặc biệt thường gặp ở đầu/giữa (icons, dấu •)
    text = re.sub(r"[•·●○◦▾▸▼►]+", " ", text)

    # Thử regex chuẩn
    match = DUTY_LOG_PATTERN.search(text)
    is_loose = False

    if not match:
        # Fallback sang regex lỏng (OCR có thể nhận sai ký tự tiếng Việt)
        match = DUTY_LOG_LOOSE_PATTERN.search(text)
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
        )
    except (ValueError, AttributeError) as e:
        import logging as _logging
        _logging.getLogger(__name__).warning(f"Parse duty log thất bại: {e} | text={text[:200]}")
        return None
