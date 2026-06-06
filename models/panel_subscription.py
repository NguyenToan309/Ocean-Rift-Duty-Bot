"""
panel_subscription.py — Track pinned panel messages cho auto-refresh.

Mỗi guild × panel_type lưu 1 entry (PK composite). Background task
(bot/tasks/schedule_tasks.py::refresh_panels_tick) iterate bảng này mỗi
5 phút để edit embed với data mới.
"""
from datetime import datetime
from sqlalchemy import BigInteger, String, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from models.base import Base
from bot.utils.time_utils import utcnow


PANEL_TYPES = ("overview", "duty", "leave", "resign", "schedule")


class PanelSubscription(Base):
    __tablename__ = "panel_subscriptions"

    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # 'overview' | 'duty' | 'leave' | 'resign' | 'schedule'
    panel_type: Mapped[str] = mapped_column(String(20), primary_key=True)

    channel_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # Cho /panel overview — cần lưu period để re-render đúng khoảng thời gian.
    # Các panel khác để NULL.
    period: Mapped[str | None] = mapped_column(String(20), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    def __repr__(self) -> str:
        return (
            f"<PanelSubscription guild={self.guild_id} type={self.panel_type} "
            f"channel={self.channel_id} msg={self.message_id}>"
        )
