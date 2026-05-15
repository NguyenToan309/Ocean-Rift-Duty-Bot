"""Tạo tables cho lịch trực + xin nghỉ + onboarding

- member_schedules: lịch trực cố định hàng tuần
- schedule_reminders: track nhắc đã gửi (chống dup)
- onboarding_logs: track DM onboarding (cooldown 24h)
- leave_requests: đơn xin nghỉ + xin out ngành
- duty_logs: thêm cột schedule_id (auto-link)
- guild_configs: thêm 4 channel ID + medic_role_id + default_remind_offsets

Revision ID: 003
Revises: 002
Create Date: 2026-05-04
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── member_schedules ──
    op.create_table(
        "member_schedules",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("weekday", sa.SmallInteger(), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("end_time", sa.Time(), nullable=False),
        sa.Column("crosses_midnight", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("custom_remind_offsets", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "guild_id", "user_id", "weekday", "start_time",
            name="uq_member_schedule_slot",
        ),
    )
    op.create_index("ix_schedules_guild_user", "member_schedules", ["guild_id", "user_id"])
    op.create_index("ix_schedules_guild_weekday", "member_schedules", ["guild_id", "weekday"])

    # ── schedule_reminders ──
    op.create_table(
        "schedule_reminders",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("schedule_id", sa.BigInteger(), nullable=False),
        sa.Column("occurrence_date", sa.Date(), nullable=False),
        sa.Column("reminder_type", sa.String(30), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "schedule_id", "occurrence_date", "reminder_type",
            name="uq_schedule_reminder_unique",
        ),
        sa.ForeignKeyConstraint(
            ["schedule_id"], ["member_schedules.id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_schedule_reminders_date", "schedule_reminders", ["occurrence_date"])

    # ── onboarding_logs ──
    op.create_table(
        "onboarding_logs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("last_reminded_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("guild_id", "user_id", name="uq_onboarding_user"),
    )
    op.create_index("ix_onboarding_last_reminded", "onboarding_logs", ["last_reminded_at"])

    # ── leave_requests ──
    op.create_table(
        "leave_requests",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(100), nullable=False),
        sa.Column("request_type", sa.String(20), nullable=False, server_default="leave"),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("vote_message_id", sa.BigInteger(), nullable=True),
        sa.Column("vote_channel_id", sa.BigInteger(), nullable=True),
        sa.Column("decided_by", sa.BigInteger(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column("detail", postgresql.JSON(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("vote_message_id", name="uq_leave_vote_msg"),
    )
    op.create_index("ix_leave_guild_user", "leave_requests", ["guild_id", "user_id"])
    op.create_index("ix_leave_guild_status", "leave_requests", ["guild_id", "status"])
    op.create_index("ix_leave_guild_dates", "leave_requests", ["guild_id", "start_date", "end_date"])

    # ── duty_logs: thêm cột schedule_id ──
    op.add_column(
        "duty_logs",
        sa.Column("schedule_id", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        "fk_duty_logs_schedule",
        "duty_logs", "member_schedules",
        ["schedule_id"], ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_duty_logs_schedule", "duty_logs", ["schedule_id"])

    # ── guild_configs: thêm 4 channel + medic role + remind defaults ──
    op.add_column("guild_configs", sa.Column("schedule_channel_id", sa.BigInteger(), nullable=True))
    op.add_column("guild_configs", sa.Column("remind_channel_id", sa.BigInteger(), nullable=True))
    op.add_column("guild_configs", sa.Column("leave_channel_id", sa.BigInteger(), nullable=True))
    op.add_column("guild_configs", sa.Column("staff_channel_id", sa.BigInteger(), nullable=True))
    op.add_column("guild_configs", sa.Column("medic_role_id", sa.BigInteger(), nullable=True))
    op.add_column(
        "guild_configs",
        sa.Column(
            "default_remind_offsets",
            postgresql.JSON(astext_type=sa.Text()),
            nullable=False,
            server_default='[60, 30, 5]',
        ),
    )


def downgrade() -> None:
    op.drop_column("guild_configs", "default_remind_offsets")
    op.drop_column("guild_configs", "medic_role_id")
    op.drop_column("guild_configs", "staff_channel_id")
    op.drop_column("guild_configs", "leave_channel_id")
    op.drop_column("guild_configs", "remind_channel_id")
    op.drop_column("guild_configs", "schedule_channel_id")

    op.drop_index("ix_duty_logs_schedule", table_name="duty_logs")
    op.drop_constraint("fk_duty_logs_schedule", "duty_logs", type_="foreignkey")
    op.drop_column("duty_logs", "schedule_id")

    op.drop_table("leave_requests")
    op.drop_table("onboarding_logs")
    op.drop_table("schedule_reminders")
    op.drop_table("member_schedules")
