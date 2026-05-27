"""
leave.py — Đơn xin nghỉ phép (tạm thời) + xin out ngành (vĩnh viễn)
Dùng chung 1 model với cột `request_type` phân biệt.
"""
from datetime import datetime, date
from sqlalchemy import (
    BigInteger, String, Date, DateTime, Text, Index, JSON, text,
)
from sqlalchemy.orm import Mapped, mapped_column
from models.base import Base
from bot.utils.time_utils import utcnow


class LeaveRequestType:
    """Loại đơn"""
    LEAVE = "leave"            # /xinnghi — xin nghỉ tạm thời (có start + end)
    RESIGN = "resign"          # /xinoutnganh — xin out hẳn (chỉ có start)


class LeaveRequestStatus:
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"     # user tự huỷ trước khi staff duyệt


class LeaveRequest(Base):
    """
    Đơn xin nghỉ / xin out ngành.
    Workflow: user submit → staff react ✅/❌ trong channel xin nghỉ → status đổi → DM user.
    """
    __tablename__ = "leave_requests"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    username: Mapped[str] = mapped_column(String(100), nullable=False)

    request_type: Mapped[str] = mapped_column(String(20), nullable=False, default=LeaveRequestType.LEAVE)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=LeaveRequestStatus.PENDING)

    # Khoảng nghỉ: start_date bắt buộc; end_date optional (cho RESIGN có thể null)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    reason: Mapped[str] = mapped_column(Text, nullable=False)

    # Discord message ID nơi staff vote (để bot listen react).
    # Unique constraint chuyển sang partial index (migration 009): chỉ
    # enforce trên non-null. Xem __table_args__ bên dưới.
    vote_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    vote_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # Ai duyệt (Discord user ID), khi nào, ghi chú
    decided_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Bot dùng cờ này để track đơn web đã duyệt nhưng chưa xử lý DM/cleanup.
    # Web set decided_at + status → bot scan + DM/cleanup → set processed_at.
    # Khi duyệt qua react Discord, processed_at được set ngay cùng lúc với decided_at.
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Metadata thêm (vd: avatar URL người xin để hiển thị)
    detail: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    __table_args__ = (
        Index("ix_leave_guild_user", "guild_id", "user_id"),
        Index("ix_leave_guild_status", "guild_id", "status"),
        Index("ix_leave_guild_dates", "guild_id", "start_date", "end_date"),
        # Partial unique index — chỉ enforce uniqueness khi vote_message_id
        # không null. Đa số đơn sau xử lý có thể null vote_message_id.
        Index(
            "ix_leave_vote_msg_unique",
            "vote_message_id",
            unique=True,
            postgresql_where=text("vote_message_id IS NOT NULL"),
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<LeaveRequest #{self.id} type={self.request_type} "
            f"user={self.user_id} status={self.status}>"
        )
