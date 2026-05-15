"""
test_compliance_calc.py — Test logic tính tỷ lệ compliance trong /lich tongket.

Theo nghiệp vụ:
- Tỷ lệ đúng giờ chỉ tính trên ca PHẢI trực (loại off_schedule + on_leave).
- Ca on_leave KHÔNG đếm vào denominator (nghỉ phép đã duyệt là hợp lệ).

Chạy: pytest tests/test_compliance_calc.py -v
"""
import pytest
from bot.utils.schedule_engine import (
    STATUS_ON_TIME, STATUS_LATE, STATUS_MISSED,
    STATUS_OFF_SCHEDULE, STATUS_ON_LEAVE,
)


def calc_rate(counters: dict) -> float:
    """Helper: tính tỷ lệ giống logic trong cog/web"""
    countable = sum(
        counters.get(s, 0) for s in (STATUS_ON_TIME, STATUS_LATE, STATUS_MISSED)
    )
    if countable == 0:
        return 0.0
    return counters.get(STATUS_ON_TIME, 0) / countable * 100


class TestComplianceRate:
    def test_all_on_time(self):
        counters = {STATUS_ON_TIME: 5}
        assert calc_rate(counters) == 100.0

    def test_half_missed(self):
        counters = {STATUS_ON_TIME: 5, STATUS_MISSED: 5}
        assert calc_rate(counters) == 50.0

    def test_late_counts_as_not_on_time(self):
        """Late ca trễ giờ không tính là on_time"""
        counters = {STATUS_ON_TIME: 0, STATUS_LATE: 10}
        assert calc_rate(counters) == 0.0

    def test_on_leave_excluded_from_denominator(self):
        """5 ca on_time + 5 ca on_leave → tỷ lệ = 100% (chỉ tính ca phải trực)"""
        counters = {STATUS_ON_TIME: 5, STATUS_ON_LEAVE: 5}
        assert calc_rate(counters) == 100.0

    def test_off_schedule_excluded_from_denominator(self):
        """off_schedule = log ngoài lịch, không phải ca đăng ký → loại"""
        counters = {STATUS_ON_TIME: 5, STATUS_OFF_SCHEDULE: 10}
        assert calc_rate(counters) == 100.0

    def test_complex_mix(self):
        """3 đúng + 1 trễ + 1 vắng + 2 nghỉ phép + 4 ngoài lịch → 3/5 = 60%"""
        counters = {
            STATUS_ON_TIME: 3,
            STATUS_LATE: 1,
            STATUS_MISSED: 1,
            STATUS_ON_LEAVE: 2,
            STATUS_OFF_SCHEDULE: 4,
        }
        assert calc_rate(counters) == 60.0

    def test_empty_counters(self):
        assert calc_rate({}) == 0.0

    def test_only_on_leave(self):
        """Chỉ có ca nghỉ phép → countable=0 → trả 0% (không có ca để chấm)"""
        counters = {STATUS_ON_LEAVE: 5}
        assert calc_rate(counters) == 0.0

    def test_only_off_schedule(self):
        """Chỉ có log ngoài lịch (chưa đăng ký lịch) → 0% (không có ca phải trực)"""
        counters = {STATUS_OFF_SCHEDULE: 10}
        assert calc_rate(counters) == 0.0
