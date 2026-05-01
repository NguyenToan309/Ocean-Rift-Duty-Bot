"""
stats.py — Cog xử lý /stats
Thống kê cá nhân: tổng giờ, số ca, trung bình, xếp hạng
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
from bot.utils.permissions import require_member, require_mod, send_no_permission, DutyRole
from bot.utils.embed_builder import build_stats_embed, build_error_embed
from bot.utils.time_utils import get_period_range, get_custom_range

logger = logging.getLogger(__name__)


async def _get_user_stats(
    session: AsyncSession,
    guild_id: int,
    user_id: int,
    start: object,
    end: object,
) -> dict:
    """
    Tính thống kê cho một user trong khoảng thời gian.
    Trả về: total_minutes, session_count, avg_minutes, rank
    """
    # Thống kê của user
    user_result = await session.execute(
        select(
            func.sum(DutyLog.duration_minutes).label("total"),
            func.count(DutyLog.id).label("count"),
        )
        .where(DutyLog.guild_id == guild_id)
        .where(DutyLog.user_id == user_id)
        .where(DutyLog.started_at >= start)
        .where(DutyLog.started_at <= end)
    )
    row = user_result.first()
    total = row.total or 0
    count = row.count or 0

    # Xếp hạng: đếm bao nhiêu người có tổng phút > user này
    rank_result = await session.execute(
        select(func.count())
        .select_from(
            select(
                DutyLog.user_id,
                func.sum(DutyLog.duration_minutes).label("total_minutes"),
            )
            .where(DutyLog.guild_id == guild_id)
            .where(DutyLog.started_at >= start)
            .where(DutyLog.started_at <= end)
            .group_by(DutyLog.user_id)
            .having(func.sum(DutyLog.duration_minutes) > total)
            .subquery()
        )
    )
    rank = (rank_result.scalar() or 0) + 1  # +1 vì rank bắt đầu từ 1

    return {
        "total_minutes": total,
        "session_count": count,
        "avg_minutes": total / count if count > 0 else 0,
        "rank": rank if total > 0 else None,
    }


class StatsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="stats", description="Xem thống kê chấm công cá nhân")
    @app_commands.describe(
        thanh_vien="Xem thống kê của thành viên khác (cần quyền MOD+)",
        ky="Kỳ thống kê",
        tu_ngay="Từ ngày (DD/MM/YYYY) — nếu chọn 'tuy_chinh'",
        den_ngay="Đến ngày (DD/MM/YYYY) — nếu chọn 'tuy_chinh'",
    )
    @app_commands.choices(ky=[
        app_commands.Choice(name="📅 Hôm nay", value="day"),
        app_commands.Choice(name="📆 Tuần này", value="week"),
        app_commands.Choice(name="🗓️ Tháng này", value="month"),
        app_commands.Choice(name="📊 Quý này", value="quarter"),
        app_commands.Choice(name="🔧 Tùy chỉnh ngày", value="custom"),
    ])
    @app_commands.checks.cooldown(rate=10, per=60.0)
    async def stats(
        self,
        interaction: discord.Interaction,
        thanh_vien: discord.Member | None = None,
        ky: str = "month",
        tu_ngay: str | None = None,
        den_ngay: str | None = None,
    ):
        await interaction.response.defer(ephemeral=True)

        async with AsyncSessionLocal() as session:
            # Xem stats người khác cần quyền MOD
            if thanh_vien and thanh_vien.id != interaction.user.id:
                if not await require_mod(interaction, session):
                    await send_no_permission(interaction, DutyRole.MOD)
                    return
            else:
                if not await require_member(interaction, session):
                    await send_no_permission(interaction, DutyRole.MEMBER)
                    return

            target = thanh_vien or interaction.user

            # Lấy timezone của guild
            tz_result = await session.execute(
                select(GuildConfig.timezone).where(GuildConfig.guild_id == interaction.guild_id)
            )
            guild_tz = tz_result.scalar_one_or_none() or "Asia/Ho_Chi_Minh"

            try:
                if ky == "custom":
                    if not tu_ngay or not den_ngay:
                        await interaction.followup.send(
                            embed=build_error_embed("Vui lòng nhập cả `tu_ngay` và `den_ngay`."),
                            ephemeral=True,
                        )
                        return
                    start, end = get_custom_range(tu_ngay, den_ngay, guild_tz)
                else:
                    start, end = get_period_range(ky, tz_str=guild_tz)

                user_stats = await _get_user_stats(session, interaction.guild_id, target.id, start, end)

            except ValueError as e:
                await interaction.followup.send(embed=build_error_embed(str(e)), ephemeral=True)
                return

        embed = build_stats_embed(
            username=target.display_name,
            stats=user_stats,
            period=ky,
            guild_name=interaction.guild.name,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @stats.error
    async def on_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        """Xử lý cooldown VÀ mọi lỗi khác — không nuốt im lặng"""
        if isinstance(error, app_commands.CommandOnCooldown):
            embed = build_error_embed(f"Thử lại sau **{error.retry_after:.0f}s**.")
        else:
            logger.error(f"Lỗi /stats: {error}", exc_info=error)
            embed = build_error_embed(f"Đã xảy ra lỗi: `{type(error).__name__}: {error}`")

        try:
            if interaction.response.is_done():
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as send_err:
            logger.error(f"Không gửi được error embed: {send_err}", exc_info=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(StatsCog(bot))
