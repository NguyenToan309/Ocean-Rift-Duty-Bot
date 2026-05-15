"""
test_leave_parsing.py — Test parse date input cho /xinnghi, /xinoutnganh.

Chạy: pytest tests/test_leave_parsing.py -v
"""
import pytest
from datetime import date, datetime
from bot.cogs.leave import _parse_date


class TestParseDate:
    def test_full_date_slash(self):
        assert _parse_date("01/05/2026") == date(2026, 5, 1)

    def test_full_date_dash(self):
        assert _parse_date("01-05-2026") == date(2026, 5, 1)

    def test_full_date_dot(self):
        assert _parse_date("01.05.2026") == date(2026, 5, 1)

    def test_short_year(self):
        """Năm 2 chữ số → 20xx"""
        assert _parse_date("01/05/26") == date(2026, 5, 1)

    def test_dd_mm_only(self):
        """DD/MM (không năm) → year hiện tại"""
        result = _parse_date("01/05")
        assert result.day == 1
        assert result.month == 5
        assert result.year == datetime.now().year

    def test_invalid_format(self):
        with pytest.raises(ValueError):
            _parse_date("not-a-date")

    def test_invalid_day(self):
        with pytest.raises(ValueError):
            _parse_date("32/05/2026")

    def test_invalid_month(self):
        with pytest.raises(ValueError):
            _parse_date("01/13/2026")

    def test_with_whitespace(self):
        assert _parse_date(" 01/05/2026 ") == date(2026, 5, 1)
