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

    # Channels cho lịch trực + xin nghỉ (cấu hình qua /setup channel-...)
    schedule_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)   # nơi /dangky
    remind_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)     # nơi tag nhắc trực
    leave_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)      # nơi /xinnghi
    staff_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)      # staff quản lý

    # Discord role ID của Medic (để onboarding scan ai chưa đăng ký lịch)
    medic_role_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # Default mốc nhắc trước ca (phút) — JSON list, vd [60, 30, 5]
    # Member có thể override qua MemberSchedule.custom_remind_offsets
    default_remind_offsets: Mapped[list] = mapped_column(
        JSON, nullable=False, default=lambda: [60, 30, 5]
    )

    # Danh sách role ID bị gỡ tự động khi /xinoutnganh được duyệt hoặc /sathai
    # Lưu list[str] để tránh mất chính xác snowflake 64-bit khi serialize JSON
    cleanup_role_ids: Mapped[list] = mapped_column(
        JSON, nullable=False, default=list
    )

    # Map role: {"DUTY_ADMIN": role_id, "DUTY_MOD": role_id, "DUTY_MEMBER": role_id}
    # Lưu dạng JSON vì số lượng role có thể thay đổi
    role_map: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    # Map chức vụ y tế → role hệ thống. Admin tự config trong Settings.
    # VD: {"VIEN_TRUONG": "DUTY_ADMIN", "TRUONG_KHOA": "DUTY_MOD", "BAC_SI": "DUTY_MEMBER"}
    # Bot có thể dùng để auto-cấp role Discord khi đổi chức vụ (optional, tuỳ admin enable).
    position_role_map: Mapped[dict] = mapped_column(
        JSON, nullable=False, default=dict
    )

    # Notification settings — admin toggle bật/tắt từ Settings.
    # Default keys: {
    #   "remind_register_shift": true,   # Nhắc đăng ký ca trực (onboarding)
    #   "remind_before_shift": true,     # Nhắc trước giờ ca theo default_remind_offsets
    #   "alert_late": true,              # Cảnh báo đi muộn
    #   "alert_burnout": true,           # Cảnh báo vượt giờ tối đa/tuần
    #   "daily_digest": false,           # Digest 8h sáng
    # }
    notification_settings: Mapped[dict] = mapped_column(
        JSON, nullable=False, default=lambda: {
            "remind_register_shift": True,
            "remind_before_shift": True,
            "alert_late": True,
            "alert_burnout": True,
            "daily_digest": False,
        }
    )

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
