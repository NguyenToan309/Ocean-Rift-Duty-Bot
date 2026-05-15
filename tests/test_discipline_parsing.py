"""
test_discipline_parsing.py — Test parse "thời hạn" cho /kyluat modal.

Chạy: pytest tests/test_discipline_parsing.py -v
"""
import pytest
from datetime import datetime, timezone, timedelta
from bot.cogs.discipline import _parse_duration


class TestParseDuration:
    def test_days(self):
        label, end = _parse_duration("7 ngày")
        assert label == "7 ngày"
        assert end is not None
        # Check end ≈ now + 7 days (sai số <1 phút)
        expected = datetime.now(timezone.utc) + timedelta(days=7)
        assert abs((end - expected).total_seconds()) < 60

    def test_days_no_diacritic(self):
        label, _ = _parse_duration("7 ngay")
        assert label == "7 ngày"

    def test_days_english(self):
        label, _ = _parse_duration("3 days")
        assert label == "3 ngày"

    def test_weeks(self):
        label, end = _parse_duration("2 tuần")
        assert label == "2 tuần"
        expected = datetime.now(timezone.utc) + timedelta(weeks=2)
        assert abs((end - expected).total_seconds()) < 60

    def test_months(self):
        label, end = _parse_duration("1 tháng")
        assert label == "1 tháng"
        # 1 tháng = 30 ngày approx
        expected = datetime.now(timezone.utc) + timedelta(days=30)
        assert abs((end - expected).total_seconds()) < 60

    def test_permanent_vi(self):
        label, end = _parse_duration("vĩnh viễn")
        assert label == "Vĩnh viễn"
        assert end is None

    def test_permanent_no_diacritic(self):
        label, end = _parse_duration("vinh vien")
        assert label == "Vĩnh viễn"
        assert end is None

    def test_permanent_english(self):
        label, end = _parse_duration("permanent")
        assert label == "Vĩnh viễn"
        assert end is None

    def test_free_text(self):
        """Text không match pattern → giữ nguyên label, end=None"""
        label, end = _parse_duration("Đến hết tháng 5")
        assert "Đến hết tháng 5" in label
        assert end is None

    def test_empty(self):
        label, end = _parse_duration("")
        assert label == "Không xác định"
        assert end is None

    def test_whitespace(self):
        label, end = _parse_duration("   ")
        assert label == "Không xác định"
        assert end is None

    def test_with_extra_spaces(self):
        label, _ = _parse_duration("  7   ngày  ")
        assert label == "7 ngày"

    def test_case_insensitive(self):
        label, _ = _parse_duration("7 NGÀY")
        assert label == "7 ngày"
