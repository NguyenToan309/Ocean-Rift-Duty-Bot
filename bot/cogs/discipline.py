"""
discipline.py — Cog kỷ luật + sa thải nhân viên.

- /kyluat @member <mức-độ>: mở modal nhập lý do + thời hạn (chỉ Mod+)
- /sathai @member <lý-do>: sa thải ngay (chỉ Admin+) — auto cleanup giống /xinoutnganh
"""
from __future__ import annotations
import logging
import re
from datetime import datetime, timedelta

import discord
from discord.ext import commands
from discord import app_commands
from sqlalchemy import select, func

from models.base import AsyncSessionLocal
from models.guild import GuildConfig
from models.audit_log import AuditLog, AuditAction
from bot.utils.permissions import (
    require_admin, require_mod, send_no_permission, DutyRole,
)
from bot.utils.embed_builder import (
    build_error_embed, build_success_embed,
    COLOR_ERROR, COLOR_WARNING, SUPPORT_FOOTER,
)
from bot.utils.time_utils import utcnow

logger = logging.getLogger(__name__)


# ─── Discipline levels ───────────────────────────────────────────────────────

DISCIPLINE_LEVELS = {
    "canh_cao":    {"label": "⚠️ Cảnh cáo",    "color": 0xFEE75C, "weight": 1},
    "khien_trach": {"label": "🟠 Khiển trách",  "color": 0xED9121, "weight": 2},
    "phat":        {"label": "🔴 Phạt nặng",    "color": 0xED4245, "weight": 3},
}


# ─── Parse "thời hạn" linh hoạt ──────────────────────────────────────────────

_DURATION_PAT = re.compile(r"^\s*(\d+)\s*(ngay|ngày|day|days|tuan|tuần|week|weeks|thang|tháng|month|months)\s*$", re.I)


def _parse_duration(s: str) -> tuple[str, datetime | None]:
    """
    Parse '7 ngày', '2 tuần', '1 tháng', 'vĩnh viễn' → (label, end_date_utc | None)
    Trả về None khi vĩnh viễn / không xác định.
    """
    s_clean = s.strip().lower()
    if not s_clean:
        return ("Không xác định", None)
    if s_clean in ("vĩnh viễn", "vinh vien", "permanent", "forever", "vv"):
        return ("Vĩnh viễn", None)

    m = _DURATION_PAT.match(s_clean)
    if m:
        n = int(m.group(1))
        unit_raw = m.group(2)
        if unit_raw in ("ngay", "ngày", "day", "days"):
            return (f"{n} ngày", utcnow() + timedelta(days=n))
        if unit_raw in ("tuan", "tuần", "week", "weeks"):
            return (f"{n} tuần", utcnow() + timedelta(weeks=n))
        if unit_raw in ("thang", "tháng", "month", "months"):
            return (f"{n} tháng", utcnow() + timedelta(days=n * 30))

    # Free-form text → giữ nguyên label, không tính end date
    return (s.strip()[:50], None)


# ─── Modal /kyluat ────────────────────────────────────────────────────────────

class KyLuatModal(discord.ui.Modal, title="📋 Kỷ luật nhân viên"):
    """
    Modal nhập đầy đủ thông tin kỷ luật:
      - Lý do (multiline)
      - Thời hạn (vd: "7 ngày", "2 tuần", "1 tháng", "vĩnh viễn")
      - Ghi chú thêm (optional)
    """
    ly_do = discord.ui.TextInput(
        label="Lý do kỷ luật",
        placeholder="Mô tả chi tiết hành vi vi phạm...",
        required=True,
        style=discord.TextStyle.paragraph,
        max_length=900,
    )
    thoi_han = discord.ui.TextInput(
        label="Thời hạn (vd: 7 ngày / 2 tuần / vĩnh viễn)",
        placeholder="7 ngày",
        required=True,
        max_length=50,
    )
    ghi_chu = discord.ui.TextInput(
        label="Ghi chú thêm (optional)",
        placeholder="VD: Lưu ý đặc biệt cho staff khác...",
        required=False,
        style=discord.TextStyle.paragraph,
        max_length=400,
    )

    def __init__(self, cog: "DisciplineCog", target: discord.Member, level_key: str):
        super().__init__()
        self.cog = cog
        self.target = target
        self.level_key = level_key

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await self.cog._handle_kyluat_submit(
            interaction,
            target=self.target,
            level_key=self.level_key,
            ly_do=self.ly_do.value.strip(),
            thoi_han=self.thoi_han.value.strip(),
            ghi_chu=(self.ghi_chu.value or "").strip(),
        )


# ─── Cog ──────────────────────────────────────────────────────────────────────

class DisciplineCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ─── /kyluat ────────────────────────────────────────────────────────────

    @app_commands.command(name="kyluat", description="Kỷ luật / cảnh cáo nhân viên (chỉ Mod+)")
    @app_commands.describe(
        thanh_vien="Nhân viên bị kỷ luật",
        muc_do="Mức độ kỷ luật",
    )
    @app_commands.choices(muc_do=[
        app_commands.Choice(name="⚠️ Cảnh cáo (lần 1)",   value="canh_cao"),
        app_commands.Choice(name="🟠 Khiển trách (lần 2)", value="khien_trach"),
        app_commands.Choice(name="🔴 Phạt nặng (lần 3)",   value="phat"),
    ])
    @app_commands.checks.cooldown(rate=10, per=60.0)
    async def kyluat(
        self,
        interaction: discord.Interaction,
        thanh_vien: discord.Member,
        muc_do: str,
    ):
        """Mở modal để nhập đầy đủ lý do + thời hạn"""
        # Quick guards trước khi mở modal
        if thanh_vien.bot:
            await interaction.response.send_message(
                embed=build_error_embed("Không thể kỷ luật bot."), ephemeral=True
            )
            return
        if thanh_vien.id == interaction.user.id:
            await interaction.response.send_message(
                embed=build_error_embed("Không thể tự kỷ luật chính mình."), ephemeral=True
            )
            return
        if thanh_vien.id == interaction.guild.owner_id:
            await interaction.response.send_message(
                embed=build_error_embed("Không thể kỷ luật Owner server."), ephemeral=True
            )
            return

        # Quyền: phải là Mod+
        async with AsyncSessionLocal() as session:
            if not await require_mod(interaction, session):
                await send_no_permission(interaction, DutyRole.MOD)
                return

        await interaction.response.send_modal(KyLuatModal(self, thanh_vien, muc_do))

    async def _handle_kyluat_submit(
        self,
        interaction: discord.Interaction,
        target: discord.Member,
        level_key: str,
        ly_do: str,
        thoi_han: str,
        ghi_chu: str,
    ):
        """Logic sau khi modal submit"""
        level_info = DISCIPLINE_LEVELS.get(level_key, DISCIPLINE_LEVELS["canh_cao"])
        duration_label, duration_end = _parse_duration(thoi_han)

        async with AsyncSessionLocal() as session:
            # Đếm số lần kỷ luật trước (PostgreSQL JSON path filter)
            # detail->>'for_user' = '<id>' — efficient hơn load all rows + len()
            count_row = await session.execute(
                select(func.count(AuditLog.id))
                .where(AuditLog.guild_id == interaction.guild_id)
                .where(AuditLog.action == AuditAction.DISCIPLINE)
                .where(AuditLog.detail["for_user"].astext == str(target.id))
            )
            previous_count = int(count_row.scalar() or 0)

            session.add(AuditLog(
                guild_id=interaction.guild_id,
                user_id=interaction.user.id,
                username=str(interaction.user),
                action=AuditAction.DISCIPLINE,
                detail={
                    "for_user": str(target.id),
                    "for_username": target.display_name,
                    "level": level_key,
                    "level_label": level_info["label"],
                    "reason": ly_do[:900],
                    "duration_label": duration_label,
                    "duration_end_utc": duration_end.isoformat() if duration_end else None,
                    "note": ghi_chu[:400] if ghi_chu else None,
                    "previous_count": previous_count,
                },
                created_at=utcnow(),
            ))
            await session.commit()

            cfg = await _get_config(session, interaction.guild_id)

        # Build embed
        embed = discord.Embed(
            title=f"{level_info['label']} — Đã ghi nhận kỷ luật",
            description=(
                f"**{discord.utils.escape_markdown(target.display_name)}** "
                f"đã bị kỷ luật bởi {interaction.user.mention}."
            ),
            color=level_info["color"],
        )
        embed.add_field(name="📋 Mức độ", value=level_info["label"], inline=True)
        embed.add_field(name="⏳ Thời hạn", value=f"**{duration_label}**", inline=True)
        if duration_end:
            embed.add_field(name="📅 Hết hạn", value=f"`{duration_end.strftime('%H:%M %d/%m/%Y')} UTC`", inline=True)
        else:
            embed.add_field(name="​", value="​", inline=True)  # spacer
        embed.add_field(name="📝 Lý do", value=discord.utils.escape_markdown(ly_do)[:1024], inline=False)
        if ghi_chu:
            embed.add_field(name="🗒️ Ghi chú nội bộ (chỉ staff thấy)", value=discord.utils.escape_markdown(ghi_chu)[:1024], inline=False)
        if previous_count > 0:
            embed.add_field(
                name="📚 Lịch sử",
                value=f"Đây là **lần kỷ luật thứ {previous_count + 1}** của thành viên.",
                inline=False,
            )
        embed.set_footer(text=f"{SUPPORT_FOOTER} • {utcnow().strftime('%H:%M %d/%m/%Y')} UTC")

        await interaction.followup.send(embed=embed, ephemeral=True)

        # DM thành viên — KHÔNG hiển thị "ghi chú nội bộ"
        try:
            dm_embed = discord.Embed(
                title=f"{level_info['label']} — Bạn vừa bị kỷ luật",
                description=(
                    f"Bạn vừa bị **{level_info['label']}** trong server "
                    f"**{interaction.guild.name}**."
                ),
                color=level_info["color"],
            )
            dm_embed.add_field(name="⏳ Thời hạn", value=duration_label, inline=True)
            if duration_end:
                dm_embed.add_field(name="📅 Hết hạn", value=f"`{duration_end.strftime('%H:%M %d/%m/%Y')} UTC`", inline=True)
            dm_embed.add_field(name="📝 Lý do", value=ly_do[:1024], inline=False)
            if previous_count > 0:
                dm_embed.add_field(
                    name="⚠️ Cảnh báo",
                    value=(
                        f"Đây là **lần thứ {previous_count + 1}** bạn bị kỷ luật. "
                        "Vui lòng cải thiện hành vi trước khi bị xử lý nặng hơn (sa thải)."
                    ),
                    inline=False,
                )
            dm_embed.set_footer(text=SUPPORT_FOOTER)
            await target.send(embed=dm_embed)
        except discord.HTTPException:
            pass

        # Tag staff channel (giữ ghi chú nội bộ)
        if cfg and cfg.staff_channel_id:
            ch = interaction.guild.get_channel(cfg.staff_channel_id)
            if ch:
                try:
                    await ch.send(content=target.mention, embed=embed)
                except discord.HTTPException:
                    pass

    # ─── /sathai ────────────────────────────────────────────────────────────

    @app_commands.command(name="sathai", description="Sa thải nhân viên ngay lập tức (chỉ Admin)")
    @app_commands.describe(
        thanh_vien="Nhân viên bị sa thải",
        ly_do="Lý do sa thải (sẽ DM cho thành viên + lưu audit)",
    )
    @app_commands.checks.cooldown(rate=3, per=300.0)
    async def sathai(
        self,
        interaction: discord.Interaction,
        thanh_vien: discord.Member,
        ly_do: str,
    ):
        await interaction.response.defer(ephemeral=True)

        async with AsyncSessionLocal() as session:
            if not await require_admin(interaction, session):
                await send_no_permission(interaction, DutyRole.ADMIN)
                return

            # Bảo vệ
            if thanh_vien.bot:
                await interaction.followup.send(
                    embed=build_error_embed("Không thể sa thải bot."),
                    ephemeral=True,
                )
                return
            if thanh_vien.id == interaction.user.id:
                await interaction.followup.send(
                    embed=build_error_embed("Không thể tự sa thải chính mình."),
                    ephemeral=True,
                )
                return
            if thanh_vien.id == interaction.guild.owner_id:
                await interaction.followup.send(
                    embed=build_error_embed("Không thể sa thải Owner server."),
                    ephemeral=True,
                )
                return

            # Import lazy để tránh circular
            from bot.cogs.leave import auto_cleanup_after_resign_approval

            cleanup_report = await auto_cleanup_after_resign_approval(
                session,
                self.bot,
                interaction.guild_id,
                thanh_vien.id,
                interaction.user.id,
                reason=f"Sa thải bởi {interaction.user}: {ly_do[:200]}",
            )

            # Audit log riêng cho /sathai
            session.add(AuditLog(
                guild_id=interaction.guild_id,
                user_id=interaction.user.id,
                username=str(interaction.user),
                action=AuditAction.DISMISSED,
                detail={
                    "for_user": str(thanh_vien.id),
                    "for_username": thanh_vien.display_name,
                    "reason": ly_do[:500],
                    "cleanup_report": cleanup_report,
                },
                created_at=utcnow(),
            ))
            await session.commit()

            cfg = await _get_config(session, interaction.guild_id)

        # Embed confirm cho người ra lệnh
        confirm_embed = discord.Embed(
            title="🔨 Đã sa thải nhân viên",
            description=(
                f"**{discord.utils.escape_markdown(thanh_vien.display_name)}** "
                f"đã bị sa thải bởi {interaction.user.mention}."
            ),
            color=COLOR_ERROR,
        )
        confirm_embed.add_field(name="📝 Lý do", value=discord.utils.escape_markdown(ly_do)[:1024], inline=False)
        confirm_embed.add_field(
            name="🧹 Đã xử lý",
            value=(
                f"• Xoá **{cleanup_report['schedules_deleted']}** lịch trực\n"
                f"• Gỡ **{len(cleanup_report.get('roles_removed') or [])}** role\n"
                f"• Bỏ qua **{len(cleanup_report.get('roles_skipped') or [])}** role (thiếu quyền)\n"
                f"• Lịch sử chấm công vẫn được giữ"
            ),
            inline=False,
        )
        await interaction.followup.send(embed=confirm_embed, ephemeral=True)

        # DM thành viên bị sa thải
        try:
            dm_embed = discord.Embed(
                title="🔨 Bạn đã bị sa thải",
                description=(
                    f"Bạn đã bị sa thải khỏi **{interaction.guild.name}** "
                    f"bởi {interaction.user.mention}."
                ),
                color=COLOR_ERROR,
            )
            dm_embed.add_field(name="📝 Lý do", value=ly_do[:1024], inline=False)
            removed = cleanup_report.get("roles_removed") or []
            if removed:
                dm_embed.add_field(
                    name="🎭 Đã gỡ role",
                    value=", ".join(f"`{n}`" for n in removed[:8]) + (f" +{len(removed)-8}" if len(removed) > 8 else ""),
                    inline=False,
                )
            dm_embed.set_footer(text=SUPPORT_FOOTER)
            await thanh_vien.send(embed=dm_embed)
        except discord.HTTPException:
            pass

        # Tag staff channel
        if cfg and cfg.staff_channel_id:
            ch = interaction.guild.get_channel(cfg.staff_channel_id)
            if ch:
                try:
                    await ch.send(content=thanh_vien.mention, embed=confirm_embed)
                except discord.HTTPException:
                    pass


async def _get_config(session, guild_id: int) -> GuildConfig | None:
    r = await session.execute(
        select(GuildConfig).where(GuildConfig.guild_id == guild_id)
    )
    return r.scalar_one_or_none()


async def setup(bot: commands.Bot):
    await bot.add_cog(DisciplineCog(bot))
