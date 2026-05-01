"""
user.py — Người dùng đã đăng nhập web dashboard qua Discord OAuth2
Tách biệt với dữ liệu chấm công (DutyLog dùng user_id trực tiếp từ Discord)
"""
from datetime import datetime
from sqlalchemy import BigInteger, String, Boolean, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column
from models.base import Base
from cryptography.fernet import Fernet
from bot.config import settings
from bot.utils.time_utils import utcnow

# Fernet instance dùng chung để mã hoá/giải mã
_fernet = Fernet(settings.FERNET_KEY.encode())


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    # Discord user ID — unique key thực sự
    discord_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, index=True)

    username: Mapped[str] = mapped_column(String(100), nullable=False)
    discriminator: Mapped[str | None] = mapped_column(String(10), nullable=True)  # Số #xxxx cũ
    avatar_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # 2FA TOTP secret (mã hoá bằng Fernet trước khi lưu)
    # Chỉ admin cấp cao mới có field này được set
    _totp_secret_encrypted: Mapped[str | None] = mapped_column(
        "totp_secret_encrypted", Text, nullable=True
    )

    is_2fa_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Số lần đăng nhập sai liên tiếp — dùng cho lockout
    failed_login_attempts: Mapped[int] = mapped_column(nullable=False, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_login_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)  # IPv6 max 45 ký tự

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    # ----- Helpers mã hoá TOTP -----

    def set_totp_secret(self, secret: str) -> None:
        """Mã hoá TOTP secret trước khi lưu vào DB"""
        self._totp_secret_encrypted = _fernet.encrypt(secret.encode()).decode()
        self.is_2fa_enabled = True

    def get_totp_secret(self) -> str | None:
        """Giải mã TOTP secret khi cần verify OTP"""
        if not self._totp_secret_encrypted:
            return None
        return _fernet.decrypt(self._totp_secret_encrypted.encode()).decode()

    def is_locked(self) -> bool:
        """Kiểm tra tài khoản có đang bị khóa do nhập sai nhiều lần không"""
        if self.locked_until is None:
            return False
        return utcnow() < self.locked_until

    def __repr__(self) -> str:
        return f"<User discord_id={self.discord_id} username={self.username}>"
