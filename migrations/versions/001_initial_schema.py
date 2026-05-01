"""Initial schema — tạo tất cả bảng lần đầu

Revision ID: 001
Revises:
Create Date: 2026-04-27
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── guild_configs ──
    op.create_table(
        "guild_configs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("guild_name", sa.String(100), nullable=False),
        sa.Column("log_channel_id", sa.BigInteger(), nullable=True),
        sa.Column("role_map", postgresql.JSON(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("timezone", sa.String(50), nullable=False, server_default="Asia/Ho_Chi_Minh"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("guild_id"),
    )
    op.create_index("ix_guild_configs_guild_id", "guild_configs", ["guild_id"])

    # ── users ──
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("discord_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(100), nullable=False),
        sa.Column("discriminator", sa.String(10), nullable=True),
        sa.Column("avatar_url", sa.String(500), nullable=True),
        sa.Column("totp_secret_encrypted", sa.Text(), nullable=True),
        sa.Column("is_2fa_enabled", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("failed_login_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_ip", sa.String(45), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("discord_id"),
    )
    op.create_index("ix_users_discord_id", "users", ["discord_id"])

    # ── duty_logs ──
    op.create_table(
        "duty_logs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(100), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column("source", sa.String(20), nullable=False, server_default="forward"),
        sa.Column("source_message_id", sa.BigInteger(), nullable=True),
        sa.Column("submitted_by", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_message_id"),
    )
    op.create_index("ix_duty_logs_guild_started",       "duty_logs", ["guild_id", "started_at"])
    op.create_index("ix_duty_logs_guild_user",          "duty_logs", ["guild_id", "user_id"])
    op.create_index("ix_duty_logs_guild_user_started",  "duty_logs", ["guild_id", "user_id", "started_at"])

    # ── audit_logs ──
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(100), nullable=False),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("detail", postgresql.JSON(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_logs_guild_id",       "audit_logs", ["guild_id"])
    op.create_index("ix_audit_logs_created_at",     "audit_logs", ["created_at"])
    op.create_index("ix_audit_logs_guild_action",   "audit_logs", ["guild_id", "action"])
    op.create_index("ix_audit_logs_user_created",   "audit_logs", ["user_id", "created_at"])

    # ── token_blacklist ──
    op.create_table(
        "token_blacklist",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("jti", sa.String(64), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("blacklisted_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("jti"),
    )
    op.create_index("ix_token_blacklist_jti",           "token_blacklist", ["jti"])
    op.create_index("ix_blacklist_user_exp",            "token_blacklist", ["user_id", "expires_at"])


def downgrade() -> None:
    op.drop_table("token_blacklist")
    op.drop_table("audit_logs")
    op.drop_table("duty_logs")
    op.drop_table("users")
    op.drop_table("guild_configs")
