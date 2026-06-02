"""
control_panel.py — 5 Control Panel chuyên biệt cho từng channel.

Slash commands:
  /panel              — Tổng quan
  /panel-duty         — Chấm công
  /panel-leave        — Xin nghỉ phép
  /panel-resign       — Xin out ngành
  /panel-schedule     — Lịch trực

Mỗi command có param `pin: True` cho admin pin panel vào channel cố định.
"""
from __future__ import annotations
import logging

import discord
from discord import app_commands, ui
from discord.ext import commands
from sqlalchemy import select, func

from bot.config import settings
from bot.utils.time_utils import get_period_range, minutes_to_hhmm, utcnow, get_period_label
from bot.utils.embed_builder import build_error_embed
from models.base import AsyncSessionLocal
from models.duty_log import DutyLog
from models.leave import LeaveRequest, LeaveRequestStatus, LeaveRequestType
from models.schedule import MemberSchedule
from models.guild import GuildConfig

logger = logging.getLogger(__name__)

# ─── Color palette ───────────────────────────────────────────────────────────
COLOR_BRAND = 0x3B82F6      # blue — overview
COLOR_DUTY = 0x10B981       # emerald — chấm công
COLOR_LEAVE = 0x8B5CF6      # violet — xin nghỉ
COLOR_RESIGN = 0xEF4444     # red — xin out
COLOR_SCHEDULE = 0x06B6D4   # cyan — lịch trực
COLOR_GOLD = 0xFBBF24       # amber — top

# Unicode divider
DIV = "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"


def _web_url() -> str:
    return (settings.ALLOWED_ORIGINS[0] if settings.ALLOWED_ORIGINS else "http://localhost:8000").rstrip("/")


async def _fetch_guild_tz(guild_id: int) -> str:
    async with AsyncSessionLocal() as session:
        tz = (await session.execute(
            select(GuildConfig.timezone).where(GuildConfig.guild_id == guild_id)
        )).scalar_one_or_none()
    return tz or "Asia/Ho_Chi_Minh"


def _stat_chip(emoji: str, label: str, value: str) -> str:
    """Tạo 1 chip stat dạng inline để embed nhìn gọn gàng."""
    return f"{emoji} **{label}**\n` {value} `"


# ============================================================
# 1. OVERVIEW PANEL
# ============================================================

async def build_overview_embed(guild: discord.Guild, user: discord.User | discord.Member, period: str) -> discord.Embed:
    tz = await _fetch_guild_tz(guild.id)
    start, end = get_period_range(period, tz_str=tz)

    async with AsyncSessionLocal() as session:
        totals = (await session.execute(
            select(
                func.count(DutyLog.id).label("sessions"),
                func.coalesce(func.sum(DutyLog.duration_minutes), 0).label("minutes"),
                func.count(func.distinct(DutyLog.user_id)).label("active"),
            )
            .where(DutyLog.guild_id == guild.id)
            .where(DutyLog.started_at >= start)
            .where(DutyLog.started_at <= end)
        )).one()
        pending = (await session.execute(
            select(func.count(LeaveRequest.id))
            .where(LeaveRequest.guild_id == guild.id)
            .where(LeaveRequest.status == LeaveRequestStatus.PENDING)
        )).scalar() or 0
        total_schedules = (await session.execute(
            select(func.count(MemberSchedule.id))
            .where(MemberSchedule.guild_id == guild.id)
            .where(MemberSchedule.is_active == True)  # noqa: E712
        )).scalar() or 0

    embed = discord.Embed(
        title=f"🏥  HOMIE MEDIC  ·  Tổng quan {get_period_label(period).lower()}",
        description=(
            f"Xin chào **{user.display_name}** 👋\n"
            f"-# 📊 Thống kê toàn server tại thời điểm hiện tại"
        ),
        color=COLOR_BRAND,
        timestamp=utcnow(),
    )
    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)

    # 3-column stat row
    embed.add_field(
        name="⏱️  Tổng giờ trực",
        value=f"```{minutes_to_hhmm(totals.minutes or 0)}```{totals.sessions or 0} ca trong kỳ",
        inline=True,
    )
    embed.add_field(
        name="👥  Nhân sự active",
        value=f"```{totals.active or 0} người```Đã chấm công",
        inline=True,
    )
    embed.add_field(
        name="📋  Lịch trực",
        value=f"```{total_schedules} ca```Đã đăng ký",
        inline=True,
    )

    embed.add_field(
        name="📝  Đơn nghỉ chờ duyệt",
        value=(
            f"🔴 **{pending}** đơn đang chờ xử lý"
            if pending > 0 else "✅ Không có đơn nào"
        ),
        inline=False,
    )

    embed.set_footer(text=f"⚡ Đổi khoảng thời gian bằng dropdown bên dưới")
    return embed


class _PeriodSelect(ui.Select):
    def __init__(self, current: str, on_change):
        opts = [
            discord.SelectOption(label="Hôm nay", value="day", emoji="📅", default=current == "day", description="Thống kê trong ngày hôm nay"),
            discord.SelectOption(label="Tuần này", value="week", emoji="📆", default=current == "week", description="ISO week (T2 → CN)"),
            discord.SelectOption(label="Tháng này", value="month", emoji="🗓️", default=current == "month", description="Cả tháng hiện tại"),
            discord.SelectOption(label="Quý này", value="quarter", emoji="📊", default=current == "quarter", description="Q1/Q2/Q3/Q4 hiện tại"),
        ]
        super().__init__(
            placeholder=f"📆 Đổi khoảng thời gian (hiện: {get_period_label(current)})",
            options=opts, row=1,
        )
        self._on_change = on_change

    async def callback(self, interaction: discord.Interaction):
        await self._on_change(interaction, self.values[0])


class OverviewPanelView(ui.View):
    def __init__(self, period: str = "week"):
        super().__init__(timeout=None)
        self.period = period
        self.add_item(_PeriodSelect(period, self._on_period_change))

    async def _on_period_change(self, interaction: discord.Interaction, period: str):
        self.period = period
        embed = await build_overview_embed(interaction.guild, interaction.user, period)
        new_view = OverviewPanelView(period)
        await interaction.response.edit_message(embed=embed, view=new_view)

    @ui.button(label="Stats của tôi", emoji="📊", style=discord.ButtonStyle.primary, row=0)
    async def btn_my_stats(self, interaction: discord.Interaction, _: ui.Button):
        await interaction.response.defer(ephemeral=True, thinking=True)
        tz = await _fetch_guild_tz(interaction.guild_id)
        start, end = get_period_range(self.period, tz_str=tz)
        async with AsyncSessionLocal() as session:
            row = (await session.execute(
                select(
                    func.count(DutyLog.id).label("sessions"),
                    func.coalesce(func.sum(DutyLog.duration_minutes), 0).label("minutes"),
                    func.max(DutyLog.started_at).label("last"),
                    func.min(DutyLog.started_at).label("first"),
                )
                .where(DutyLog.guild_id == interaction.guild_id)
                .where(DutyLog.user_id == interaction.user.id)
                .where(DutyLog.started_at >= start)
                .where(DutyLog.started_at <= end)
            )).one()
        embed = discord.Embed(
            title="📊  Thống kê của bạn",
            description=f"### {interaction.user.display_name}\n*Kỳ: {get_period_label(self.period)}*",
            color=COLOR_BRAND, timestamp=utcnow(),
        )
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        embed.add_field(name="⏱️  GIỜ TRỰC", value=f"```ml\n{minutes_to_hhmm(row.minutes or 0)}\n```", inline=True)
        embed.add_field(name="📋  SỐ CA", value=f"```ml\n{row.sessions or 0}\n```", inline=True)
        if row.sessions:
            avg = (row.minutes or 0) // row.sessions
            embed.add_field(name="📐  TB/CA", value=f"```ml\n{minutes_to_hhmm(avg)}\n```", inline=True)
        if row.last:
            embed.add_field(name="🕐 Lần chấm công cuối", value=f"<t:{int(row.last.timestamp())}:R>", inline=True)
        if row.first:
            embed.add_field(name="🚀 Lần đầu trong kỳ", value=f"<t:{int(row.first.timestamp())}:R>", inline=True)
        embed.set_footer(text="Dùng /log upload để thêm ca trực mới")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @ui.button(label="Top trực", emoji="🏆", style=discord.ButtonStyle.secondary, row=0)
    async def btn_top(self, interaction: discord.Interaction, _: ui.Button):
        await interaction.response.defer(ephemeral=True, thinking=True)
        tz = await _fetch_guild_tz(interaction.guild_id)
        start, end = get_period_range(self.period, tz_str=tz)
        async with AsyncSessionLocal() as session:
            rows = (await session.execute(
                select(DutyLog.username, func.sum(DutyLog.duration_minutes).label("m"), func.count(DutyLog.id).label("c"))
                .where(DutyLog.guild_id == interaction.guild_id)
                .where(DutyLog.started_at >= start)
                .where(DutyLog.started_at <= end)
                .group_by(DutyLog.user_id, DutyLog.username)
                .order_by(func.sum(DutyLog.duration_minutes).desc())
                .limit(10)
            )).all()
        embed = discord.Embed(
            title=f"🏆  Top 10 trực — {get_period_label(self.period)}",
            color=COLOR_GOLD, timestamp=utcnow(),
        )
        if not rows:
            embed.description = "*Chưa có dữ liệu trong kỳ này.*"
        else:
            max_m = rows[0].m or 1
            medals = ["🥇", "🥈", "🥉"] + [f"`#{i:>2}`" for i in range(4, 11)]
            lines = []
            for i, r in enumerate(rows):
                bar_len = int((r.m / max_m) * 12)
                bar = "█" * bar_len + "░" * (12 - bar_len)
                lines.append(f"{medals[i]} **{r.username}** · `{minutes_to_hhmm(r.m)}` ({r.c} ca)\n`{bar}`")
            embed.description = "\n\n".join(lines)
        embed.set_footer(text="Dùng /top để xem bảng xếp hạng chi tiết")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @ui.button(label="Làm mới", emoji="🔄", style=discord.ButtonStyle.secondary, row=0)
    async def btn_refresh(self, interaction: discord.Interaction, _: ui.Button):
        embed = await build_overview_embed(interaction.guild, interaction.user, self.period)
        await interaction.response.edit_message(embed=embed, view=self)


# ============================================================
# 2. DUTY PANEL
# ============================================================

async def build_duty_embed(guild: discord.Guild, user: discord.User | discord.Member) -> discord.Embed:
    """Embed cá nhân hoá: ưu tiên stats của user, kèm setup channel + quick hint upload."""
    tz = await _fetch_guild_tz(guild.id)
    week_start, week_end = get_period_range("week", tz_str=tz)
    day_start, day_end = get_period_range("day", tz_str=tz)

    async with AsyncSessionLocal() as session:
        # Stats CÁ NHÂN
        my_week = (await session.execute(
            select(
                func.count(DutyLog.id).label("c"),
                func.coalesce(func.sum(DutyLog.duration_minutes), 0).label("m"),
                func.max(DutyLog.started_at).label("last"),
            )
            .where(DutyLog.guild_id == guild.id)
            .where(DutyLog.user_id == user.id)
            .where(DutyLog.started_at >= week_start)
            .where(DutyLog.started_at <= week_end)
        )).one()
        my_today = (await session.execute(
            select(
                func.count(DutyLog.id).label("c"),
                func.coalesce(func.sum(DutyLog.duration_minutes), 0).label("m"),
            )
            .where(DutyLog.guild_id == guild.id)
            .where(DutyLog.user_id == user.id)
            .where(DutyLog.started_at >= day_start)
            .where(DutyLog.started_at <= day_end)
        )).one()
        # Channel chấm công đã setup
        cfg = (await session.execute(
            select(GuildConfig).where(GuildConfig.guild_id == guild.id)
        )).scalar_one_or_none()
        # Channel chấm công gọi là `log_channel_id` trong GuildConfig
        duty_channel_id = getattr(cfg, "log_channel_id", None) if cfg else None

    channel_mention = f"<#{duty_channel_id}>" if duty_channel_id else "*chưa setup* — dùng `/setup channel`"

    embed = discord.Embed(
        title="✍️  Bảng chấm công",
        description=(
            f"Xin chào **{user.display_name}** 👋\n"
            f"📍 Channel chấm công: {channel_mention}\n"
            f"-# *Forward hoặc screenshot tin nhắn LOG DUTY vào channel — bot tự xử lý.*"
        ),
        color=COLOR_DUTY, timestamp=utcnow(),
    )
    embed.set_thumbnail(url=user.display_avatar.url)

    # ── Stats cá nhân ──
    embed.add_field(
        name="📅  Hôm nay",
        value=f"```{minutes_to_hhmm(my_today.m or 0)}```{my_today.c or 0} ca",
        inline=True,
    )
    embed.add_field(
        name="📆  Tuần này",
        value=f"```{minutes_to_hhmm(my_week.m or 0)}```{my_week.c or 0} ca",
        inline=True,
    )
    embed.add_field(
        name="🕐  Lần cuối chấm",
        value=(
            f"<t:{int(my_week.last.timestamp())}:R>"
            if my_week.last else "*Chưa có log*"
        ),
        inline=True,
    )

    # ── 2 cách chấm công ──
    embed.add_field(
        name="🚀  Cách chấm công",
        value=(
            f"**1.** Forward tin nhắn LOG DUTY → {channel_mention}\n"
            f"**2.** Hoặc gửi ảnh screenshot LOG DUTY → {channel_mention}\n\n"
            f"Bot tự OCR/parse → reply embed *Đã ghi nhận ca trực* khi thành công.\n"
            f"Nếu sai format/tên/trùng → bot báo lỗi cụ thể."
        ),
        inline=False,
    )

    embed.set_footer(text="🔒 Bot khớp tên với Discord ID — không thể chấm hộ người khác")
    return embed


def _build_log_format_help_embed() -> discord.Embed:
    """Embed phụ — hiện khi user click button "Format chuẩn"."""
    embed = discord.Embed(
        title="📋  Format LOG DUTY chuẩn",
        description=(
            "### Quy trình chuẩn\n"
            "1️⃣ Bot bệnh viện (HomieMedic / khác) gửi tin nhắn **LOG DUTY** khi bạn kết thúc ca\n"
            "2️⃣ Bạn **forward** hoặc **screenshot** tin nhắn đó vào channel chấm công\n"
            "3️⃣ Bot này auto-scan → parse → lưu DB → reply embed xác nhận\n\n"
            "### Format text bot mong đợi\n"
            "```yaml\n"
            "LOG DUTY (Disconnect)\n"
            "Tên: {tên bạn}\n"
            "Thời gian làm việc: {X} phút\n"
            "Thời gian bắt đầu: {DD/MM/YYYY HH:MM:SS}\n"
            "Thời gian kết thúc: {DD/MM/YYYY HH:MM:SS}\n"
            "```"
        ),
        color=COLOR_DUTY,
    )
    embed.add_field(
        name="✅  Bot chấp nhận",
        value=(
            "• Forward thẳng tin nhắn LOG DUTY\n"
            "• Ảnh screenshot tin nhắn LOG DUTY\n"
            "• Copy/paste text LOG DUTY thủ công\n"
            "• Mọi biến thể: `LOG DUTY`, `LOG DUTY (Disconnect)`, có/không kèm timestamp footer"
        ),
        inline=False,
    )
    embed.add_field(
        name="❌  Bot từ chối",
        value=(
            "• Tên trong LOG DUTY **không khớp** username/nickname Discord của bạn\n"
            "  *(không chấm công hộ người khác)*\n"
            "• Format ngày sai (phải `DD/MM/YYYY`)\n"
            "• Trùng ca đã chấm (cùng thời gian, hoặc message_id đã lưu)\n"
            "• `bắt đầu` ≥ `kết thúc`\n"
            "• Thời gian làm việc lệch >5 phút so với (end − start)"
        ),
        inline=False,
    )
    embed.add_field(
        name="🔧  Slash command (fallback)",
        value=(
            "Khi auto-scan không hoạt động (channel không setup, format lạ…):\n"
            "• `/log upload` — chọn file ảnh\n"
            "• `/log forward` — paste text vào modal"
        ),
        inline=False,
    )
    embed.set_footer(text="💡 Tip: forward (cách 1) nhanh nhất vì bot đọc text trực tiếp, không cần OCR")
    return embed


class DutyPanelView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="Format chuẩn", emoji="❓", style=discord.ButtonStyle.secondary, row=0)
    async def btn_help(self, interaction: discord.Interaction, _: ui.Button):
        await interaction.response.send_message(
            embed=_build_log_format_help_embed(), ephemeral=True,
        )

    @ui.button(label="Log gần nhất của tôi", emoji="📜", style=discord.ButtonStyle.primary, row=0)
    async def btn_my_logs(self, interaction: discord.Interaction, _: ui.Button):
        await interaction.response.defer(ephemeral=True, thinking=True)
        async with AsyncSessionLocal() as session:
            logs = (await session.execute(
                select(DutyLog)
                .where(DutyLog.guild_id == interaction.guild_id)
                .where(DutyLog.user_id == interaction.user.id)
                .order_by(DutyLog.started_at.desc())
                .limit(10)
            )).scalars().all()
        embed = discord.Embed(
            title="📜  10 ca trực gần nhất",
            description=f"### {interaction.user.display_name}",
            color=COLOR_DUTY, timestamp=utcnow(),
        )
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        if not logs:
            embed.description += "\n\n*Bạn chưa có log nào. Thử `/log upload`.*"
        else:
            lines = []
            for log in logs:
                lines.append(
                    f"`#{log.id:>5}` <t:{int(log.started_at.timestamp())}:R> · "
                    f"⏱️ **{minutes_to_hhmm(log.duration_minutes)}**"
                )
            embed.description += "\n\n" + "\n".join(lines)
        embed.set_footer(text="Dùng /log view để xem với filter chi tiết")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @ui.button(label="Top trực tuần", emoji="🏆", style=discord.ButtonStyle.secondary, row=0)
    async def btn_top_week(self, interaction: discord.Interaction, _: ui.Button):
        await interaction.response.defer(ephemeral=True, thinking=True)
        tz = await _fetch_guild_tz(interaction.guild_id)
        start, end = get_period_range("week", tz_str=tz)
        async with AsyncSessionLocal() as session:
            rows = (await session.execute(
                select(DutyLog.username, func.sum(DutyLog.duration_minutes).label("m"), func.count(DutyLog.id).label("c"))
                .where(DutyLog.guild_id == interaction.guild_id)
                .where(DutyLog.started_at >= start)
                .where(DutyLog.started_at <= end)
                .group_by(DutyLog.user_id, DutyLog.username)
                .order_by(func.sum(DutyLog.duration_minutes).desc())
                .limit(5)
            )).all()
        embed = discord.Embed(
            title="🏆  Top 5 trực tuần này",
            color=COLOR_GOLD, timestamp=utcnow(),
        )
        if not rows:
            embed.description = "*Chưa có ai trực tuần này.*"
        else:
            max_m = rows[0].m or 1
            medals = ["🥇", "🥈", "🥉", "🏅", "🏅"]
            lines = []
            for i, r in enumerate(rows):
                bar_len = int((r.m / max_m) * 15)
                bar = "█" * bar_len + "░" * (15 - bar_len)
                lines.append(
                    f"{medals[i]}  **{r.username}** — `{minutes_to_hhmm(r.m)}`\n"
                    f"`{bar}` *{r.c} ca*"
                )
            embed.description = "\n\n".join(lines)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @ui.button(label="Làm mới", emoji="🔄", style=discord.ButtonStyle.secondary, row=0)
    async def btn_refresh(self, interaction: discord.Interaction, _: ui.Button):
        embed = await build_duty_embed(interaction.guild, interaction.user)
        await interaction.response.edit_message(embed=embed, view=self)


# ============================================================
# 3. LEAVE PANEL
# ============================================================

class LeaveModal(ui.Modal, title="📤 Gửi đơn xin nghỉ phép"):
    start_date_input = ui.TextInput(label="Ngày bắt đầu (DD/MM/YYYY)", placeholder="VD: 20/05/2026", max_length=10, required=True)
    end_date_input = ui.TextInput(label="Ngày kết thúc (để trống = 1 ngày)", placeholder="VD: 22/05/2026", max_length=10, required=False)
    reason_input = ui.TextInput(
        label="Lý do",
        style=discord.TextStyle.paragraph,
        placeholder="Mô tả ngắn gọn lý do xin nghỉ…",
        max_length=500, required=True,
    )

    async def on_submit(self, interaction: discord.Interaction):
        # Defer trước — delegate sang LeaveCog có thể tốn >3s (gửi message + add 2 reactions + DM)
        await interaction.response.defer(ephemeral=True, thinking=True)

        # Parse dates
        from bot.cogs.leave import _parse_date, LeaveCog
        from datetime import date, timedelta
        try:
            sd = _parse_date(self.start_date_input.value)
            end_v = self.end_date_input.value.strip()
            ed = _parse_date(end_v) if end_v else sd
            if ed < sd:
                raise ValueError("Ngày kết thúc phải sau ngày bắt đầu")
            if sd < date.today() - timedelta(days=1):
                raise ValueError("Ngày bắt đầu không thể ở quá khứ")
        except ValueError as e:
            await interaction.followup.send(
                embed=build_error_embed(str(e), title="❌ Sai định dạng"), ephemeral=True,
            )
            return

        # Delegate sang LeaveCog._submit_request — post lên staff channel + reactions + DM
        leave_cog: LeaveCog | None = interaction.client.get_cog("LeaveCog")
        if leave_cog is None:
            await interaction.followup.send(
                embed=build_error_embed("Cog `LeaveCog` chưa được load. Liên hệ admin."),
                ephemeral=True,
            )
            return
        await leave_cog._submit_request(
            interaction,
            request_type=LeaveRequestType.LEAVE,
            start_date=sd,
            end_date=ed,
            reason=self.reason_input.value.strip(),
        )


async def build_leave_embed(guild: discord.Guild, user: discord.User | discord.Member) -> discord.Embed:
    async with AsyncSessionLocal() as session:
        my_pending = (await session.execute(
            select(func.count(LeaveRequest.id))
            .where(LeaveRequest.guild_id == guild.id)
            .where(LeaveRequest.user_id == user.id)
            .where(LeaveRequest.status == LeaveRequestStatus.PENDING)
        )).scalar() or 0
        my_approved = (await session.execute(
            select(func.count(LeaveRequest.id))
            .where(LeaveRequest.guild_id == guild.id)
            .where(LeaveRequest.user_id == user.id)
            .where(LeaveRequest.status == LeaveRequestStatus.APPROVED)
        )).scalar() or 0
        server_pending = (await session.execute(
            select(func.count(LeaveRequest.id))
            .where(LeaveRequest.guild_id == guild.id)
            .where(LeaveRequest.status == LeaveRequestStatus.PENDING)
            .where(LeaveRequest.request_type == "leave")
        )).scalar() or 0

    embed = discord.Embed(
        title="📤  Xin nghỉ phép",
        description=(
            "Gửi đơn nghỉ ngắn hạn — staff vote duyệt.\n"
            "-# *Bạn nhận DM kết quả ngay khi staff quyết định.*"
        ),
        color=COLOR_LEAVE, timestamp=utcnow(),
    )
    embed.add_field(
        name="📋  Đơn của bạn",
        value=(
            f"⏳ Chờ duyệt: ` {my_pending} `\n"
            f"✅ Đã duyệt: ` {my_approved} `"
        ),
        inline=True,
    )
    embed.add_field(
        name="🗂️  Tổng server",
        value=f"🔴 ` {server_pending} ` đơn đang chờ",
        inline=True,
    )
    embed.add_field(
        name="⏱️  Thời hạn duyệt",
        value="Tối đa **24h**\nkể từ lúc gửi",
        inline=True,
    )

    embed.add_field(
        name="📝  Hướng dẫn",
        value=(
            "**1.** Click **Gửi đơn xin nghỉ** → mở form\n"
            "**2.** Điền loại nghỉ + ngày + lý do\n"
            "**3.** Staff vote — đa số duyệt = approved\n"
            "**4.** Nếu approved: bot auto-note vào lịch + audit log"
        ),
        inline=False,
    )
    embed.set_footer(text="💡 Cần out hẳn khỏi ngành? Dùng /panel-resign")
    return embed


class LeavePanelView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="Gửi đơn xin nghỉ", emoji="📤", style=discord.ButtonStyle.success, row=0)
    async def btn_submit(self, interaction: discord.Interaction, _: ui.Button):
        await interaction.response.send_modal(LeaveModal())

    @ui.button(label="Đơn của tôi", emoji="📋", style=discord.ButtonStyle.primary, row=0)
    async def btn_my_leaves(self, interaction: discord.Interaction, _: ui.Button):
        await interaction.response.defer(ephemeral=True, thinking=True)
        async with AsyncSessionLocal() as session:
            rows = (await session.execute(
                select(LeaveRequest)
                .where(LeaveRequest.guild_id == interaction.guild_id)
                .where(LeaveRequest.user_id == interaction.user.id)
                .order_by(LeaveRequest.created_at.desc())
                .limit(10)
            )).scalars().all()
        embed = discord.Embed(
            title="📋  10 đơn gần nhất của bạn",
            description=f"### {interaction.user.display_name}",
            color=COLOR_LEAVE, timestamp=utcnow(),
        )
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        if not rows:
            embed.description += "\n\n*Bạn chưa gửi đơn nào.*"
        else:
            status_meta = {
                "pending":  ("⏳", "Chờ duyệt"),
                "approved": ("✅", "Đã duyệt"),
                "rejected": ("❌", "Từ chối"),
            }
            lines = []
            for r in rows:
                emo, lbl = status_meta.get(r.status, ("•", r.status))
                period_str = r.start_date.strftime("%d/%m") + (
                    f"→{r.end_date.strftime('%d/%m')}" if r.end_date and r.end_date != r.start_date else ""
                )
                lines.append(f"{emo} `#{r.id:>4}` · **{lbl}** · `{period_str}` · {r.request_type}")
            embed.description += "\n\n" + "\n".join(lines)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @ui.button(label="Làm mới", emoji="🔄", style=discord.ButtonStyle.secondary, row=0)
    async def btn_refresh(self, interaction: discord.Interaction, _: ui.Button):
        embed = await build_leave_embed(interaction.guild, interaction.user)
        await interaction.response.edit_message(embed=embed, view=self)


# ============================================================
# 4. RESIGN PANEL
# ============================================================

class ResignModal(ui.Modal, title="⚠️ Xin out ngành"):
    confirm_input = ui.TextInput(label="Gõ 'XÁC NHẬN' để tiếp tục", placeholder="XÁC NHẬN", max_length=10, required=True)
    target_date_input = ui.TextInput(label="Ngày dự kiến out (DD/MM/YYYY)", placeholder="VD: 30/06/2026", max_length=10, required=True)
    reason_input = ui.TextInput(label="Lý do xin out", style=discord.TextStyle.paragraph, max_length=1000, required=True)
    handover_input = ui.TextInput(label="Bàn giao ca trực (tuỳ chọn)", style=discord.TextStyle.paragraph, max_length=300, required=False)

    async def on_submit(self, interaction: discord.Interaction):
        if self.confirm_input.value.strip().upper() != "XÁC NHẬN":
            await interaction.response.send_message(
                embed=build_error_embed("Bạn phải gõ chính xác `XÁC NHẬN` để gửi đơn."),
                ephemeral=True,
            )
            return
        await interaction.response.defer(ephemeral=True, thinking=True)

        from bot.cogs.leave import _parse_date, LeaveCog
        try:
            tgt = _parse_date(self.target_date_input.value)
        except ValueError as e:
            await interaction.followup.send(
                embed=build_error_embed(str(e), title="❌ Sai định dạng"), ephemeral=True,
            )
            return

        full_reason = self.reason_input.value.strip()
        if self.handover_input.value.strip():
            full_reason += f"\n\n**Bàn giao:** {self.handover_input.value.strip()}"

        leave_cog: LeaveCog | None = interaction.client.get_cog("LeaveCog")
        if leave_cog is None:
            await interaction.followup.send(
                embed=build_error_embed("Cog `LeaveCog` chưa được load. Liên hệ admin."),
                ephemeral=True,
            )
            return
        await leave_cog._submit_request(
            interaction,
            request_type=LeaveRequestType.RESIGN,
            start_date=tgt,
            end_date=None,
            reason=full_reason,
        )


async def build_resign_embed() -> discord.Embed:
    embed = discord.Embed(
        title="⚠️  Xin out ngành",
        description=(
            "**🚨 Quyết định nghiêm trọng** — đơn xin out sẽ:\n"
            "🔴 Yêu cầu vote duyệt từ **nhiều staff** (1 admin không tự duyệt được)\n"
            "🔴 Nếu duyệt: bot **tự gỡ role nhân viên** vào ngày đã chọn\n"
            "🔴 Huỷ **mọi lịch trực** còn lại của bạn\n\n"
            "-# 💡 *Chỉ muốn nghỉ ngắn hạn? Dùng `/panel-leave` thay vì panel này.*"
        ),
        color=COLOR_RESIGN, timestamp=utcnow(),
    )
    embed.add_field(
        name="✅  Checklist trước khi gửi",
        value=(
            "```diff\n"
            "+ Đã hoàn thành công việc đang dang dở\n"
            "+ Đã bàn giao ca trực cho người tiếp nhận\n"
            "+ Đã thông báo với cấp trên / leader\n"
            "+ Hiểu rằng quyết định khó hoàn tác sau khi duyệt\n"
            "```"
        ),
        inline=False,
    )
    embed.set_footer(text="🔒 Gõ chính xác 'XÁC NHẬN' trong form để xác nhận chủ ý")
    return embed


class ResignPanelView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="Gửi đơn xin out", emoji="⚠️", style=discord.ButtonStyle.danger, row=0)
    async def btn_submit(self, interaction: discord.Interaction, _: ui.Button):
        await interaction.response.send_modal(ResignModal())

    @ui.button(label="Trạng thái đơn của tôi", emoji="📋", style=discord.ButtonStyle.secondary, row=0)
    async def btn_my_resign(self, interaction: discord.Interaction, _: ui.Button):
        await interaction.response.defer(ephemeral=True, thinking=True)
        async with AsyncSessionLocal() as session:
            rows = (await session.execute(
                select(LeaveRequest)
                .where(LeaveRequest.guild_id == interaction.guild_id)
                .where(LeaveRequest.user_id == interaction.user.id)
                .where(LeaveRequest.request_type == "resign")
                .order_by(LeaveRequest.created_at.desc())
                .limit(5)
            )).scalars().all()
        embed = discord.Embed(title="📋  Đơn xin out của bạn", color=COLOR_RESIGN, timestamp=utcnow())
        if not rows:
            embed.description = "*Bạn chưa từng gửi đơn xin out — điều đó tốt* 🎉"
        else:
            status_label = {
                "pending":  ("⏳", "Đang chờ vote"),
                "approved": ("✅", "Đã được duyệt"),
                "rejected": ("❌", "Bị từ chối"),
            }
            lines = []
            for r in rows:
                emo, lbl = status_label.get(r.status, ("•", r.status))
                lines.append(f"{emo} `#{r.id}` — **{lbl}** · ngày dự kiến `{r.start_date.strftime('%d/%m/%Y')}`")
            embed.description = "\n".join(lines)
        await interaction.followup.send(embed=embed, ephemeral=True)


# ============================================================
# 5. SCHEDULE PANEL
# ============================================================

async def build_schedule_embed(guild: discord.Guild, user: discord.User | discord.Member) -> discord.Embed:
    async with AsyncSessionLocal() as session:
        my_count = (await session.execute(
            select(func.count(MemberSchedule.id))
            .where(MemberSchedule.guild_id == guild.id)
            .where(MemberSchedule.user_id == user.id)
            .where(MemberSchedule.is_active == True)  # noqa: E712
        )).scalar() or 0
        total_count = (await session.execute(
            select(func.count(MemberSchedule.id))
            .where(MemberSchedule.guild_id == guild.id)
            .where(MemberSchedule.is_active == True)  # noqa: E712
        )).scalar() or 0
        total_members = (await session.execute(
            select(func.count(func.distinct(MemberSchedule.user_id)))
            .where(MemberSchedule.guild_id == guild.id)
            .where(MemberSchedule.is_active == True)  # noqa: E712
        )).scalar() or 0

    embed = discord.Embed(
        title="📅  Lịch trực hàng tuần",
        description=(
            "Quản lý ca trực — bot **nhắc trước giờ vào ca** và tính độ tuân thủ "
            "dựa trên log chấm công thực tế."
        ),
        color=COLOR_SCHEDULE, timestamp=utcnow(),
    )

    embed.add_field(
        name="🗓️  Của bạn",
        value=f"```{my_count} ca/tuần```",
        inline=True,
    )
    embed.add_field(
        name="👥  Đã đăng ký",
        value=f"```{total_members} người```",
        inline=True,
    )
    embed.add_field(
        name="📋  Tổng server",
        value=f"```{total_count} ca```",
        inline=True,
    )

    embed.add_field(
        name="⚙️  Thao tác nhanh",
        value=(
            "**📅 Lịch của tôi** — xem ca đã đăng ký theo thứ\n"
            "**➕ Đăng ký ca mới** — hướng dẫn dùng `/dangky`\n"
            "**📊 Báo cáo tuân thủ** — rate on-time / late / missed"
        ),
        inline=False,
    )
    embed.set_footer(text="🔔 Mặc định nhắc 60/30/5 phút trước ca — đổi qua /lich nhac")
    return embed


class SchedulePanelView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="Lịch của tôi", emoji="📅", style=discord.ButtonStyle.primary, row=0)
    async def btn_my_schedule(self, interaction: discord.Interaction, _: ui.Button):
        await interaction.response.defer(ephemeral=True, thinking=True)
        async with AsyncSessionLocal() as session:
            scheds = (await session.execute(
                select(MemberSchedule)
                .where(MemberSchedule.guild_id == interaction.guild_id)
                .where(MemberSchedule.user_id == interaction.user.id)
                .where(MemberSchedule.is_active == True)  # noqa: E712
                .order_by(MemberSchedule.weekday, MemberSchedule.start_time)
            )).scalars().all()
        embed = discord.Embed(
            title="📅  Lịch trực của bạn",
            description=f"### {interaction.user.display_name}",
            color=COLOR_SCHEDULE, timestamp=utcnow(),
        )
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        if not scheds:
            embed.description += "\n\n*Bạn chưa đăng ký ca nào. Dùng `/dangky` để bắt đầu.*"
        else:
            weekdays = ["Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7", "Chủ nhật"]
            by_day: dict[int, list] = {}
            for s in scheds:
                by_day.setdefault(s.weekday, []).append(s)
            for wd in sorted(by_day.keys()):
                slots = "\n".join(
                    f"`#{s.id:>3}` `{s.start_time.strftime('%H:%M')} → {s.end_time.strftime('%H:%M')}`"
                    + (" 🌙" if s.crosses_midnight else "")
                    for s in by_day[wd]
                )
                embed.add_field(name=f"📌 {weekdays[wd]}", value=slots, inline=True)
        embed.set_footer(text="🌙 = ca qua đêm · Dùng /lich xoa <id> để xoá")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @ui.button(label="Đăng ký ca mới", emoji="➕", style=discord.ButtonStyle.success, row=0)
    async def btn_add(self, interaction: discord.Interaction, _: ui.Button):
        embed = discord.Embed(
            title="➕  Đăng ký ca trực mới",
            description=(
                "### Slash command: `/dangky`\n\n"
                "```yaml\n"
                "Tham số:\n"
                "  thu          : Thứ trong tuần (T2-CN)\n"
                "  gio_bat_dau  : VD 07:00\n"
                "  gio_ket_thuc : VD 15:00 (có thể qua đêm)\n"
                "```\n"
                "🔔 Ca trực sẽ được nhắc trước theo các mốc đã setup."
            ),
            color=COLOR_SCHEDULE,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @ui.button(label="Báo cáo tuân thủ", emoji="📊", style=discord.ButtonStyle.secondary, row=0)
    async def btn_compliance(self, interaction: discord.Interaction, _: ui.Button):
        embed = discord.Embed(
            title="📊  Báo cáo tuân thủ",
            description=(
                "Slash command: `/lich tongket`\n\n"
                "Xem tỷ lệ on-time / late / missed của từng thành viên theo kỳ."
            ),
            color=COLOR_SCHEDULE, timestamp=utcnow(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @ui.button(label="Làm mới", emoji="🔄", style=discord.ButtonStyle.secondary, row=0)
    async def btn_refresh(self, interaction: discord.Interaction, _: ui.Button):
        embed = await build_schedule_embed(interaction.guild, interaction.user)
        await interaction.response.edit_message(embed=embed, view=self)


# ============================================================
# Cog — 5 commands × 2 variants (regular + pin)
# ============================================================

async def _send_panel(
    interaction: discord.Interaction,
    embed: discord.Embed,
    view: ui.View,
    pin: bool,
):
    """Send panel — pin path defers interaction trước để tránh 'Ứng dụng không phản hồi'."""
    if pin:
        # Defer ngay để Discord biết bot đã nhận; sau đó mới gửi + pin (có thể tốn 1-2s)
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            msg = await interaction.channel.send(embed=embed, view=view)
        except discord.Forbidden:
            await interaction.followup.send(
                embed=build_error_embed("Bot không có quyền gửi message trong channel này."),
                ephemeral=True,
            )
            return
        try:
            await msg.pin(reason=f"Homie Medic panel by {interaction.user}")
        except discord.Forbidden:
            await interaction.followup.send(
                embed=build_error_embed(
                    "Đã gửi panel nhưng bot không có quyền **Manage Messages** để pin. "
                    "Vào server settings → Roles → Cái máy chấm công → bật `Manage Messages`."
                ),
                ephemeral=True,
            )
            return
        except discord.HTTPException as e:
            await interaction.followup.send(
                embed=build_error_embed(f"Pin thất bại: {e}. Có thể channel đã đủ 50 pinned messages."),
                ephemeral=True,
            )
            return
        await interaction.followup.send(
            embed=discord.Embed(
                title="✅  Đã pin panel",
                description=f"Panel đã được pin trong {interaction.channel.mention}. Mọi người trong channel này có thể dùng các nút.",
                color=COLOR_DUTY,
            ),
            ephemeral=True,
        )
    else:
        await interaction.response.send_message(embed=embed, view=view)


async def _check_pin_permission(interaction: discord.Interaction) -> bool:
    """
    Cho phép pin panel khi:
      - User có Discord native `manage_messages`, HOẶC
      - User là DUTY_ADMIN trong hierarchy bot.
    Lý do: DUTY_ADMIN cần pin được panel kể cả khi Discord role không có
    `manage_messages`; ngược lại các channel mod cũ vẫn pin được mà không
    phải nâng cấp lên DUTY_ADMIN.
    """
    if interaction.user.guild_permissions.manage_messages:
        return True
    from bot.utils.permissions import require_admin
    async with AsyncSessionLocal() as session:
        return await require_admin(interaction, session)


class ControlPanelCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ───── OVERVIEW ─────
    @app_commands.command(name="panel", description="📊 Panel tổng quan — stats + top + period")
    @app_commands.describe(pin="Pin panel vào channel (cần Manage Messages)")
    async def panel(self, interaction: discord.Interaction, pin: bool = False):
        if pin and not await _check_pin_permission(interaction):
            await interaction.response.send_message(
                embed=build_error_embed("Cần permission `Manage Messages` để pin."), ephemeral=True,
            )
            return
        embed = await build_overview_embed(interaction.guild, interaction.user, "week")
        await _send_panel(interaction, embed, OverviewPanelView("week"), pin)

    # ───── DUTY ─────
    @app_commands.command(name="panel-duty", description="✍️ Panel chấm công — hướng dẫn + log gần nhất + top")
    @app_commands.describe(pin="Pin panel vào channel chấm công (cần Manage Messages)")
    async def panel_duty(self, interaction: discord.Interaction, pin: bool = False):
        if pin and not await _check_pin_permission(interaction):
            await interaction.response.send_message(
                embed=build_error_embed("Cần permission `Manage Messages` để pin."), ephemeral=True,
            )
            return
        embed = await build_duty_embed(interaction.guild, interaction.user)
        await _send_panel(interaction, embed, DutyPanelView(), pin)

    # ───── LEAVE ─────
    @app_commands.command(name="panel-leave", description="📤 Panel xin nghỉ phép — modal + danh sách đơn")
    @app_commands.describe(pin="Pin panel vào channel xin nghỉ (cần Manage Messages)")
    async def panel_leave(self, interaction: discord.Interaction, pin: bool = False):
        if pin and not await _check_pin_permission(interaction):
            await interaction.response.send_message(
                embed=build_error_embed("Cần permission `Manage Messages` để pin."), ephemeral=True,
            )
            return
        embed = await build_leave_embed(interaction.guild, interaction.user)
        await _send_panel(interaction, embed, LeavePanelView(), pin)

    # ───── RESIGN ─────
    @app_commands.command(name="panel-resign", description="⚠️ Panel xin out ngành — cảnh báo + modal nghiêm túc")
    @app_commands.describe(pin="Pin panel vào channel HR/staff (cần Manage Messages)")
    async def panel_resign(self, interaction: discord.Interaction, pin: bool = False):
        if pin and not await _check_pin_permission(interaction):
            await interaction.response.send_message(
                embed=build_error_embed("Cần permission `Manage Messages` để pin."), ephemeral=True,
            )
            return
        embed = await build_resign_embed()
        await _send_panel(interaction, embed, ResignPanelView(), pin)

    # ───── SCHEDULE ─────
    @app_commands.command(name="panel-schedule", description="📅 Panel lịch trực — xem lịch + đăng ký + tuân thủ")
    @app_commands.describe(pin="Pin panel vào channel lịch trực (cần Manage Messages)")
    async def panel_schedule(self, interaction: discord.Interaction, pin: bool = False):
        if pin and not await _check_pin_permission(interaction):
            await interaction.response.send_message(
                embed=build_error_embed("Cần permission `Manage Messages` để pin."), ephemeral=True,
            )
            return
        embed = await build_schedule_embed(interaction.guild, interaction.user)
        await _send_panel(interaction, embed, SchedulePanelView(), pin)


async def setup(bot: commands.Bot):
    await bot.add_cog(ControlPanelCog(bot))
