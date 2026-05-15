"""
schedule.py — Lịch trực cố định hàng tuần của member
+ track lịch sử nhắc đã gửi (chống nhắc trùng)
"""
from datetime import datetime, time, date
from sqlalchemy import (
    BigInteger, SmallInteger, Time, Date, DateTime, Boolean,
    String, JSON, Index, UniqueConstraint, ForeignKey,
)
from sqlalchemy.orm import Mapped, mapped_column
from models.base import Base
from bot.utils.time_utils import utcnow


# Weekday convention: 0=Thứ 2 ... 6=Chủ nhật (giống Python date.weekday())
WEEKDAY_LABELS = ["Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7", "Chủ nhật"]
WEEKDAY_SHORT = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"]


class MemberSchedule(Base):
    """
    1 entry = 1 ngày trong tuần + khoảng giờ trực cố định của 1 user.
    User có thể có nhiều entry: ví dụ T2-T6 18h-20h = 5 entries.
    Hỗ trợ ca qua đêm (crosses_midnight=True): start_time > end_time, vd 22:00-02:00.
    """
    __tablename__ = "member_schedules"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    weekday: Mapped[int] = mapped_column(SmallInteger, nullable=False)   # 0=T2..6=CN
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    crosses_midnight: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Mốc nhắc trước ca (phút), JSON list — None = dùng default của guild
    # Ví dụ: [60, 30, 5] → nhắc trước 60p, 30p, 5p
    custom_remind_offsets: Mapped[list | None] = mapped_column(JSON, nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        Index("ix_schedules_guild_user", "guild_id", "user_id"),
        Index("ix_schedules_guild_weekday", "guild_id", "weekday"),
        # Mỗi user 1 thứ 1 ca duy nhất (đăng ký lại sẽ ghi đè) — UNIQUE chặn duplicate
        # NOTE: nếu cần nhiều ca/ngày (sáng + tối) có thể dùng UNIQUE 4-cột (guild, user, weekday, start_time)
        UniqueConstraint(
            "guild_id", "user_id", "weekday", "start_time",
            name="uq_member_schedule_slot",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<MemberSchedule guild={self.guild_id} user={self.user_id} "
            f"{WEEKDAY_SHORT[self.weekday]} {self.start_time}-{self.end_time}>"
        )


class ScheduleReminder(Base):
    """
    Track mỗi notif đã gửi để chống nhắc trùng.
    1 row = (schedule_id, occurrence_date, type) — vd schedule X, ngày 27/04, type='pre_30'.
    """
    __tablename__ = "schedule_reminders"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    schedule_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("member_schedules.id", ondelete="CASCADE"),
        nullable=False,
    )
    occurrence_date: Mapped[date] = mapped_column(Date, nullable=False)
    # Loại nhắc: 'pre_<minutes>' (60/30/15/5/...) | 'pre_end_5' | 'eod_missing'
    reminder_type: Mapped[str] = mapped_column(String(30), nullable=False)
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    __table_args__ = (
        UniqueConstraint(
            "schedule_id", "occurrence_date", "reminder_type",
            name="uq_schedule_reminder_unique",
        ),
        Index("ix_schedule_reminders_date", "occurrence_date"),
    )


class OnboardingLog(Base):
    """
    Track việc đã DM/tag onboarding nhắc nhân viên Medic chưa đăng ký lịch.
    Chống spam: tối đa 1 nhắc / 24h / user.
    """
    __tablename__ = "onboarding_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    last_reminded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    __table_args__ = (
        UniqueConstraint("guild_id", "user_id", name="uq_onboarding_user"),
        Index("ix_onboarding_last_reminded", "last_reminded_at"),
    )
