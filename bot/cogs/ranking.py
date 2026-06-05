"""
ranking.py — Cog xử lý /top và /bottom
Bảng xếp hạng trực nhiều/ít nhất theo ngày/tuần/tháng/quý
"""
import logging
from discord.ext import commands
from discord import app_commands
import discord
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from models.base import AsyncSessionLocal
from models.duty_log import DutyLog
from models.guild import GuildConfig
from bot.utils.permissions import require_mod, send_no_permission, DutyRole
from bot.utils.embed_builder import build_top_embed, build_error_embed
from bot.utils.time_utils import get_period_range, get_custom_range, make_period_choices

logger = logging.getLogger(__name__)


async def _get_ranking(
    session: AsyncSession,
    guild_id: int,
    start: object,
    end: object,
    order: str = "desc",
    limit: int = 10,
) -> list[dict]:
    """
    Query top/bottom theo khoảng thời gian. Gộp theo discord_user_id qua
    shared helper — tránh duplicate khi user có nhiều tên ingame.
    order: "desc" = nhiều nhất trước, "asc" = ít nhất trước
    """
    from utils.ranking_utils import aggregate_ranking
    rows = await aggregate_ranking(
        session, guild_id=guild_id, start=start, end=end,
        order=order, limit=limit,
    )
    return [
        {
            "user_id": r.user_id,
            "username": r.display_name,
            "total_minutes": r.total_minutes,
            "session_count": r.sessions,
        }
        for r in rows
    ]


async def _get_guild_tz(session: AsyncSession, guild_id: int) -> str:
    result = await session.execute(
        select(GuildConfig.timezone).where(GuildConfig.guild_id == guild_id)
    )
    tz = result.scalar_one_or_none()
    return tz or "Asia/Ho_Chi_Minh"


class RankingCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="top", description="Bảng xếp hạng trực NHIỀU nhất")
    @app_commands.describe(
        ky="Kỳ thống kê",
        tu_ngay="Từ ngày (DD/MM/YYYY) — nếu chọn 'tuy_chinh'",
        den_ngay="Đến ngày (DD/MM/YYYY) — nếu chọn 'tuy_chinh'",
    )
    @app_commands.choices(ky=make_period_choices())
    @app_commands.checks.cooldown(rate=10, per=60.0)
    async def top(
        self,
        interaction: discord.Interaction,
        ky: str = "week",
        tu_ngay: str | None = None,
        den_ngay: str | None = None,
    ):
        # Check quyền TRƯỚC khi defer — tránh treo "thinking..." nếu denied
        async with AsyncSessionLocal() as session:
            if not await require_mod(interaction, session):
                await send_no_permission(interaction, DutyRole.MOD)
                return

        await interaction.response.defer()

        async with AsyncSessionLocal() as session:
            guild_tz = await _get_guild_tz(session, interaction.guild_id)

            try:
                if ky == "custom":
                    if not tu_ngay or not den_ngay:
                        await interaction.followup.send(
                            embed=build_error_embed("Vui lòng nhập cả `tu_ngay` và `den_ngay` khi chọn tùy chỉnh."),
                            ephemeral=True,
                        )
                        return
                    start, end = get_custom_range(tu_ngay, den_ngay, guild_tz)
                    date_range = (tu_ngay, den_ngay)
                else:
                    start, end = get_period_range(ky, tz_str=guild_tz)
                    date_range = None

                rankings = await _get_ranking(session, interaction.guild_id, start, end, order="desc")

            except ValueError as e:
                await interaction.followup.send(embed=build_error_embed(str(e)), ephemeral=True)
                return

        embed = build_top_embed(
            rankings, ky, mode="top",
            guild_name=interaction.guild.name,
            date_range=date_range,
        )
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="bottom", description="Bảng xếp hạng trực ÍT nhất")
    @app_commands.describe(
        ky="Kỳ thống kê",
        tu_ngay="Từ ngày (DD/MM/YYYY) — nếu chọn 'tuy_chinh'",
        den_ngay="Đến ngày (DD/MM/YYYY) — nếu chọn 'tuy_chinh'",
    )
    @app_commands.choices(ky=make_period_choices())
    @app_commands.checks.cooldown(rate=10, per=60.0)
    async def bottom(
        self,
        interaction: discord.Interaction,
        ky: str = "week",
        tu_ngay: str | None = None,
        den_ngay: str | None = None,
    ):
        async with AsyncSessionLocal() as session:
            if not await require_mod(interaction, session):
                await send_no_permission(interaction, DutyRole.MOD)
                return

        await interaction.response.defer()

        async with AsyncSessionLocal() as session:
            guild_tz = await _get_guild_tz(session, interaction.guild_id)

            try:
                if ky == "custom":
                    if not tu_ngay or not den_ngay:
                        await interaction.followup.send(
                            embed=build_error_embed("Vui lòng nhập cả `tu_ngay` và `den_ngay` khi chọn tùy chỉnh."),
                            ephemeral=True,
                        )
                        return
                    start, end = get_custom_range(tu_ngay, den_ngay, guild_tz)
                    date_range = (tu_ngay, den_ngay)
                else:
                    start, end = get_period_range(ky, tz_str=guild_tz)
                    date_range = None

                rankings = await _get_ranking(session, interaction.guild_id, start, end, order="asc")

            except ValueError as e:
                await interaction.followup.send(embed=build_error_embed(str(e)), ephemeral=True)
                return

        embed = build_top_embed(
            rankings, ky, mode="bottom",
            guild_name=interaction.guild.name,
            date_range=date_range,
        )
        await interaction.followup.send(embed=embed)

    @top.error
    @bottom.error
    async def on_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        """Xử lý cooldown VÀ mọi lỗi khác — không được nuốt im lặng"""
        if isinstance(error, app_commands.CommandOnCooldown):
            embed = build_error_embed(f"Thử lại sau **{error.retry_after:.0f}s**.")
        else:
            # Log đầy đủ traceback để debug
            logger.error(f"Lỗi /{interaction.command.name if interaction.command else '?'}: {error}", exc_info=error)
            embed = build_error_embed(f"Đã xảy ra lỗi: `{type(error).__name__}: {error}`")

        try:
            if interaction.response.is_done():
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as send_err:
            logger.error(f"Không gửi được error embed: {send_err}", exc_info=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(RankingCog(bot))
