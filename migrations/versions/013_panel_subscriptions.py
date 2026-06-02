"""Bảng panel_subscriptions — track pinned panel messages để auto-refresh.

Khi admin chạy /panel-* với pin=True, bot lưu (guild, panel_type, channel,
message) vào bảng này. Background task chạy mỗi 5 phút iterate bảng để edit
embed mới với data hiện tại. Nếu message bị xoá → entry tự bị xoá khỏi DB.

panel_type: 'overview' | 'duty' | 'leave' | 'resign' | 'schedule'
Mỗi guild × panel_type chỉ tracked 1 message tại 1 thời điểm (chạy /panel
lần 2 sẽ overwrite entry cũ).

Revision ID: 013
Revises: 012
Create Date: 2026-06-02
"""
from alembic import op
import sqlalchemy as sa


revision = "013"
down_revision = "012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "panel_subscriptions",
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("panel_type", sa.String(20), nullable=False),
        sa.Column("channel_id", sa.BigInteger(), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=False),
        sa.Column("period", sa.String(20), nullable=True),   # cho overview
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("guild_id", "panel_type"),
    )


def downgrade() -> None:
    op.drop_table("panel_subscriptions")
