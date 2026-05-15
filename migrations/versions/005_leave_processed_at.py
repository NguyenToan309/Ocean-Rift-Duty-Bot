"""Thêm cột processed_at vào leave_requests

Mục đích: bot dùng để biết đơn nào web đã duyệt nhưng chưa thực hiện
DM/gỡ role/cleanup. Bot scan periodic, xử lý xong set processed_at.

Revision ID: 005
Revises: 004
Create Date: 2026-05-04
"""
from alembic import op
import sqlalchemy as sa

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "leave_requests",
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Index để bot scan nhanh: WHERE decided_at IS NOT NULL AND processed_at IS NULL
    op.create_index(
        "ix_leave_pending_process",
        "leave_requests",
        ["decided_at", "processed_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_leave_pending_process", table_name="leave_requests")
    op.drop_column("leave_requests", "processed_at")
