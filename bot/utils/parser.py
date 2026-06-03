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
# thứ tự field trong OCR có thể không cố định.
#
# OCR-tolerant: thay vì match chính xác ký tự tiếng Việt (vd "ê", "ổ"), dùng
# \S{0,2} cho ký tự có dấu. Cách này match được:
# - Tên / Tên / Ten / Tèn / Tên (OCR đọc nhầm dấu)
# - Tổng / Tong / Tỗng / Tống
# - Bắt / Bat / Bặt / Bât
# - Kết / Ket / Kểt
# - Phút / Phut / Phưt
# - Giờ / Gio / Gìờ
#
# Dấu phân tách label-value: chấp nhận :, ：, ; (OCR đôi khi đọc nhầm).

_LABEL_SEP = r"[:：;]"

# Lookahead stop pattern: dùng cho các field text (name, discord, reason) để
# stop CAPTURE khi gặp label kế tiếp. Lý do: EasyOCR với paragraph=True có
# thể join hết các dòng vào 1 paragraph (không có \n), khi đó regex greedy
# `[^\n]+` sẽ nuốt cả block log thành "name" → vượt 100 ký tự → reject.
# Lookahead này chấp nhận khoảng trắng + 1 trong các label kế tiếp HOẶC
# end-of-line / end-of-string.
_NEXT_LABEL = (
    r"(?=\s+(?:"
    r"Discord\s*[:：;]"        # "Discord:"
    r"|T\S{0,2}n\s+[Dd]iscord"  # "Tên discord"
    r"|T\S{0,2}ng\s*th"         # "Tổng thời..."
    r"|B\S{0,2}t\s+[dđ]"        # "Bắt đầu"
    r"|K\S{0,2}t\s+th"          # "Kết thúc"
    r"|L\S{0,2}\s+do"           # "Lý do"
    r")|\n|$)"
)

# Pattern dùng cho normalize_for_ocr — match khoảng trắng + label kế tiếp
# (KHÔNG ở đầu dòng), thay bằng newline + label để parser regex chạy đúng.
# Dùng fixed-width lookbehind (?<=[^\n]) thay vì variable lookbehind (?<!^).
_LABEL_HEAD_PAT = re.compile(
    r"(?<=[^\n])"      # phải có ký tự non-newline ngay trước (không ở đầu)
    r"[ \t]+"          # ăn khoảng trắng ngang giữa value cũ và label mới
    r"(?="
    r"T\S{0,2}n\s+[Dd]iscord"     # "Tên discord"
    r"|Discord\s*[:：;]"           # "Discord:"
    r"|T\S{0,2}ng\s*th\S{0,2}i"   # "Tổng thời..."
    r"|B\S{0,2}t\s+[dđ]\S{0,2}u"  # "Bắt đầu"
    r"|K\S{0,2}t\s+th\S{0,2}c"    # "Kết thúc"
    r"|L\S{0,2}\s+do\s+r"          # "Lý do rời"
    r")",
    re.IGNORECASE,
)


def normalize_ocr_text(text: str) -> str:
    """Chèn '\\n' trước mỗi label nhận biết được để parser regex chạy đúng.

    EasyOCR đôi khi gộp tất cả label + value vào 1 dòng (paragraph=True).
    Khi đó text trông như:
        "CAPY TOWN LOGS Tên: Báo Lê Discord: @VT Tổng thời gian: 1 Giờ ..."
    Normalize sẽ insert \\n trước "Discord:", "Tổng thời gian:", v.v. để regex
    field-by-field chạy đúng:
        "CAPY TOWN LOGS\\nTên: Báo Lê\\nDiscord: @VT\\nTổng thời gian: 1 Giờ ..."

    Idempotent: text đã có \\n thì không thêm nữa.
    """
    if not text:
        return text
    return _LABEL_HEAD_PAT.sub(r"\n", text)


_FIELD_NAME = re.compile(
    # Non-greedy + stop ở label kế tiếp HOẶC newline HOẶC EOL.
    r"T\S{0,2}n\s*" + _LABEL_SEP + r"\s*(?P<name>[^\n]+?)" + _NEXT_LABEL,
    re.IGNORECASE,
)
_FIELD_DISCORD = re.compile(
    # Match "Discord:" hoặc "Tên discord:" / "Tên Discord:" — Discord là tên
    # riêng tiếng Anh nên thường OCR đọc đúng, không cần loose.
    r"(?:T\S{0,2}n\s+)?Discord\s*" + _LABEL_SEP + r"\s*(?P<discord>[^\n]+?)" + _NEXT_LABEL,
    re.IGNORECASE,
)
_FIELD_DURATION_V2 = re.compile(
    # 3 unit có thể combine: "1 Giờ 10 Phút 39 Giây" / "39 Giây" / "7 Phút".
    # Tất cả group optional, nhưng ít nhất 1 phải có (kiểm tra ngoài).
    #
    # Phân biệt "Giờ" và "Giây": cả 2 bắt đầu "Gi" nhưng "Giây" kết thúc bằng "y".
    # Hours pattern dùng lookbehind (?<![yY]) để KHÔNG match "Giây".
    # Seconds pattern bắt buộc kết thúc bằng "y" để phân biệt.
    r"T\S{0,2}ng\s*th\S{0,2}i\s*gian\s*" + _LABEL_SEP + r"\s*"
    r"(?:(?P<hours>\d+)\s*G\S{1,3}(?<![yY])(?=\s|$|\d))?\s*"
    r"(?:(?P<minutes>\d+)\s*Ph\S{0,2}t)?\s*"
    r"(?:(?P<seconds>\d+)\s*G\S{1,3}y)?",
    re.IGNORECASE,
)
_FIELD_START = re.compile(
    # "Bắt đầu" / "Bat dau" / "Bặt dầu"...
    r"B\S{0,2}t\s+[dđ]\S{0,2}u\s*" + _LABEL_SEP + r"\s*(?P<started_at>" + _DATETIME_PAT + r")",
    re.IGNORECASE,
)
_FIELD_END = re.compile(
    r"K\S{0,2}t\s*th\S{0,2}c\s*" + _LABEL_SEP + r"\s*(?P<ended_at>" + _DATETIME_PAT + r")",
    re.IGNORECASE,
)
_FIELD_REASON = re.compile(
    r"L\S{0,2}\s*do\s*r\S{0,2}i\s*" + _LABEL_SEP + r"\s*(?P<reason>[^\n]+)",
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

    # Duration: gộp "X Giờ Y Phút Z Giây" → total minutes (round up nếu có giây)
    hours = duration_m.group("hours")
    minutes = duration_m.group("minutes")
    seconds = duration_m.group("seconds")
    if not hours and not minutes and not seconds:
        return None
    total_seconds = (
        (int(hours) * 3600 if hours else 0)
        + (int(minutes) * 60 if minutes else 0)
        + (int(seconds) if seconds else 0)
    )
    if total_seconds <= 0:
        return None
    # Round up: ca ngắn (vd 39 giây) vẫn ghi nhận = 1 phút để qua validation
    # duration > 0. Validation tolerance ±5 phút sẽ bao trùm.
    total_minutes = max(1, (total_seconds + 30) // 60)

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

    # Thử V2 trực tiếp trước
    result = _parse_v2(text)
    if result:
        return result

    # OCR có thể gộp tất cả field vào 1 dòng → normalize chèn \n trước mỗi
    # label rồi thử V2 lần nữa.
    normalized = normalize_ocr_text(text)
    if normalized != text:
        result = _parse_v2(normalized)
        if result:
            return result

    # Fallback V1
    return _parse_v1(text)


# ─── Backward compat alias ───────────────────────────────────────────────────
# Các module khác có thể đang import DUTY_LOG_PATTERN — giữ alias cho V1
DUTY_LOG_PATTERN = DUTY_LOG_PATTERN_V1
DUTY_LOG_LOOSE_PATTERN = DUTY_LOG_LOOSE_PATTERN_V1
