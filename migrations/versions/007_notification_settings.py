"""Thêm cột notification_settings vào guild_configs.

Lưu JSON: {remind_register_shift, remind_before_shift, alert_late, alert_burnout, daily_digest}
Admin toggle từ trang Settings → Notifications.

Mặc định khi tạo cột: '{}'::json (rỗng) để tránh issue parser của SQLAlchemy với
JSON containing ':' (bị nhầm thành SQL parameter binding).
Sau đó UPDATE để fill default values cho các row đã có.

Revision ID: 007
Revises: 006
Create Date: 2026-05-16
"""
from alembic import op
import sqlalchemy as sa

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Bước 1: Thêm cột với default JSON rỗng (tránh lỗi parser SQLAlchemy với `:true`)
    op.add_column(
        "guild_configs",
        sa.Column(
            "notification_settings",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'::json"),
        ),
    )

    # Bước 2: Backfill default values bằng raw SQL (PostgreSQL jsonb_build_object)
    # Dùng escape `::text::json` để tránh parser
    op.execute("""
        UPDATE guild_configs
        SET notification_settings = jsonb_build_object(
            'remind_register_shift', true,
            'remind_before_shift', true,
            'alert_late', true,
            'alert_burnout', true,
            'daily_digest', false
        )::json
        WHERE notification_settings::text = '{}'
    """)


def downgrade() -> None:
    op.drop_column("guild_configs", "notification_settings")
