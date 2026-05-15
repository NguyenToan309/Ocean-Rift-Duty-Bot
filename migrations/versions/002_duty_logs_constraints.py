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

    # ── DEDUP: dọn dữ liệu trùng trước khi tạo UniqueConstraint ──
    # Trước migration này, code chỉ check duplicate ở application level
    # (race condition có thể tạo bản ghi trùng). Cần xoá duplicate trước khi
    # tạo unique constraint, nếu không sẽ vi phạm và migration fail.
    #
    # Strategy: với mỗi nhóm (guild, user, started_at, ended_at) trùng,
    # giữ lại record có id NHỎ NHẤT (record cũ nhất, đã có audit log),
    # xoá các record sau (id lớn hơn).
    conn = op.get_bind()
    result = conn.execute(sa.text("""
        SELECT COUNT(*) FROM (
            SELECT 1 FROM duty_logs
            GROUP BY guild_id, user_id, started_at, ended_at
            HAVING COUNT(*) > 1
        ) t
    """))
    dup_groups = result.scalar() or 0
    if dup_groups > 0:
        # Đếm số record sẽ bị xoá
        result = conn.execute(sa.text("""
            SELECT COUNT(*) - COUNT(DISTINCT (guild_id, user_id, started_at, ended_at))
            FROM duty_logs
        """))
        dup_rows = result.scalar() or 0
        print(f"[migration 002] Phát hiện {dup_groups} nhóm trùng, "
              f"sẽ xoá {dup_rows} bản ghi duplicate (giữ lại id nhỏ nhất mỗi nhóm)...")
        conn.execute(sa.text("""
            DELETE FROM duty_logs a
            USING duty_logs b
            WHERE a.id > b.id
              AND a.guild_id   = b.guild_id
              AND a.user_id    = b.user_id
              AND a.started_at = b.started_at
              AND a.ended_at   = b.ended_at
        """))
        print(f"[migration 002] Đã xoá {dup_rows} bản ghi trùng. Tiếp tục tạo constraint...")

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
