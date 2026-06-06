"""
duty_log.py — Bảng chính lưu mỗi ca trực
Index kép (guild_id, started_at) và (guild_id, user_id) để query thống kê nhanh
"""
from datetime import datetime
from sqlalchemy import (
    BigInteger, String, Integer, DateTime, Text, Index, UniqueConstraint, ForeignKey,
    text,
)
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

    # Nguồn dữ liệu: "ocr" | "forward" | "manual" | "message"
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="forward")

    # Format LOG DUTY v2 (CAPY TOWN LOGS) fields — nullable vì V1 cũ không có
    # và V2 cũng có thể không có exit_reason (thoát bình thường).
    discord_handle: Mapped[str | None] = mapped_column(String(100), nullable=True)
    exit_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Discord message ID gốc (để tránh duplicate auto-scan).
    # Unique constraint chuyển sang partial index (migration 009): chỉ
    # enforce trên non-null. Xem __table_args__ bên dưới.
    source_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # Người upload/xác nhận (admin có thể nhập thay)
    submitted_by: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # Auto-link với MemberSchedule khi log khớp với lịch đăng ký
    # NULL = log "ngoài lịch" (member trực không có trong lịch)
    schedule_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("member_schedules.id", ondelete="SET NULL"),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    __table_args__ = (
        # Query thống kê theo kỳ (filter guild + date range)
        Index("ix_duty_logs_guild_started", "guild_id", "started_at"),
        # Query theo user trong guild
        Index("ix_duty_logs_guild_user", "guild_id", "user_id"),
        # Query ranking: guild + date range + group by user — covering index tránh heap scan
        Index("ix_duty_logs_ranking_cover", "guild_id", "started_at", "user_id", "duration_minutes"),
        # Query overlap check: tìm ca trực chồng lấp cùng user
        Index("ix_duty_logs_overlap", "guild_id", "user_id", "started_at", "ended_at"),
        # DB-level unique constraint: chặn race condition Layer 2
        # (application check không đủ khi 2 requests đồng thời)
        UniqueConstraint(
            "guild_id", "user_id", "started_at", "ended_at",
            name="uq_duty_log_entry"
        ),
        # Index hỗ trợ query compliance: filter logs theo schedule
        Index("ix_duty_logs_schedule", "schedule_id"),
        # Partial unique index — chỉ enforce uniqueness khi source_message_id
        # không null. NULL rows (manual log không gắn message) không tham gia.
        Index(
            "ix_duty_logs_source_msg_unique",
            "source_message_id",
            unique=True,
            postgresql_where=text("source_message_id IS NOT NULL"),
        ),
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
