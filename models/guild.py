"""
guild.py — Cấu hình từng Guild (server Discord)
Mỗi guild có role map, channel log, timezone riêng
"""
from datetime import datetime
from sqlalchemy import BigInteger, String, Boolean, DateTime, JSON
from sqlalchemy.orm import Mapped, mapped_column
from models.base import Base
from bot.utils.time_utils import utcnow


class GuildConfig(Base):
    __tablename__ = "guild_configs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    # Discord guild ID (unique key thực sự)
    guild_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, index=True)

    guild_name: Mapped[str] = mapped_column(String(100), nullable=False)

    # Channel ID được phép gửi log (None = cho phép tất cả channel)
    log_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # Map role: {"DUTY_ADMIN": role_id, "DUTY_MOD": role_id, "DUTY_MEMBER": role_id}
    # Lưu dạng JSON vì số lượng role có thể thay đổi
    role_map: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    # Timezone của guild (VD: "Asia/Ho_Chi_Minh")
    timezone: Mapped[str] = mapped_column(String(50), nullable=False, default="Asia/Ho_Chi_Minh")

    # Guild có đang active không
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )

    def __repr__(self) -> str:
        return f"<GuildConfig guild_id={self.guild_id} name={self.guild_name}>"
