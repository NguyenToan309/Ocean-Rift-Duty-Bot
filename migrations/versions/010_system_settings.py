"""Bảng system_settings — key-value branding global của bot

Lưu các setting bot owner có thể đổi qua web /admin:
- system_name: tên hiển thị trên web (sidebar, login, browser title)
- bot_activity_text: text "đang xem ..." trên Discord presence của bot

Schema key-value đơn giản, không cần per-guild vì cả 2 đều là branding
của 1 bot instance.

Revision ID: 010
Revises: 009
Create Date: 2026-05-28
"""
from alembic import op
import sqlalchemy as sa


revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "system_settings",
        sa.Column("key", sa.String(50), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("updated_by", sa.BigInteger(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    # Seed default values để bot không crash khi đọc lần đầu (bảng rỗng)
    op.execute(
        "INSERT INTO system_settings (key, value, updated_at) VALUES "
        "('system_name', 'Homie Medic', NOW()), "
        "('bot_activity_text', 'Homie Medic | /log upload', NOW())"
    )


def downgrade() -> None:
    op.drop_table("system_settings")
