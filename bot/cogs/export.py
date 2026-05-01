"""
export.py — Cog xử lý /export csv và /export excel
Tạo file → upload Discord ephemeral → tự xóa sau khi gửi
Logic tạo file nằm ở utils/export_utils.py (dùng chung với web)
"""
import io
import logging
from datetime import datetime

import discord
from discord.ext import commands
from discord import app_commands
from sqlalchemy import select

from models.base import AsyncSessionLocal
from models.duty_log import DutyLog
from models.guild import GuildConfig
from models.audit_log import AuditLog, AuditAction
from bot.utils.permissions import require_mod, send_no_permission, DutyRole
from bot.utils.embed_builder import build_error_embed, build_success_embed
from bot.utils.time_utils import get_period_range, get_custom_range, utcnow
from utils.export_utils import logs_to_dataframe, generate_csv_bytes, generate_excel_bytes, sign_file

logger = logging.getLogger(__name__)


async def _query_logs(
    session,
    guild_id: int,
    start: datetime,
    end: datetime,
) -> list[DutyLog]:
    result = await session.execute(
        select(DutyLog)
        .where(DutyLog.guild_id == guild_id)
        .where(DutyLog.started_at >= start)
        .where(DutyLog.started_at <= end)
        .order_by(DutyLog.started_at.asc())
    )
    return result.scalars().all()


class ExportCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    export_group = app_commands.Group(name="export", description="Xuất báo cáo chấm công")

    @export_group.command(name="csv", description="Xuất báo cáo dạng CSV")
    @app_commands.describe(
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
    @app_commands.checks.cooldown(rate=2, per=300.0)
    async def export_csv(
        self,
        interaction: discord.Interaction,
        ky: str = "month",
        tu_ngay: str | None = None,
        den_ngay: str | None = None,
    ):
        await interaction.response.defer(ephemeral=True)

        async with AsyncSessionLocal() as session:
            if not await require_mod(interaction, session):
                await send_no_permission(interaction, DutyRole.MOD)
                return

            tz_result = await session.execute(
                select(GuildConfig.timezone).where(GuildConfig.guild_id == interaction.guild_id)
            )
            guild_tz = tz_result.scalar_one_or_none() or "Asia/Ho_Chi_Minh"

            try:
                if ky == "custom":
                    if not tu_ngay or not den_ngay:
                        await interaction.followup.send(
                            embed=build_error_embed("Nhập cả `tu_ngay` và `den_ngay`."), ephemeral=True
                        )
                        return
                    start, end = get_custom_range(tu_ngay, den_ngay, guild_tz)
                    period_label = f"{tu_ngay} đến {den_ngay}"
                else:
                    start, end = get_period_range(ky, tz_str=guild_tz)
                    period_label = {"day": "Hôm nay", "week": "Tuần này", "month": "Tháng này", "quarter": "Quý này"}[ky]

                logs = await _query_logs(session, interaction.guild_id, start, end)

            except ValueError as e:
                await interaction.followup.send(embed=build_error_embed(str(e)), ephemeral=True)
                return

            # Ghi audit log
            session.add(AuditLog(
                guild_id=interaction.guild_id,
                user_id=interaction.user.id,
                username=str(interaction.user),
                action=AuditAction.EXPORT_CSV,
                detail={"period": ky, "rows": len(logs)},
                created_at=utcnow(),
            ))
            await session.commit()

        if not logs:
            await interaction.followup.send(
                embed=build_error_embed("Không có dữ liệu trong khoảng thời gian này."),
                ephemeral=True,
            )
            return

        df = logs_to_dataframe(logs, interaction.guild.name)
        csv_bytes = generate_csv_bytes(df)
        signature = sign_file(csv_bytes)

        filename = f"duty_log_{interaction.guild_id}_{ky}_{utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
        file = discord.File(io.BytesIO(csv_bytes), filename=filename)

        embed = build_success_embed(
            f"Xuất **{len(logs)} bản ghi** — {period_label}\n"
            f"🔏 HMAC: `{signature[:16]}...`\n"
            f"_File chỉ hiển thị với bạn_"
        )
        await interaction.followup.send(embed=embed, file=file, ephemeral=True)

    @export_group.command(name="excel", description="Xuất báo cáo dạng Excel (.xlsx)")
    @app_commands.describe(
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
    @app_commands.checks.cooldown(rate=2, per=300.0)
    async def export_excel(
        self,
        interaction: discord.Interaction,
        ky: str = "month",
        tu_ngay: str | None = None,
        den_ngay: str | None = None,
    ):
        await interaction.response.defer(ephemeral=True)

        async with AsyncSessionLocal() as session:
            if not await require_mod(interaction, session):
                await send_no_permission(interaction, DutyRole.MOD)
                return

            tz_result = await session.execute(
                select(GuildConfig.timezone).where(GuildConfig.guild_id == interaction.guild_id)
            )
            guild_tz = tz_result.scalar_one_or_none() or "Asia/Ho_Chi_Minh"

            try:
                if ky == "custom":
                    if not tu_ngay or not den_ngay:
                        await interaction.followup.send(
                            embed=build_error_embed("Nhập cả `tu_ngay` và `den_ngay`."), ephemeral=True
                        )
                        return
                    start, end = get_custom_range(tu_ngay, den_ngay, guild_tz)
                    period_label = f"{tu_ngay} đến {den_ngay}"
                else:
                    start, end = get_period_range(ky, tz_str=guild_tz)
                    period_label = {"day": "Hôm nay", "week": "Tuần này", "month": "Tháng này", "quarter": "Quý này"}[ky]

                logs = await _query_logs(session, interaction.guild_id, start, end)

            except ValueError as e:
                await interaction.followup.send(embed=build_error_embed(str(e)), ephemeral=True)
                return

            session.add(AuditLog(
                guild_id=interaction.guild_id,
                user_id=interaction.user.id,
                username=str(interaction.user),
                action=AuditAction.EXPORT_EXCEL,
                detail={"period": ky, "rows": len(logs)},
                created_at=utcnow(),
            ))
            await session.commit()

        if not logs:
            await interaction.followup.send(
                embed=build_error_embed("Không có dữ liệu trong khoảng thời gian này."),
                ephemeral=True,
            )
            return

        df = logs_to_dataframe(logs, interaction.guild.name)
        xlsx_bytes = generate_excel_bytes(df, period_label)
        signature = sign_file(xlsx_bytes)

        filename = f"duty_log_{interaction.guild_id}_{ky}_{utcnow().strftime('%Y%m%d_%H%M%S')}.xlsx"
        file = discord.File(io.BytesIO(xlsx_bytes), filename=filename)

        embed = build_success_embed(
            f"Xuất **{len(logs)} bản ghi** — {period_label}\n"
            f"🔏 HMAC: `{signature[:16]}...`\n"
            f"_File chỉ hiển thị với bạn_"
        )
        await interaction.followup.send(embed=embed, file=file, ephemeral=True)

    @export_csv.error
    @export_excel.error
    async def on_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        """Xử lý cooldown VÀ mọi lỗi khác — không nuốt im lặng"""
        if isinstance(error, app_commands.CommandOnCooldown):
            embed = build_error_embed(f"Export bị giới hạn. Thử lại sau **{error.retry_after:.0f}s**.")
        else:
            logger.error(f"Lỗi /export: {error}", exc_info=error)
            embed = build_error_embed(f"Đã xảy ra lỗi: `{type(error).__name__}: {error}`")

        try:
            if interaction.response.is_done():
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as send_err:
            logger.error(f"Không gửi được error embed: {send_err}", exc_info=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(ExportCog(bot))
