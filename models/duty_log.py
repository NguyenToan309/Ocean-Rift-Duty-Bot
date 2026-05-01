"""
duty_log.py — Bảng chính lưu mỗi ca trực
Index kép (guild_id, started_at) và (guild_id, user_id) để query thống kê nhanh
"""
from datetime import datetime
from sqlalchemy import BigInteger, String, Integer, DateTime, Text, Index
from sqlalchemy.orm import Mapped, mapped_column
from models.base import Base
from bot.utils.time_utils import utcnow


class DutyLog(Base):
    __tablename__ = "duty_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    # Strict guild isolation — bắt buộc có guild_id trong mọi query
    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # Discord user ID (không foreign key sang bảng users vì member có thể chưa login web)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    username: Mapped[str] = mapped_column(String(100), nullable=False)

    # Thời gian trực (UTC)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Thời gian làm việc tính bằng phút (lấy từ log, không tự tính để tránh sai lệch timezone)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)

    # Nguyên bản text log (để debug khi parse sai)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Nguồn dữ liệu: "ocr" | "forward" | "manual"
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="forward")

    # Discord message ID gốc (để tránh duplicate)
    source_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, unique=True)

    # Người upload/xác nhận (admin có thể nhập thay)
    submitted_by: Mapped[int] = mapped_column(BigInteger, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    # ----- Composite indexes cho query thống kê -----
    __table_args__ = (
        Index("ix_duty_logs_guild_started", "guild_id", "started_at"),
        Index("ix_duty_logs_guild_user", "guild_id", "user_id"),
        Index("ix_duty_logs_guild_user_started", "guild_id", "user_id", "started_at"),
    )

    @property
    def duration_hhmm(self) -> str:
        """Hiển thị dạng '2 giờ 15 phút'"""
        h, m = divmod(self.duration_minutes, 60)
        if h == 0:
            return f"{m} phút"
        return f"{h} giờ {m} phút"

    @property
    def week_number(self) -> int:
        return self.started_at.isocalendar()[1]

    @property
    def quarter(self) -> int:
        return (self.started_at.month - 1) // 3 + 1

    def __repr__(self) -> str:
        return (
            f"<DutyLog guild={self.guild_id} user={self.username} "
            f"duration={self.duration_minutes}m started={self.started_at}>"
        )
