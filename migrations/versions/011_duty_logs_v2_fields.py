"""Thêm 2 cột optional cho định dạng LOG DUTY v2 (CAPY TOWN LOGS):

- discord_handle: text từ field "Discord:" hoặc "Tên discord:" (vd "@Habibi")
- exit_reason: text từ field "Lý do rời:" (vd "Server timeout", "Game crashed")

Cả 2 nullable vì log V1 cũ không có; log V2 cũng có thể không có
exit_reason. Không tạo index — query không filter theo 2 cột này.

Revision ID: 011
Revises: 010
Create Date: 2026-05-31
"""
from alembic import op
import sqlalchemy as sa


revision = "011"
down_revision = "010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "duty_logs",
        sa.Column("discord_handle", sa.String(100), nullable=True),
    )
    op.add_column(
        "duty_logs",
        sa.Column("exit_reason", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("duty_logs", "exit_reason")
    op.drop_column("duty_logs", "discord_handle")
