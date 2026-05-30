"""
system_setting.py — Bảng key-value chứa branding global của bot.

Setting hiện có:
- system_name: tên hiển thị web (sidebar logo, login title, browser title)
- bot_activity_text: text Discord presence "đang xem ..."

Mở rộng: thêm key mới chỉ cần INSERT row, không cần migration mới.
"""
from datetime import datetime
from sqlalchemy import String, Text, BigInteger, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from models.base import Base
from bot.utils.time_utils import utcnow


# Default values dùng khi bảng rỗng (chưa migrate hoặc seed fail).
# Bot và web sẽ fallback các giá trị này để không crash.
DEFAULTS: dict[str, str] = {
    "system_name": "Homie Medic",
    "bot_activity_text": "Homie Medic | /log upload",
}


# Whitelist key được phép sửa qua API — chặn caller inject key tuỳ ý vào bảng.
ALLOWED_KEYS: set[str] = set(DEFAULTS.keys())

# Validation length per key
MAX_VALUE_LENGTH: dict[str, int] = {
    "system_name": 60,
    "bot_activity_text": 128,  # Discord activity name limit
}


class SystemSetting(Base):
    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(50), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    def __repr__(self) -> str:
        return f"<SystemSetting {self.key}={self.value[:30]!r}>"
