"""Thêm indexes và constraints mới cho duty_logs

- Thêm UniqueConstraint (guild_id, user_id, started_at, ended_at) — chặn race condition duplicate
- Thêm covering index cho ranking query (tránh heap scan)
- Thêm index cho overlap check
- Xóa index cũ ix_duty_logs_guild_user_started (được thay bằng ix_duty_logs_overlap)
- Thêm index expires_at cho token_blacklist cleanup

Revision ID: 002
Revises: 001
Create Date: 2026-05-02
"""
from alembic import op
import sqlalchemy as sa

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── duty_logs: xóa index cũ (superseded) ──
    op.drop_index("ix_duty_logs_guild_user_started", table_name="duty_logs")

    # ── duty_logs: unique constraint chống race condition duplicate ──
    op.create_unique_constraint(
        "uq_duty_log_entry",
        "duty_logs",
        ["guild_id", "user_id", "started_at", "ended_at"],
    )

    # ── duty_logs: covering index cho ranking query ──
    # Giúp query: WHERE guild_id=? AND started_at BETWEEN ? AND ?
    # GROUP BY user_id ORDER BY SUM(duration_minutes)
    # chạy index-only scan, không cần đọc heap
    op.create_index(
        "ix_duty_logs_ranking_cover",
        "duty_logs",
        ["guild_id", "started_at", "user_id", "duration_minutes"],
    )

    # ── duty_logs: index cho overlap check ──
    # Giúp query: WHERE guild_id=? AND user_id=? AND started_at < ? AND ended_at > ?
    op.create_index(
        "ix_duty_logs_overlap",
        "duty_logs",
        ["guild_id", "user_id", "started_at", "ended_at"],
    )

    # ── token_blacklist: index riêng trên expires_at cho cleanup job ──
    op.create_index(
        "ix_token_blacklist_expires",
        "token_blacklist",
        ["expires_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_token_blacklist_expires", table_name="token_blacklist")
    op.drop_index("ix_duty_logs_overlap", table_name="duty_logs")
    op.drop_index("ix_duty_logs_ranking_cover", table_name="duty_logs")
    op.drop_constraint("uq_duty_log_entry", "duty_logs", type_="unique")
    op.create_index(
        "ix_duty_logs_guild_user_started",
        "duty_logs",
        ["guild_id", "user_id", "started_at"],
    )
