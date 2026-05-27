"""Đổi UNIQUE thường → partial unique index WHERE column IS NOT NULL

Áp dụng cho:
- duty_logs.source_message_id (constraint auto-named: duty_logs_source_message_id_key)
- leave_requests.vote_message_id (constraint: uq_leave_vote_msg)

Lý do:
PostgreSQL UNIQUE trên cột nullable đã cho phép nhiều NULL (NULL ≠ NULL theo
spec) nên hành vi dedup hiện tại đúng. Tuy nhiên index full chứa cả NULL rows
nên tốn space + chậm hơn nhẹ. Partial index `WHERE column IS NOT NULL` chỉ
lưu non-null entries, kết quả y hệt về dedup nhưng index nhỏ hơn — đặc biệt
có lợi cho leave_requests.vote_message_id (nhiều row NULL sau khi xử lý).

Revision ID: 009
Revises: 008
Create Date: 2026-05-28
"""
from alembic import op


revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── duty_logs.source_message_id ──
    op.drop_constraint(
        "duty_logs_source_message_id_key",
        "duty_logs",
        type_="unique",
    )
    op.execute(
        "CREATE UNIQUE INDEX ix_duty_logs_source_msg_unique "
        "ON duty_logs (source_message_id) "
        "WHERE source_message_id IS NOT NULL"
    )

    # ── leave_requests.vote_message_id ──
    op.drop_constraint(
        "uq_leave_vote_msg",
        "leave_requests",
        type_="unique",
    )
    op.execute(
        "CREATE UNIQUE INDEX ix_leave_vote_msg_unique "
        "ON leave_requests (vote_message_id) "
        "WHERE vote_message_id IS NOT NULL"
    )


def downgrade() -> None:
    # ── leave_requests.vote_message_id ──
    op.drop_index("ix_leave_vote_msg_unique", table_name="leave_requests")
    op.create_unique_constraint(
        "uq_leave_vote_msg",
        "leave_requests",
        ["vote_message_id"],
    )

    # ── duty_logs.source_message_id ──
    op.drop_index("ix_duty_logs_source_msg_unique", table_name="duty_logs")
    op.create_unique_constraint(
        "duty_logs_source_message_id_key",
        "duty_logs",
        ["source_message_id"],
    )
