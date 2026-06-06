"""
staff_member.py — Quản lý chức vụ y tế của nhân sự trong từng guild.

Chức vụ là khái niệm BUSINESS (ngành y), khác với role DUTY_ADMIN/MOD/MEMBER
(khái niệm SYSTEM cho permission). Một guild có thể map chức vụ → role hệ thống
qua GuildConfig.position_role_map (admin tự config trong Settings).

Mỗi (guild_id, user_id) chỉ có 1 record duy nhất.
"""
from __future__ import annotations
from datetime import datetime
from sqlalchemy import (
    BigInteger, String, Boolean, DateTime, Text,
    UniqueConstraint, Index,
)
from sqlalchemy.orm import Mapped, mapped_column
from models.base import Base
from bot.utils.time_utils import utcnow


# ─── Position constants ──────────────────────────────────────────────────────

class StaffPosition:
    """Chức vụ trong ngành y. Lưu dạng string trong DB."""
    # LÃNH ĐẠO (cấp 1-4)
    VIEN_TRUONG = "VIEN_TRUONG"          # Viện Trưởng (Director)
    VIEN_PHO = "VIEN_PHO"                # Viện Phó (Deputy Director)
    THU_KY = "THU_KY"                    # Thư Ký
    QUAN_LY_BAC_SI = "QUAN_LY_BAC_SI"    # Quản Lý Bác Sĩ
    # Y TẾ (cấp 5-7)
    TRUONG_KHOA = "TRUONG_KHOA"          # Trưởng Khoa
    PHO_KHOA = "PHO_KHOA"                # Phó Khoa
    BAC_SI = "BAC_SI"                    # Bác Sĩ
    # ĐÀO TẠO (cấp 8)
    THUC_TAP_SINH = "THUC_TAP_SINH"      # Thực Tập Sinh

    ALL = [
        VIEN_TRUONG, VIEN_PHO, THU_KY, QUAN_LY_BAC_SI,
        TRUONG_KHOA, PHO_KHOA, BAC_SI,
        THUC_TAP_SINH,
    ]


class StaffGroup:
    """Nhóm chức vụ — dùng để filter + style ở UI."""
    LANH_DAO = "LANH_DAO"      # 🔴 Lãnh đạo
    Y_TE = "Y_TE"              # 🟢 Y tế
    DAO_TAO = "DAO_TAO"        # ⚪ Đào tạo


# Metadata mỗi chức vụ: label tiếng Việt, nhóm, màu hex, icon, level (thấp = cao)
POSITION_METADATA: dict[str, dict] = {
    StaffPosition.VIEN_TRUONG: {
        "label": "Viện Trưởng",
        "group": StaffGroup.LANH_DAO,
        "color": "#EF4444",  # red-500
        "icon": "🏥",
        "level": 1,
    },
    StaffPosition.VIEN_PHO: {
        "label": "Viện Phó",
        "group": StaffGroup.LANH_DAO,
        "color": "#DC2626",  # red-600
        "icon": "🏥",
        "level": 2,
    },
    StaffPosition.THU_KY: {
        "label": "Thư Ký",
        "group": StaffGroup.LANH_DAO,
        "color": "#F97316",  # orange-500
        "icon": "📋",
        "level": 3,
    },
    StaffPosition.QUAN_LY_BAC_SI: {
        "label": "Quản Lý Bác Sĩ",
        "group": StaffGroup.LANH_DAO,
        "color": "#EAB308",  # yellow-500
        "icon": "👨‍⚕️",
        "level": 4,
    },
    StaffPosition.TRUONG_KHOA: {
        "label": "Trưởng Khoa",
        "group": StaffGroup.Y_TE,
        "color": "#22C55E",  # green-500
        "icon": "🩺",
        "level": 5,
    },
    StaffPosition.PHO_KHOA: {
        "label": "Phó Khoa",
        "group": StaffGroup.Y_TE,
        "color": "#3B82F6",  # blue-500
        "icon": "🩺",
        "level": 6,
    },
    StaffPosition.BAC_SI: {
        "label": "Bác Sĩ",
        "group": StaffGroup.Y_TE,
        "color": "#60A5FA",  # blue-400
        "icon": "👨‍⚕️",
        "level": 7,
    },
    StaffPosition.THUC_TAP_SINH: {
        "label": "Thực Tập Sinh",
        "group": StaffGroup.DAO_TAO,
        "color": "#9CA3AF",  # gray-400
        "icon": "🎓",
        "level": 8,
    },
}

GROUP_METADATA: dict[str, dict] = {
    StaffGroup.LANH_DAO: {"label": "LÃNH ĐẠO", "color": "#EF4444", "icon": "🏥", "order": 1},
    StaffGroup.Y_TE:     {"label": "Y TẾ",      "color": "#22C55E", "icon": "🩺", "order": 2},
    StaffGroup.DAO_TAO:  {"label": "ĐÀO TẠO",   "color": "#9CA3AF", "icon": "🎓", "order": 3},
}


def is_valid_position(pos: str) -> bool:
    return pos in POSITION_METADATA


def get_position_level(pos: str) -> int:
    """Trả về level (1=cao nhất). Vô lệ → 99."""
    return POSITION_METADATA.get(pos, {}).get("level", 99)


# ─── ORM Model ───────────────────────────────────────────────────────────────

class StaffMember(Base):
    __tablename__ = "staff_members"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)

    # Discord user ID (snowflake) — KHÔNG dùng FK vì User table optional
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)

    # Username để hiển thị offline (Discord API có thể down)
    username: Mapped[str] = mapped_column(String(100), nullable=False)

    # Chức vụ — string enum (xem StaffPosition)
    position: Mapped[str] = mapped_column(String(50), nullable=False, default=StaffPosition.BAC_SI)

    # Khoa/Phòng ban (tự do, vd: "Khoa Nội", "Khoa Cấp cứu") — optional
    department: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Ghi chú tự do (vd: "Đang học CKII", "Đảm nhiệm thêm…")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Còn hoạt động không (False = đã nghỉ việc nhưng giữ lại để tra cứu lịch sử)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Ngày vào làm (admin nhập, có thể null)
    joined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        UniqueConstraint("guild_id", "user_id", name="uq_staff_guild_user"),
        Index("ix_staff_guild_position", "guild_id", "position"),
        Index("ix_staff_guild_active", "guild_id", "is_active"),
    )

    def __repr__(self) -> str:
        return (
            f"<StaffMember guild={self.guild_id} user={self.user_id} "
            f"position={self.position}>"
        )
