"""Thêm cột cleanup_role_ids vào guild_configs

- cleanup_role_ids: list role IDs sẽ tự động bị gỡ khi /xinoutnganh duyệt hoặc /sathai

Revision ID: 004
Revises: 003
Create Date: 2026-05-04
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "guild_configs",
        sa.Column(
            "cleanup_role_ids",
            postgresql.JSON(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
    )


def downgrade() -> None:
    op.drop_column("guild_configs", "cleanup_role_ids")
