"""
test_time_utils.py — Unit test cho time_utils.py
"""
import pytest
from datetime import datetime
import pytz
from bot.utils.time_utils import (
    get_period_range, get_custom_range, minutes_to_hhmm, get_quarter_label
)

VN_TZ = "Asia/Ho_Chi_Minh"


def test_minutes_to_hhmm():
    assert minutes_to_hhmm(0)   == "0 phút"
    assert minutes_to_hhmm(45)  == "45 phút"
    assert minutes_to_hhmm(60)  == "1 giờ"
    assert minutes_to_hhmm(90)  == "1 giờ 30 phút"
    assert minutes_to_hhmm(135) == "2 giờ 15 phút"
    assert minutes_to_hhmm(-5)  == "0 phút"


def test_get_quarter_label():
    assert get_quarter_label(1)  == "Q1"
    assert get_quarter_label(3)  == "Q1"
    assert get_quarter_label(4)  == "Q2"
    assert get_quarter_label(6)  == "Q2"
    assert get_quarter_label(7)  == "Q3"
    assert get_quarter_label(10) == "Q4"
    assert get_quarter_label(12) == "Q4"


def test_period_day():
    ref = datetime(2026, 4, 27, 14, 30, 0, tzinfo=pytz.utc)
    start, end = get_period_range("day", ref, VN_TZ)
    # UTC+7 → 27/04/2026 00:00 VN = 26/04/2026 17:00 UTC
    assert start.day == 26
    assert start.hour == 17
    assert start.minute == 0


def test_period_week_starts_monday():
    # 27/04/2026 là Chủ nhật (weekday=6) → tuần bắt đầu 21/04
    ref = datetime(2026, 4, 27, 0, 0, 0, tzinfo=pytz.utc)
    start, end = get_period_range("week", ref, VN_TZ)
    # start giờ là aware UTC — chuyển thẳng về VN timezone
    local_start = start.astimezone(pytz.timezone(VN_TZ))
    assert local_start.weekday() == 0  # Thứ 2


def test_custom_range_valid():
    start, end = get_custom_range("01/04/2026", "30/04/2026", VN_TZ)
    assert start < end


def test_custom_range_invalid_format():
    with pytest.raises(ValueError, match="Định dạng"):
        get_custom_range("2026-04-01", "2026-04-30", VN_TZ)


def test_custom_range_start_after_end():
    with pytest.raises(ValueError, match="trước"):
        get_custom_range("30/04/2026", "01/04/2026", VN_TZ)
