"""
test_schedule_parsing.py — Test parse input cho /dangky:
- _parse_time: parse "08:00", "8h", "8:30"
- _parse_weekdays: parse "T2,T4,T6", "all", "cả tuần"

Chạy: pytest tests/test_schedule_parsing.py -v
"""
import pytest
from datetime import time
from bot.cogs.schedule import _parse_time, _parse_weekdays


class TestParseTime:
    def test_standard_hhmm(self):
        assert _parse_time("08:00") == time(8, 0)
        assert _parse_time("18:30") == time(18, 30)
        assert _parse_time("23:59") == time(23, 59)

    def test_h_separator(self):
        assert _parse_time("8h") == time(8, 0)
        assert _parse_time("18h30") == time(18, 30)

    def test_dot_separator(self):
        assert _parse_time("18.30") == time(18, 30)

    def test_single_digit_hour(self):
        assert _parse_time("8:00") == time(8, 0)

    def test_with_whitespace(self):
        assert _parse_time(" 08:00 ") == time(8, 0)

    def test_invalid_hour(self):
        with pytest.raises(ValueError):
            _parse_time("25:00")

    def test_invalid_minute(self):
        with pytest.raises(ValueError):
            _parse_time("08:60")

    def test_invalid_format(self):
        with pytest.raises(ValueError):
            _parse_time("abc")

    def test_empty(self):
        with pytest.raises(ValueError):
            _parse_time("")


class TestParseWeekdays:
    def test_single_t2(self):
        assert _parse_weekdays("T2") == [0]

    def test_multiple_comma(self):
        assert _parse_weekdays("T2,T4,T6") == [0, 2, 4]

    def test_multiple_space(self):
        assert _parse_weekdays("T2 T4 T6") == [0, 2, 4]

    def test_lowercase(self):
        assert _parse_weekdays("t2,t4") == [0, 2]

    def test_cn(self):
        assert _parse_weekdays("CN") == [6]
        assert _parse_weekdays("cn") == [6]

    def test_all(self):
        assert _parse_weekdays("all") == [0, 1, 2, 3, 4, 5, 6]
        assert _parse_weekdays("cả tuần") == [0, 1, 2, 3, 4, 5, 6]
        assert _parse_weekdays("ca tuan") == [0, 1, 2, 3, 4, 5, 6]
        assert _parse_weekdays("*") == [0, 1, 2, 3, 4, 5, 6]

    def test_dedup(self):
        """Nhập trùng → chỉ giữ 1"""
        assert _parse_weekdays("T2,T2,T2") == [0]

    def test_sorted(self):
        """Output luôn sorted"""
        assert _parse_weekdays("T6,T2,T4") == [0, 2, 4]

    def test_invalid_token(self):
        with pytest.raises(ValueError, match="Thứ không hợp lệ"):
            _parse_weekdays("T8")

    def test_empty(self):
        with pytest.raises(ValueError):
            _parse_weekdays("")

    def test_english_aliases(self):
        assert _parse_weekdays("monday") == [0]
        assert _parse_weekdays("mon,tue,wed") == [0, 1, 2]
