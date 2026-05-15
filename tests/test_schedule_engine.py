"""
test_schedule_engine.py — Test logic schedule_engine:
- schedule_occurrence_to_utc: tính UTC từ schedule + ngày local
- _max_overlap_minutes: tính overlap giữa logs và occurrence

Chạy: pytest tests/test_schedule_engine.py -v
"""
import pytest
from datetime import datetime, time, date, timedelta, timezone
from unittest.mock import MagicMock

from bot.utils.schedule_engine import (
    schedule_occurrence_to_utc, _max_overlap_minutes,
    STATUS_ON_TIME, STATUS_LATE, STATUS_MISSED,
    COMPLIANCE_MIN_MINUTES,
)


def _make_sched_mock(weekday=0, start=time(18, 0), end=time(20, 0), crosses_midnight=False):
    s = MagicMock()
    s.weekday = weekday
    s.start_time = start
    s.end_time = end
    s.crosses_midnight = crosses_midnight
    return s


def _make_log(start_utc: datetime, end_utc: datetime):
    """Tạo mock DutyLog với started_at + ended_at"""
    log = MagicMock()
    log.started_at = start_utc
    log.ended_at = end_utc
    return log


# ─── schedule_occurrence_to_utc ──────────────────────────────────────────────

class TestOccurrenceToUtc:
    def test_normal_shift(self):
        """T2 18:00-20:00 ngày 04/05/2026 (Vietnam) → 11:00-13:00 UTC cùng ngày"""
        sched = _make_sched_mock(weekday=0, start=time(18, 0), end=time(20, 0))
        s_utc, e_utc = schedule_occurrence_to_utc(sched, date(2026, 5, 4), "Asia/Ho_Chi_Minh")
        assert s_utc.hour == 11
        assert s_utc.minute == 0
        assert e_utc.hour == 13
        assert s_utc.tzinfo is not None  # aware datetime

    def test_overnight_shift(self):
        """22:00-02:00 (qua đêm) → end là ngày HÔM SAU"""
        sched = _make_sched_mock(start=time(22, 0), end=time(2, 0), crosses_midnight=True)
        s_utc, e_utc = schedule_occurrence_to_utc(sched, date(2026, 5, 4), "Asia/Ho_Chi_Minh")
        # 22:00 VN = 15:00 UTC; 02:00 VN ngày hôm sau = 19:00 UTC ngày hôm trước (vì +7)
        # Thực ra: 02:00 VN ngày 5/5 = 19:00 UTC ngày 4/5
        assert e_utc > s_utc
        diff_hours = (e_utc - s_utc).total_seconds() / 3600
        assert abs(diff_hours - 4) < 0.01  # đúng 4 giờ

    def test_overnight_implicit_via_end_lte_start(self):
        """end_time < start_time → tự động xử lý như qua đêm dù crosses_midnight=False"""
        sched = _make_sched_mock(start=time(23, 0), end=time(1, 0), crosses_midnight=False)
        s_utc, e_utc = schedule_occurrence_to_utc(sched, date(2026, 5, 4), "Asia/Ho_Chi_Minh")
        assert e_utc > s_utc

    def test_morning_shift_utc7(self):
        """8:00-12:00 VN → 1:00-5:00 UTC"""
        sched = _make_sched_mock(start=time(8, 0), end=time(12, 0))
        s_utc, e_utc = schedule_occurrence_to_utc(sched, date(2026, 5, 4), "Asia/Ho_Chi_Minh")
        assert s_utc.hour == 1
        assert e_utc.hour == 5


# ─── _max_overlap_minutes ────────────────────────────────────────────────────

class TestOverlap:
    def test_full_overlap(self):
        """Log nằm gọn trong occurrence"""
        occ_start = datetime(2026, 5, 4, 11, 0, tzinfo=timezone.utc)
        occ_end = datetime(2026, 5, 4, 13, 0, tzinfo=timezone.utc)
        log = _make_log(
            datetime(2026, 5, 4, 11, 30, tzinfo=timezone.utc),
            datetime(2026, 5, 4, 12, 30, tzinfo=timezone.utc),
        )
        assert _max_overlap_minutes([log], occ_start, occ_end) == 60

    def test_partial_overlap_start(self):
        """Log bắt đầu trước occurrence, kết thúc giữa"""
        occ_start = datetime(2026, 5, 4, 11, 0, tzinfo=timezone.utc)
        occ_end = datetime(2026, 5, 4, 13, 0, tzinfo=timezone.utc)
        log = _make_log(
            datetime(2026, 5, 4, 10, 0, tzinfo=timezone.utc),
            datetime(2026, 5, 4, 12, 0, tzinfo=timezone.utc),
        )
        # Overlap = 11:00 → 12:00 = 60 phút
        assert _max_overlap_minutes([log], occ_start, occ_end) == 60

    def test_no_overlap(self):
        """Log hoàn toàn ngoài occurrence"""
        occ_start = datetime(2026, 5, 4, 11, 0, tzinfo=timezone.utc)
        occ_end = datetime(2026, 5, 4, 13, 0, tzinfo=timezone.utc)
        log = _make_log(
            datetime(2026, 5, 4, 14, 0, tzinfo=timezone.utc),
            datetime(2026, 5, 4, 15, 0, tzinfo=timezone.utc),
        )
        assert _max_overlap_minutes([log], occ_start, occ_end) == 0

    def test_multiple_logs_sum(self):
        """Nhiều log cộng dồn"""
        occ_start = datetime(2026, 5, 4, 11, 0, tzinfo=timezone.utc)
        occ_end = datetime(2026, 5, 4, 13, 0, tzinfo=timezone.utc)
        log1 = _make_log(
            datetime(2026, 5, 4, 11, 0, tzinfo=timezone.utc),
            datetime(2026, 5, 4, 11, 30, tzinfo=timezone.utc),
        )
        log2 = _make_log(
            datetime(2026, 5, 4, 12, 0, tzinfo=timezone.utc),
            datetime(2026, 5, 4, 12, 45, tzinfo=timezone.utc),
        )
        assert _max_overlap_minutes([log1, log2], occ_start, occ_end) == 30 + 45

    def test_empty_logs(self):
        occ_start = datetime(2026, 5, 4, 11, 0, tzinfo=timezone.utc)
        occ_end = datetime(2026, 5, 4, 13, 0, tzinfo=timezone.utc)
        assert _max_overlap_minutes([], occ_start, occ_end) == 0

    def test_naive_datetime_handled(self):
        """Logs với datetime naive vẫn xử lý được (giả định UTC)"""
        occ_start = datetime(2026, 5, 4, 11, 0, tzinfo=timezone.utc)
        occ_end = datetime(2026, 5, 4, 13, 0, tzinfo=timezone.utc)
        log = MagicMock()
        log.started_at = datetime(2026, 5, 4, 11, 30)  # naive
        log.ended_at = datetime(2026, 5, 4, 12, 30)    # naive
        # Function tự convert naive → UTC
        result = _max_overlap_minutes([log], occ_start, occ_end)
        assert result == 60


class TestComplianceConstants:
    def test_min_minutes_is_60(self):
        """Theo yêu cầu user: tối thiểu 1 giờ = 60 phút"""
        assert COMPLIANCE_MIN_MINUTES == 60

    def test_status_constants_distinct(self):
        statuses = {STATUS_ON_TIME, STATUS_LATE, STATUS_MISSED}
        assert len(statuses) == 3
