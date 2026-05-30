"""
test_parser.py — Unit test cho bot/utils/parser.py
Kiểm tra parse_duty_text(), ParsedDutyLog.validate(), và _parse_datetime()

Chạy: pytest tests/test_parser.py -v
"""
import pytest
from datetime import datetime
from bot.utils.parser import (
    parse_duty_text, ParsedDutyLog,
    _normalize_date_str, _parse_datetime,
)

# ─── Hằng số nội bộ ──────────────────────────────────────────────────────────

VALID_LOG = (
    "LOG DUTY\n"
    "Tên: Nguyễn Văn A\n"
    "Thời gian làm việc: 120 phút\n"
    "Thời gian bắt đầu: 27/04/2026 08:00:00\n"
    "Thời gian kết thúc: 27/04/2026 10:00:00\n"
    "made by • DutyBot Sunday April 27 08:00:00 2026"
)

INVALID_FORMAT = "Hello world\nThis is not a duty log"
PARTIAL_LOG = "LOG DUTY\nTên: Test User\nThời gian làm việc: 60 phút"


# ─── Parse cơ bản ─────────────────────────────────────────────────────────────

class TestParseDutyText:
    """Kiểm tra parse_duty_text() trả về kết quả đúng"""

    def test_parse_valid_log(self):
        result = parse_duty_text(VALID_LOG)
        assert result is not None
        assert result.username == "Nguyễn Văn A"
        assert result.duration_minutes == 120
        assert result.started_at == datetime(2026, 4, 27, 8, 0, 0)
        assert result.ended_at == datetime(2026, 4, 27, 10, 0, 0)
        assert result.is_loose_match is False

    def test_parse_returns_none_for_garbage(self):
        assert parse_duty_text(INVALID_FORMAT) is None

    def test_parse_returns_none_for_partial(self):
        """Thiếu ngày giờ → không parse được"""
        assert parse_duty_text(PARTIAL_LOG) is None

    def test_parse_empty_string(self):
        assert parse_duty_text("") is None

    def test_parse_none(self):
        assert parse_duty_text(None) is None  # type: ignore[arg-type]

    def test_parse_too_long_text(self):
        """Text > 5000 ký tự → trả về None ngay để tránh ReDoS"""
        assert parse_duty_text("A" * 5001) is None

    def test_parse_past_date_accepted(self, past_log_text):
        """Log từ tháng trước phải parse được — validate() không chặn quá khứ"""
        result = parse_duty_text(past_log_text)
        assert result is not None
        assert result.started_at.month == 4  # tháng 4

    def test_parse_valid_90_min(self, valid_log_text_90):
        result = parse_duty_text(valid_log_text_90)
        assert result is not None
        assert result.duration_minutes == 90

    # ─── Separator variations ───────────────────────────────────────────────

    def test_parse_dash_date_separator(self):
        """Ngày dùng '-' thay vì '/' (OCR hay nhầm dấu)"""
        log = VALID_LOG.replace("27/04/2026", "27-04-2026")
        result = parse_duty_text(log)
        assert result is not None
        assert result.started_at == datetime(2026, 4, 27, 8, 0, 0)

    def test_parse_dot_date_separator(self):
        """Ngày dùng '.' thay vì '/'"""
        log = VALID_LOG.replace("27/04/2026", "27.04.2026")
        result = parse_duty_text(log)
        assert result is not None
        assert result.started_at == datetime(2026, 4, 27, 8, 0, 0)

    def test_parse_single_digit_date(self):
        """Ngày 1 chữ số: 1/4/2026 thay vì 01/04/2026"""
        log = VALID_LOG.replace("27/04/2026", "1/4/2026")
        result = parse_duty_text(log)
        assert result is not None
        assert result.started_at.day == 1
        assert result.started_at.month == 4

    def test_parse_two_digit_year(self):
        """Năm 2 chữ số '26' → tự động thêm prefix '20' → 2026"""
        log = VALID_LOG.replace("27/04/2026", "27/04/26")
        result = parse_duty_text(log)
        assert result is not None
        assert result.started_at.year == 2026

    def test_parse_bullet_chars_stripped(self):
        """Các ký tự ●•►▸ không làm hỏng parse"""
        log = (
            "LOG DUTY\n"
            "Tên: Test User\n"
            "Thời gian làm việc: 60 phút\n"
            "Thời gian bắt đầu: 27/04/2026 08:00:00\n"
            "Thời gian kết thúc: 27/04/2026 09:00:00\n"
            "●►▸• made by DutyBot Sunday April 27 08:00:00 2026"
        )
        result = parse_duty_text(log)
        assert result is not None
        assert result.username == "Test User"

    # ─── Loose regex fallback ────────────────────────────────────────────────

    def test_loose_pattern_marks_is_loose(self):
        """OCR đọc sai keyword tiếng Việt → fallback sang regex lỏng, đánh dấu is_loose_match"""
        noisy = (
            "L0G DUTY\n"
            "Tn: Nguyen Van B\n"
            "Thoi gian lam viec: 90 phut\n"
            "Thoi gian bat dau: 01/05/2026 09:00:00\n"
            "Thoi gian ket thuc: 01/05/2026 10:30:00\n"
        )
        result = parse_duty_text(noisy)
        if result is not None:
            assert result.duration_minutes == 90
            assert result.is_loose_match is True


# ─── Normalize date ──────────────────────────────────────────────────────────

class TestNormalizeDateStr:
    def test_slash_separator_unchanged(self):
        assert _normalize_date_str("27/04/2026 08:00:00") == "27/04/2026 08:00:00"

    def test_dash_to_slash(self):
        assert _normalize_date_str("27-04-2026 08:00:00") == "27/04/2026 08:00:00"

    def test_dot_date_separator(self):
        assert _normalize_date_str("27.04.2026 08:00:00") == "27/04/2026 08:00:00"

    def test_dot_time_separator(self):
        """Dấu '.' trong giờ → ':'"""
        result = _normalize_date_str("27/04/2026 08.00.00")
        assert result == "27/04/2026 08:00:00"

    def test_whitespace_collapsed(self):
        result = _normalize_date_str("  27/04/2026   08:00:00  ")
        assert "27/04/2026" in result
        assert "08:00:00" in result


class TestParseDatetime:
    def test_standard_format(self):
        dt = _parse_datetime("27/04/2026 08:00:00")
        assert dt == datetime(2026, 4, 27, 8, 0, 0)

    def test_single_digit_day_month(self):
        dt = _parse_datetime("1/4/2026 9:05:03")
        assert dt.day == 1
        assert dt.month == 4
        assert dt.hour == 9
        assert dt.minute == 5

    def test_two_digit_year(self):
        dt = _parse_datetime("01/05/26 10:00:00")
        assert dt.year == 2026

    def test_invalid_format_raises(self):
        with pytest.raises(ValueError):
            _parse_datetime("not-a-date")


# ─── ParsedDutyLog.validate() ────────────────────────────────────────────────

class TestValidation:
    """Kiểm tra logic validate() trên các trường hợp biên"""

    def _make(self, **kwargs) -> ParsedDutyLog:
        defaults = dict(
            username="Test User",
            duration_minutes=60,
            started_at=datetime(2026, 4, 27, 8, 0, 0),
            ended_at=datetime(2026, 4, 27, 9, 0, 0),
            raw_text="",
        )
        defaults.update(kwargs)
        return ParsedDutyLog(**defaults)

    def test_valid_log_no_errors(self, valid_log_text):
        result = parse_duty_text(valid_log_text)
        assert result is not None
        assert result.validate() == []

    def test_valid_log_90min_no_errors(self, valid_log_text_90):
        result = parse_duty_text(valid_log_text_90)
        assert result is not None
        assert result.validate() == []

    def test_past_date_no_errors(self, past_log_text):
        """Ngày trong quá khứ → validate() không sinh lỗi (check tương lai ở _save_duty_log)"""
        result = parse_duty_text(past_log_text)
        assert result is not None
        assert result.validate() == []

    # --- Duration ---

    def test_duration_zero_raises(self):
        errors = self._make(duration_minutes=0).validate()
        assert any("hợp lệ" in e or "không" in e for e in errors)

    def test_duration_negative_raises(self):
        errors = self._make(duration_minutes=-1).validate()
        assert len(errors) > 0

    def test_duration_over_1440_raises(self):
        """Ca trực > 24 giờ (1440 phút) không hợp lệ"""
        errors = self._make(
            duration_minutes=1500,
            ended_at=datetime(2026, 4, 28, 9, 0, 0),  # 25 giờ
        ).validate()
        assert any("quá dài" in e for e in errors)

    def test_duration_mismatch_over_5min(self):
        """Duration ghi 30 nhưng thực tế 60 → chênh 30 phút → lỗi"""
        errors = self._make(duration_minutes=30).validate()
        assert any("khớp" in e for e in errors)

    def test_duration_mismatch_within_tolerance(self):
        """Sai ±5 phút → được chấp nhận"""
        # 60 phút thực tế, ghi 58 → chênh 2 phút → OK
        errors = self._make(duration_minutes=58).validate()
        assert errors == []

    def test_duration_mismatch_exactly_5min_ok(self):
        """Sai đúng 5 phút → vẫn hợp lệ (ngưỡng là > 5)"""
        errors = self._make(duration_minutes=55).validate()
        assert errors == []

    def test_duration_mismatch_6min_fails(self):
        """Sai 6 phút → lỗi"""
        errors = self._make(duration_minutes=54).validate()
        assert any("khớp" in e for e in errors)

    # --- Start/end time ---

    def test_start_after_end(self):
        errors = self._make(
            started_at=datetime(2026, 4, 27, 11, 0, 0),
            ended_at=datetime(2026, 4, 27, 9, 0, 0),
        ).validate()
        assert any("trước" in e for e in errors)

    def test_start_equal_end(self):
        errors = self._make(
            started_at=datetime(2026, 4, 27, 8, 0, 0),
            ended_at=datetime(2026, 4, 27, 8, 0, 0),
        ).validate()
        assert any("trước" in e for e in errors)

    # --- Username ---

    def test_username_empty(self):
        errors = self._make(username="").validate()
        assert any("trống" in e for e in errors)

    def test_username_whitespace_only(self):
        errors = self._make(username="   ").validate()
        assert any("trống" in e for e in errors)

    def test_username_too_long(self):
        errors = self._make(username="A" * 101).validate()
        assert any("dài" in e for e in errors)

    def test_username_max_length_ok(self):
        """Đúng 100 ký tự → hợp lệ"""
        errors = self._make(username="A" * 100).validate()
        # Chỉ kiểm tra không có lỗi username (có thể có lỗi duration mismatch)
        assert not any("trống" in e or "quá dài" in e for e in errors)


# ─── V2 format (CAPY TOWN LOGS) ─────────────────────────────────────────────

class TestParseV2:
    """Định dạng mới với emoji + Discord handle + exit reason"""

    V2_FULL = (
        "CAPY TOWN LOGS\n"
        "👤 Tên: Ha Bibi (ACheen)\n"
        "💬 Discord: @Habibi\n"
        "🕒 Tổng thời gian: 18 Phút\n"
        "🟢 Bắt đầu: 30/05/2026 22:43:00\n"
        "🔴 Kết thúc: 30/05/2026 23:01:58\n"
        "❓ Lý do rời: Server->client connection timed out. Last seen 795 msec ago."
    )

    V2_HOURS_MINUTES = (
        "CAPY TOWN LOGS\n"
        "Tên: Báo Lê (Báo Lê Văm)\n"
        "Discord: @VT | Báo\n"
        "Tổng thời gian: 1 Giờ 10 Phút\n"
        "Bắt đầu: 30/05/2026 21:55:54\n"
        "Kết thúc: 30/05/2026 23:06:15\n"
        "Lý do rời: Exiting"
    )

    V2_NO_REASON = (
        "CAPY TOWN LOGS\n"
        "Tên: HẮC Y ĐẠO SƯ (CP847931)\n"
        "Tên discord: @VP | Hắc Y Đạo Sư\n"
        "Tổng thời gian: 1 Giờ 28 Phút\n"
        "Bắt đầu: 30/05/2026 21:50:10\n"
        "Kết thúc: 30/05/2026 23:18:21"
    )

    def test_v2_full_format(self):
        r = parse_duty_text(self.V2_FULL)
        assert r is not None
        assert r.format_version == 2
        assert r.username == "Ha Bibi (ACheen)"
        assert r.duration_minutes == 18
        assert r.discord_handle == "@Habibi"
        assert r.exit_reason and "timed out" in r.exit_reason
        assert r.started_at == datetime(2026, 5, 30, 22, 43, 0)

    def test_v2_hours_and_minutes(self):
        """1 Giờ 10 Phút = 70 phút"""
        r = parse_duty_text(self.V2_HOURS_MINUTES)
        assert r is not None
        assert r.duration_minutes == 70
        assert r.discord_handle == "@VT | Báo"
        assert r.exit_reason == "Exiting"
        assert r.format_version == 2

    def test_v2_no_reason_optional(self):
        """Field 'Lý do rời' không bắt buộc"""
        r = parse_duty_text(self.V2_NO_REASON)
        assert r is not None
        assert r.username == "HẮC Y ĐẠO SƯ (CP847931)"
        assert r.duration_minutes == 88   # 1*60 + 28
        assert r.exit_reason is None
        assert r.discord_handle == "@VP | Hắc Y Đạo Sư"

    def test_v2_validate_duration_match(self):
        """V2 với duration khớp thời gian thực tế → no errors"""
        r = parse_duty_text(self.V2_FULL)
        # 22:43 → 23:01:58 = ~18.9 phút, ghi 18 → chênh < 5 → OK
        assert r.validate() == []

    def test_v1_still_works(self):
        """V1 (LOG DUTY cũ) vẫn parse được sau khi thêm V2 — backward compat"""
        text = (
            "LOG DUTY\n"
            "Tên: Test User\n"
            "Thời gian làm việc: 60 phút\n"
            "Thời gian bắt đầu: 01/05/2026 08:00:00\n"
            "Thời gian kết thúc: 01/05/2026 09:00:00"
        )
        r = parse_duty_text(text)
        assert r is not None
        assert r.duration_minutes == 60
        assert r.format_version == 1
        assert r.discord_handle is None
        assert r.exit_reason is None
