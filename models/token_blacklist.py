"""
token_blacklist.py — Lưu JWT token đã bị thu hồi (logout)
Redis lưu primary để check nhanh, bảng này là backup persistent
"""
from datetime import datetime
from sqlalchemy import String, DateTime, BigInteger, Index
from sqlalchemy.orm import Mapped, mapped_column
from models.base import Base
from bot.utils.time_utils import utcnow


class BlacklistedToken(Base):
    __tablename__ = "token_blacklist"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    # JWT ID (jti claim) — unique identifier của token
    jti: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)

    # Discord user ID để có thể invalidate tất cả token của một user
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # Thời điểm token hết hạn — dùng để dọn dẹp record cũ
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Thời điểm bị blacklist (logout hoặc force revoke)
    blacklisted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    __table_args__ = (
        Index("ix_blacklist_user_exp", "user_id", "expires_at"),
        # Hỗ trợ cleanup_tokens.py query nhanh: WHERE expires_at < now()
        Index("ix_token_blacklist_expires", "expires_at"),
    )

    def __repr__(self) -> str:
        return f"<BlacklistedToken jti={self.jti} user={self.user_id}>"
