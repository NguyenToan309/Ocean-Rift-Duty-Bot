"""
duty_identity_binding.py — Gắn Discord user_id với tên ingame.

Logic chấm công:
- Lần đầu user X chấm với tên T → tạo binding (X, T, T) — original=current=T
- Lần sau user X chấm với tên T' → check current_ingame_name == T'
  (PHÂN BIỆT HOA THƯỜNG). Khác → reject.
- Admin /log rebind user X new_name T'' → update current=T'', original giữ
  nguyên + append vào rebind_history. Log cũ trong duty_logs KHÔNG đổi.
"""
from datetime import datetime
from sqlalchemy import BigInteger, String, DateTime, Integer, JSON
from sqlalchemy.orm import Mapped, mapped_column
from models.base import Base
from bot.utils.time_utils import utcnow


class DutyIdentityBinding(Base):
    __tablename__ = "duty_identity_binding"

    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    discord_user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    # Tên ingame lần đầu chấm — KHÔNG bao giờ đổi (read-only audit reference).
    original_ingame_name: Mapped[str] = mapped_column(String(100), nullable=False)

    # Tên ingame ĐANG dùng — admin /log rebind có thể đổi. Lần sau chấm phải khớp
    # cái này. So sánh PHÂN BIỆT HOA THƯỜNG.
    current_ingame_name: Mapped[str] = mapped_column(String(100), nullable=False)

    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    log_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rebind_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # rebind_history: list[{from, to, by, at, reason}]
    # Append mỗi lần admin /log rebind.
    rebind_history: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    def __repr__(self) -> str:
        return (
            f"<DutyIdentityBinding guild={self.guild_id} user={self.discord_user_id} "
            f"current={self.current_ingame_name!r} original={self.original_ingame_name!r}>"
        )
