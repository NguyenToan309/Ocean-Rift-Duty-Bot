"""
test_period_helpers.py — Test các helper period dùng chung trong time_utils
(get_period_label, make_period_choices, PERIOD_LABEL_MAP)

Chạy: pytest tests/test_period_helpers.py -v
"""
import pytest
from bot.utils.time_utils import (
    get_period_label, make_period_choices, PERIOD_LABEL_MAP,
)


class TestPeriodLabel:
    def test_known_periods(self):
        assert get_period_label("day") == "Hôm nay"
        assert get_period_label("week") == "Tuần này"
        assert get_period_label("month") == "Tháng này"
        assert get_period_label("quarter") == "Quý này"
        assert get_period_label("all") == "Toàn bộ thời gian"
        assert get_period_label("custom") == "Khoảng tùy chỉnh"

    def test_unknown_returns_input(self):
        """Period không có trong map → trả về chính chuỗi đó (fallback)"""
        assert get_period_label("unknown_xyz") == "unknown_xyz"

    def test_label_map_has_all_periods(self):
        """Đảm bảo map có đủ các period code dùng trong cogs"""
        for p in ("day", "week", "month", "quarter", "all", "custom"):
            assert p in PERIOD_LABEL_MAP


class TestMakePeriodChoices:
    def test_returns_5_choices(self):
        """5 lựa chọn: day, week, month, quarter, custom (KHÔNG có 'all' — không bao giờ chọn manually)"""
        choices = make_period_choices()
        assert len(choices) == 5

    def test_choice_values(self):
        choices = make_period_choices()
        values = [c.value for c in choices]
        assert "day" in values
        assert "week" in values
        assert "month" in values
        assert "quarter" in values
        assert "custom" in values

    def test_choice_names_have_emoji(self):
        """Tên choice có emoji để dễ phân biệt"""
        choices = make_period_choices()
        names = [c.name for c in choices]
        assert any("📅" in n for n in names)
        assert any("📆" in n for n in names)
        assert any("🗓️" in n for n in names)
