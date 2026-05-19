"""Functional index cho username-lock query trong duty_logs

bot/cogs/log_duty.py _save_duty_log dùng:
    WHERE guild_id = ?
      AND lower(trim(username)) = ?

Không có functional index → seq scan toàn bảng duty_logs với guild lớn.
Tạo index `(guild_id, lower(trim(username)))` để query này nhanh ngay cả
ở 100k+ rows.

Revision ID: 008
Revises: 007
Create Date: 2026-05-19
"""
from alembic import op


revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_duty_logs_guild_username_lower "
        "ON duty_logs (guild_id, lower(trim(username)))"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_duty_logs_guild_username_lower")
