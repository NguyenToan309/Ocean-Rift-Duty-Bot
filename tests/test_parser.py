"""
test_parser.py — Unit test cho parser.py
Chạy: pytest tests/test_parser.py -v
"""
import pytest
from datetime import datetime
from bot.utils.parser import parse_duty_text, ParsedDutyLog

VALID_LOG = """LOG DUTY
Tên: Nguyễn Văn A
Thời gian làm việc: 120 phút
Thời gian bắt đầu: 27/04/2026 08:00:00
Thời gian kết thúc: 27/04/2026 10:00:00
made by • DutyBot Sunday April 27 08:00:00 2026"""

INVALID_FORMAT = """Hello world
This is not a duty log"""

PARTIAL_LOG = """LOG DUTY
Tên: Test User
Thời gian làm việc: 60 phút"""


def test_parse_valid_log():
    result = parse_duty_text(VALID_LOG)
    assert result is not None
    assert result.username == "Nguyễn Văn A"
    assert result.duration_minutes == 120
    assert result.started_at == datetime(2026, 4, 27, 8, 0, 0)
    assert result.ended_at == datetime(2026, 4, 27, 10, 0, 0)


def test_parse_invalid_format():
    assert parse_duty_text(INVALID_FORMAT) is None


def test_parse_partial_log():
    assert parse_duty_text(PARTIAL_LOG) is None


def test_parse_empty():
    assert parse_duty_text("") is None
    assert parse_duty_text(None) is None


def test_validation_time_mismatch():
    """Duration 30 phút nhưng thực tế 120 phút → lỗi validation"""
    log = VALID_LOG.replace("120 phút", "30 phút")
    result = parse_duty_text(log)
    assert result is not None
    errors = result.validate()
    assert any("khớp" in e for e in errors)


def test_validation_start_after_end():
    log = VALID_LOG.replace(
        "Thời gian bắt đầu: 27/04/2026 08:00:00",
        "Thời gian bắt đầu: 27/04/2026 11:00:00"
    )
    result = parse_duty_text(log)
    if result:
        errors = result.validate()
        assert any("trước" in e for e in errors)


def test_validation_valid_log():
    result = parse_duty_text(VALID_LOG)
    assert result is not None
    errors = result.validate()
    assert errors == []


def test_parse_single_digit_date():
    """Ngày 1 chữ số: 1/4/2026 thay vì 01/04/2026"""
    log = VALID_LOG.replace("27/04/2026", "1/4/2026")
    result = parse_duty_text(log)
    assert result is not None
    assert result.started_at.day == 1
    assert result.started_at.month == 4
