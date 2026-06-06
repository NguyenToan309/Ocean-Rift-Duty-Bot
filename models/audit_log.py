"""
audit_log.py — Ghi lại toàn bộ hành động quan trọng
Chỉ DUTY_ADMIN được đọc, không ai được xóa qua ứng dụng
"""
from datetime import datetime
from sqlalchemy import BigInteger, String, DateTime, JSON, Index
from sqlalchemy.orm import Mapped, mapped_column
from models.base import Base
from bot.utils.time_utils import utcnow


# Danh sách action hợp lệ — dùng constant tránh typo
class AuditAction:
    LOGIN_SUCCESS = "LOGIN_SUCCESS"
    LOGIN_FAILED = "LOGIN_FAILED"
    LOGIN_2FA_FAILED = "LOGIN_2FA_FAILED"
    LOGOUT = "LOGOUT"
    EXPORT_CSV = "EXPORT_CSV"
    EXPORT_EXCEL = "EXPORT_EXCEL"
    LOG_UPLOADED = "LOG_UPLOADED"
    LOG_DELETED = "LOG_DELETED"
    LOG_REJECTED = "LOG_REJECTED"
    LOG_RENAMED = "LOG_RENAMED"   # Admin đổi tên (mass rename theo old_name)
    LOG_REBIND = "LOG_REBIND"     # Admin đổi binding ingame_name của 1 user_id
    LOG_WIPED = "LOG_WIPED"       # Bot owner xoá toàn bộ duty_logs của guild
    CHANGE_ROLE_CONFIG = "CHANGE_ROLE_CONFIG"
    CHANGE_CHANNEL_CONFIG = "CHANGE_CHANNEL_CONFIG"
    SETUP_GUILD = "SETUP_GUILD"
    ACCOUNT_LOCKED = "ACCOUNT_LOCKED"
    ACCOUNT_UNLOCKED = "ACCOUNT_UNLOCKED"
    ENABLE_2FA = "ENABLE_2FA"
    # Schedule + leave actions
    SCHEDULE_CREATED = "SCHEDULE_CREATED"
    SCHEDULE_UPDATED = "SCHEDULE_UPDATED"
    SCHEDULE_DELETED = "SCHEDULE_DELETED"
    LEAVE_REQUESTED = "LEAVE_REQUESTED"
    LEAVE_APPROVED = "LEAVE_APPROVED"
    LEAVE_REJECTED = "LEAVE_REJECTED"
    RESIGN_REQUESTED = "RESIGN_REQUESTED"
    RESIGN_APPROVED = "RESIGN_APPROVED"
    RESIGN_REJECTED = "RESIGN_REJECTED"
    REMIND_SENT = "REMIND_SENT"
    ONBOARDING_REMINDED = "ONBOARDING_REMINDED"
    DISCIPLINE = "DISCIPLINE"        # /kyluat (cảnh cáo / khiển trách / phạt)
    DISMISSED = "DISMISSED"          # /sathai (sa thải ngay)
    # Staff position management
    STAFF_ADDED = "STAFF_ADDED"          # Thêm nhân sự vào hệ thống
    STAFF_UPDATED = "STAFF_UPDATED"      # Đổi chức vụ/khoa/note
    STAFF_REMOVED = "STAFF_REMOVED"      # Gỡ khỏi danh sách (deactivate)
    STAFF_ROLE_SYNCED = "STAFF_ROLE_SYNCED"  # Auto-sync Discord role theo chức vụ
    POSITION_ROLE_MAP_CHANGED = "POSITION_ROLE_MAP_CHANGED"  # Admin đổi config map
    # Bot owner admin overview
    ADMIN_OVERVIEW_VIEWED = "ADMIN_OVERVIEW_VIEWED"      # Owner xem trang /admin/overview
    ADMIN_OVERVIEW_REFRESHED = "ADMIN_OVERVIEW_REFRESHED"  # Owner ấn refresh cache
    SYSTEM_SETTINGS_UPDATED = "SYSTEM_SETTINGS_UPDATED"   # Owner đổi system_name / bot_activity_text


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    # guild_id có thể None khi action ở cấp system (VD: login web)
    guild_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)

    # Discord user ID thực hiện hành động
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    username: Mapped[str] = mapped_column(String(100), nullable=False)

    # Loại hành động — xem AuditAction constants ở trên
    action: Mapped[str] = mapped_column(String(50), nullable=False)

    # Chi tiết bổ sung dạng JSON (VD: {"file": "export_2024.xlsx", "rows": 150})
    detail: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    # IP của người thực hiện (từ web dashboard)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, index=True
    )

    __table_args__ = (
        Index("ix_audit_logs_guild_action", "guild_id", "action"),
        Index("ix_audit_logs_user_created", "user_id", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<AuditLog action={self.action} user={self.username} at={self.created_at}>"
