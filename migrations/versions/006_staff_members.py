"""Thêm bảng staff_members + cột position_role_map vào guild_configs.

Mục đích: quản lý chức vụ y tế của nhân sự (Viện Trưởng, Bác Sĩ, …).
Tách biệt với role hệ thống (DUTY_ADMIN/MOD/MEMBER) — chỉ là label business.
Admin có thể map chức vụ → role hệ thống qua position_role_map (config Settings).

Revision ID: 006
Revises: 005
Create Date: 2026-05-16
"""
from alembic import op
import sqlalchemy as sa

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) Bảng staff_members
    op.create_table(
        "staff_members",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(length=100), nullable=False),
        sa.Column("position", sa.String(length=50), nullable=False, server_default="BAC_SI"),
        sa.Column("department", sa.String(length=100), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("guild_id", "user_id", name="uq_staff_guild_user"),
    )
    op.create_index("ix_staff_members_guild_id", "staff_members", ["guild_id"])
    op.create_index("ix_staff_members_user_id", "staff_members", ["user_id"])
    op.create_index("ix_staff_guild_position", "staff_members", ["guild_id", "position"])
    op.create_index("ix_staff_guild_active", "staff_members", ["guild_id", "is_active"])

    # 2) Cột position_role_map vào guild_configs
    op.add_column(
        "guild_configs",
        sa.Column(
            "position_role_map",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'::json"),
        ),
    )


def downgrade() -> None:
    op.drop_column("guild_configs", "position_role_map")
    op.drop_index("ix_staff_guild_active", table_name="staff_members")
    op.drop_index("ix_staff_guild_position", table_name="staff_members")
    op.drop_index("ix_staff_members_user_id", table_name="staff_members")
    op.drop_index("ix_staff_members_guild_id", table_name="staff_members")
    op.drop_table("staff_members")
