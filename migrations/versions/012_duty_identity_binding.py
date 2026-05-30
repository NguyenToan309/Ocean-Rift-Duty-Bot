"""Bảng duty_identity_binding — gắn Discord user ID với tên ingame.

Mục đích: chống impersonation chính xác hơn cơ chế "username lock" cũ.
Lần đầu nhân viên chấm công sẽ tạo binding (user_id, ingame_name).
Lần sau:
- Tên ingame trong log phải KHỚP CHÍNH XÁC (phân biệt hoa thường) với
  current_ingame_name của binding đó (theo user_id).
- Admin có thể đổi current_ingame_name qua /log rebind — không đổi
  original_ingame_name để admin có thể so sánh được lịch sử.

KHÔNG backfill log cũ khi rebind — log lưu username tại thời điểm tạo.

Revision ID: 012
Revises: 011
Create Date: 2026-05-31
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "012"
down_revision = "011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "duty_identity_binding",
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("discord_user_id", sa.BigInteger(), nullable=False),
        sa.Column("original_ingame_name", sa.String(100), nullable=False),
        sa.Column("current_ingame_name", sa.String(100), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("log_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rebind_count", sa.Integer(), nullable=False, server_default="0"),
        # rebind_history: list[{from, to, by, at, reason}] — append mỗi lần admin đổi
        sa.Column(
            "rebind_history",
            postgresql.JSON(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        sa.PrimaryKeyConstraint("guild_id", "discord_user_id"),
    )
    # Index cho lookup theo current_ingame_name (chống 2 user dùng cùng tên ingame).
    # Phân biệt hoa thường — KHÔNG dùng lower() functional index.
    op.create_index(
        "ix_duty_binding_guild_current_name",
        "duty_identity_binding",
        ["guild_id", "current_ingame_name"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_duty_binding_guild_current_name", table_name="duty_identity_binding")
    op.drop_table("duty_identity_binding")
