"""
setup.py — Cog /setup role, /setup channel, /setup timezone
Chỉ DUTY_ADMIN hoặc guild owner mới được dùng
"""
import logging
from discord.ext import commands
from discord import app_commands
import discord
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.base import AsyncSessionLocal
from models.guild import GuildConfig
from models.audit_log import AuditLog, AuditAction
from bot.utils.permissions import require_admin, send_no_permission, DutyRole
from bot.utils.embed_builder import build_success_embed, build_error_embed, build_info_embed
from bot.utils.time_utils import utcnow

logger = logging.getLogger(__name__)

VALID_TIMEZONES = [
    "Asia/Ho_Chi_Minh", "Asia/Bangkok", "Asia/Singapore",
    "Asia/Tokyo", "UTC", "America/New_York", "Europe/London",
]


class SetupCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    setup_group = app_commands.Group(
        name="setup",
        description="Cấu hình bot chấm công cho server (yêu cầu DUTY_ADMIN)"
    )

    @setup_group.command(name="init", description="Khởi tạo bot cho server lần đầu")
    async def setup_init(self, interaction: discord.Interaction):
        """Tạo GuildConfig nếu chưa có — chỉ guild owner mới được chạy lần đầu"""
        await interaction.response.defer(ephemeral=True)

        # Lần đầu setup: chỉ guild owner mới được
        if interaction.user.id != interaction.guild.owner_id:
            async with AsyncSessionLocal() as session:
                if not await require_admin(interaction, session):
                    await send_no_permission(interaction, DutyRole.ADMIN)
                    return

        async with AsyncSessionLocal() as session:
            existing = await session.execute(
                select(GuildConfig).where(GuildConfig.guild_id == interaction.guild_id)
            )
            if existing.scalar_one_or_none():
                await interaction.followup.send(
                    embed=build_info_embed(
                        "Server này đã được cấu hình rồi.\n"
                        "Dùng `/setup role`, `/setup channel` để thay đổi."
                    ),
                    ephemeral=True,
                )
                return

            config = GuildConfig(
                guild_id=interaction.guild_id,
                guild_name=interaction.guild.name,
                role_map={},
                timezone="Asia/Ho_Chi_Minh",
                is_active=True,
                created_at=utcnow(),
                updated_at=utcnow(),
            )
            session.add(config)

            session.add(AuditLog(
                guild_id=interaction.guild_id,
                user_id=interaction.user.id,
                username=str(interaction.user),
                action=AuditAction.SETUP_GUILD,
                detail={"guild_name": interaction.guild.name},
                created_at=utcnow(),
            ))
            await session.commit()

        embed = build_success_embed(
            "✅ Bot đã được khởi tạo cho server!\n\n"
            "**Bước tiếp theo:**\n"
            "1️⃣ `/setup role admin @role` — Gán role DUTY_ADMIN\n"
            "2️⃣ `/setup role mod @role` — Gán role DUTY_MOD\n"
            "3️⃣ `/setup role member @role` — Gán role DUTY_MEMBER\n"
            "4️⃣ `/setup channel #channel` — Chọn channel nhận log\n"
            "5️⃣ `/setup timezone` — Cấu hình timezone",
            title="🎉 Khởi tạo thành công"
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @setup_group.command(name="role", description="Gán Discord role vào quyền DUTY")
    @app_commands.describe(
        quyen="Loại quyền cần gán",
        role="Discord role tương ứng",
    )
    @app_commands.choices(quyen=[
        app_commands.Choice(name="👑 DUTY_ADMIN — Toàn quyền", value="DUTY_ADMIN"),
        app_commands.Choice(name="🛡️ DUTY_MOD — Xem và xuất báo cáo", value="DUTY_MOD"),
        app_commands.Choice(name="👤 DUTY_MEMBER — Chỉ xem log cá nhân", value="DUTY_MEMBER"),
    ])
    async def setup_role(
        self,
        interaction: discord.Interaction,
        quyen: str,
        role: discord.Role,
    ):
        await interaction.response.defer(ephemeral=True)

        async with AsyncSessionLocal() as session:
            if not await require_admin(interaction, session):
                await send_no_permission(interaction, DutyRole.ADMIN)
                return

            config = await _get_or_create_config(session, interaction)
            role_map = dict(config.role_map or {})
            role_map[quyen] = role.id
            config.role_map = role_map
            config.updated_at = utcnow()

            session.add(AuditLog(
                guild_id=interaction.guild_id,
                user_id=interaction.user.id,
                username=str(interaction.user),
                action=AuditAction.CHANGE_ROLE_CONFIG,
                detail={"role_name": quyen, "role_id": role.id, "discord_role": role.name},
                created_at=utcnow(),
            ))
            await session.commit()

        await interaction.followup.send(
            embed=build_success_embed(f"Đã gán **{role.mention}** vào quyền **{quyen}**"),
            ephemeral=True,
        )

    @setup_group.command(name="channel", description="Chọn channel duy nhất nhận log chấm công")
    @app_commands.describe(channel="Channel nhận log (bỏ trống = cho phép tất cả channel)")
    async def setup_channel(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel | None = None,
    ):
        await interaction.response.defer(ephemeral=True)

        async with AsyncSessionLocal() as session:
            if not await require_admin(interaction, session):
                await send_no_permission(interaction, DutyRole.ADMIN)
                return

            config = await _get_or_create_config(session, interaction)
            config.log_channel_id = channel.id if channel else None
            config.updated_at = utcnow()

            session.add(AuditLog(
                guild_id=interaction.guild_id,
                user_id=interaction.user.id,
                username=str(interaction.user),
                action=AuditAction.CHANGE_CHANNEL_CONFIG,
                detail={"channel_id": channel.id if channel else None},
                created_at=utcnow(),
            ))
            await session.commit()

        msg = f"Đã cấu hình channel log: {channel.mention}" if channel else "Đã cho phép log ở tất cả channel"
        await interaction.followup.send(embed=build_success_embed(msg), ephemeral=True)

    @setup_group.command(name="timezone", description="Cấu hình timezone của server")
    @app_commands.describe(tz="Timezone (VD: Asia/Ho_Chi_Minh)")
    @app_commands.choices(tz=[
        app_commands.Choice(name="🇻🇳 Asia/Ho_Chi_Minh (GMT+7)", value="Asia/Ho_Chi_Minh"),
        app_commands.Choice(name="🇹🇭 Asia/Bangkok (GMT+7)", value="Asia/Bangkok"),
        app_commands.Choice(name="🇸🇬 Asia/Singapore (GMT+8)", value="Asia/Singapore"),
        app_commands.Choice(name="🇯🇵 Asia/Tokyo (GMT+9)", value="Asia/Tokyo"),
        app_commands.Choice(name="🌐 UTC", value="UTC"),
    ])
    async def setup_timezone(
        self,
        interaction: discord.Interaction,
        tz: str = "Asia/Ho_Chi_Minh",
    ):
        await interaction.response.defer(ephemeral=True)

        async with AsyncSessionLocal() as session:
            if not await require_admin(interaction, session):
                await send_no_permission(interaction, DutyRole.ADMIN)
                return

            config = await _get_or_create_config(session, interaction)
            config.timezone = tz
            config.updated_at = utcnow()
            await session.commit()

        await interaction.followup.send(
            embed=build_success_embed(f"Đã cập nhật timezone: **{tz}**"),
            ephemeral=True,
        )

    @setup_group.command(name="info", description="Xem cấu hình hiện tại của server")
    async def setup_info(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        async with AsyncSessionLocal() as session:
            if not await require_admin(interaction, session):
                await send_no_permission(interaction, DutyRole.ADMIN)
                return

            result = await session.execute(
                select(GuildConfig).where(GuildConfig.guild_id == interaction.guild_id)
            )
            config = result.scalar_one_or_none()

        if not config:
            await interaction.followup.send(
                embed=build_error_embed("Server chưa được setup. Dùng `/setup init` trước."),
                ephemeral=True,
            )
            return

        embed = build_info_embed("", title="⚙️ Cấu hình server")
        embed.add_field(name="🌏 Timezone", value=config.timezone, inline=True)

        channel_mention = f"<#{config.log_channel_id}>" if config.log_channel_id else "Tất cả channel"
        embed.add_field(name="📢 Channel log", value=channel_mention, inline=True)

        role_map = config.role_map or {}
        roles_text = "\n".join([
            f"**{k}**: <@&{v}>" for k, v in role_map.items()
        ]) or "_Chưa cấu hình role_"
        embed.add_field(name="🎭 Phân quyền", value=roles_text, inline=False)

        await interaction.followup.send(embed=embed, ephemeral=True)


async def _get_or_create_config(session: AsyncSession, interaction: discord.Interaction) -> GuildConfig:
    """Lấy hoặc tạo mới GuildConfig"""
    result = await session.execute(
        select(GuildConfig).where(GuildConfig.guild_id == interaction.guild_id)
    )
    config = result.scalar_one_or_none()
    if config is None:
        config = GuildConfig(
            guild_id=interaction.guild_id,
            guild_name=interaction.guild.name,
            role_map={},
            timezone="Asia/Ho_Chi_Minh",
            is_active=True,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        session.add(config)
    return config


async def setup(bot: commands.Bot):
    await bot.add_cog(SetupCog(bot))
