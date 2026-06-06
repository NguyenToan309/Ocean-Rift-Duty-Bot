"""
schedule.py — Cog quản lý lịch trực:
- /dangky          : modal nhập giờ + ngày, lưu MemberSchedule
- /lich xem        : xem lịch của mình hoặc người khác
- /lich xoa <id>   : xoá 1 entry
- /lich nhac       : member tuỳ chỉnh mốc nhắc trước ca
- /lich tongket    : báo cáo tuân thủ (compliance report)
- /lich tatca      : (mod+) xem lịch toàn server
"""
from __future__ import annotations
import logging
import re
from datetime import datetime, time, timedelta, date

import discord
from discord.ext import commands
from discord import app_commands
from sqlalchemy import select, delete
from sqlalchemy.exc import IntegrityError

from models.base import AsyncSessionLocal
from models.guild import GuildConfig
from models.schedule import MemberSchedule, WEEKDAY_LABELS, WEEKDAY_SHORT
from models.audit_log import AuditLog, AuditAction
from bot.utils.permissions import require_member, require_mod, send_no_permission, DutyRole
from bot.utils.embed_builder import (
    build_error_embed, build_success_embed, build_info_embed, COLOR_INFO, COLOR_SUCCESS,
)
from bot.utils.time_utils import utcnow, get_period_range, make_period_choices, get_period_label
from bot.utils.schedule_engine import (
    compute_compliance,
    STATUS_ON_TIME, STATUS_LATE, STATUS_MISSED, STATUS_OFF_SCHEDULE, STATUS_ON_LEAVE,
)

logger = logging.getLogger(__name__)


# ─── Helpers parse input ─────────────────────────────────────────────────────

_TIME_PAT = re.compile(r"^\s*(\d{1,2})\s*[:h.]\s*(\d{0,2})\s*$")


def _parse_time(s: str) -> time:
    """Parse '8h', '8:30', '08:30', '17h00' → time. Raise ValueError nếu sai."""
    m = _TIME_PAT.match(s)
    if not m:
        raise ValueError(f"Giờ không hợp lệ: '{s}'. Dùng dạng HH:MM (vd: 18:30)")
    h = int(m.group(1))
    minute_str = m.group(2) or "0"
    mn = int(minute_str)
    if not (0 <= h <= 23 and 0 <= mn <= 59):
        raise ValueError(f"Giờ không hợp lệ: {h}:{mn}")
    return time(hour=h, minute=mn)


# Map nhãn nhập → weekday number
_WEEKDAY_INPUT = {
    "t2": 0, "thu2": 0, "thứ2": 0, "monday": 0, "mon": 0,
    "t3": 1, "thu3": 1, "thứ3": 1, "tuesday": 1, "tue": 1,
    "t4": 2, "thu4": 2, "thứ4": 2, "wednesday": 2, "wed": 2,
    "t5": 3, "thu5": 3, "thứ5": 3, "thursday": 3, "thu": 3,
    "t6": 4, "thu6": 4, "thứ6": 4, "friday": 4, "fri": 4,
    "t7": 5, "thu7": 5, "thứ7": 5, "saturday": 5, "sat": 5,
    "cn": 6, "chunhat": 6, "chủnhật": 6, "sunday": 6, "sun": 6,
}


def _parse_weekdays(s: str) -> list[int]:
    """
    Parse 'T2,T4,T6' / 't2 t4 t6' / 'all' / 'caltuan' / 'cả tuần' → list[int]
    """
    s_clean = s.strip().lower()
    if s_clean in ("all", "caltuan", "ca tuan", "cả tuần", "catuan", "cả_tuần", "*"):
        return [0, 1, 2, 3, 4, 5, 6]
    # Split by comma/space
    tokens = re.split(r"[,;\s]+", s_clean)
    out: list[int] = []
    for tok in tokens:
        tok = tok.strip().replace(" ", "")
        if not tok:
            continue
        if tok in _WEEKDAY_INPUT:
            wd = _WEEKDAY_INPUT[tok]
            if wd not in out:
                out.append(wd)
        else:
            raise ValueError(
                f"Thứ không hợp lệ: '{tok}'. Dùng: T2, T3, T4, T5, T6, T7, CN "
                "hoặc 'all' / 'cả tuần'"
            )
    if not out:
        raise ValueError("Phải chọn ít nhất 1 thứ")
    return sorted(out)


# ─── Modal /dangky ────────────────────────────────────────────────────────────

class DangKyModal(discord.ui.Modal, title="📅 Đăng ký lịch trực"):
    """
    Modal cho /dangky — 3 ô text:
      1. Giờ bắt đầu (HH:MM)
      2. Giờ kết thúc (HH:MM)
      3. Ngày trực (T2,T4,T6 hoặc 'all' / 'cả tuần')
    """

    start_time_input = discord.ui.TextInput(
        label="Giờ bắt đầu (HH:MM)",
        placeholder="08:00",
        required=True,
        max_length=5,
    )
    end_time_input = discord.ui.TextInput(
        label="Giờ kết thúc (HH:MM, qua đêm OK)",
        placeholder="12:00",
        required=True,
        max_length=5,
    )
    weekdays_input = discord.ui.TextInput(
        label="Thứ trực (T2,T4,T6 hoặc 'cả tuần')",
        placeholder="T2,T4,T6  hoặc  cả tuần",
        required=True,
        max_length=80,
    )

    def __init__(self, cog: "ScheduleCog"):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            start_t = _parse_time(self.start_time_input.value)
            end_t = _parse_time(self.end_time_input.value)
            weekdays = _parse_weekdays(self.weekdays_input.value)
        except ValueError as e:
            await interaction.followup.send(
                embed=build_error_embed(str(e), title="❌ Sai định dạng"),
                ephemeral=True,
            )
            return

        # Validate: start != end (nếu bằng nhau, hoặc là 0 phút hoặc 24h — đều bất thường)
        if start_t == end_t:
            await interaction.followup.send(
                embed=build_error_embed(
                    "Giờ bắt đầu và kết thúc trùng nhau. "
                    "Vui lòng nhập thời gian khác."
                ),
                ephemeral=True,
            )
            return

        crosses_midnight = end_t <= start_t

        # Lưu DB: 1 row per weekday. Logic REPLACE:
        # - Lấy TẤT CẢ entry active của user với SAME start_time (cùng "ca" này)
        # - Ngày có trong input mới → update/keep
        # - Ngày KHÔNG có trong input mới → DEACTIVATE (xóa khỏi lịch)
        # - Ngày mới chưa có → tạo mới
        # → User submit "ca 20:50-23:15: T2, T4, CN" mà DB đang có T2-CN
        #   → T3, T5, T6, T7 sẽ bị deactivate
        # → Các ca khung giờ KHÁC (vd 08:00-12:00) KHÔNG bị động đến.
        async with AsyncSessionLocal() as session:
            existing_rows = await session.execute(
                select(MemberSchedule)
                .where(MemberSchedule.guild_id == interaction.guild_id)
                .where(MemberSchedule.user_id == interaction.user.id)
                .where(MemberSchedule.start_time == start_t)
                .where(MemberSchedule.is_active == True)  # noqa: E712
            )
            existing_map = {s.weekday: s for s in existing_rows.scalars().all()}

            updated: list[int] = []
            created: list[int] = []
            removed: list[int] = []
            new_weekdays_set = set(weekdays)
            for wd in weekdays:
                if wd in existing_map:
                    s = existing_map[wd]
                    s.end_time = end_t
                    s.crosses_midnight = crosses_midnight
                    s.is_active = True
                    s.updated_at = utcnow()
                    updated.append(wd)
                else:
                    new_s = MemberSchedule(
                        guild_id=interaction.guild_id,
                        user_id=interaction.user.id,
                        weekday=wd,
                        start_time=start_t,
                        end_time=end_t,
                        crosses_midnight=crosses_midnight,
                        is_active=True,
                        created_at=utcnow(),
                        updated_at=utcnow(),
                    )
                    session.add(new_s)
                    created.append(wd)

            # Deactivate các ngày cũ KHÔNG còn trong input mới
            for wd, s in existing_map.items():
                if wd not in new_weekdays_set:
                    s.is_active = False
                    s.updated_at = utcnow()
                    removed.append(wd)

            session.add(AuditLog(
                guild_id=interaction.guild_id,
                user_id=interaction.user.id,
                username=str(interaction.user),
                action=(AuditAction.SCHEDULE_UPDATED if (updated or removed) else AuditAction.SCHEDULE_CREATED),
                detail={
                    "start": str(start_t),
                    "end": str(end_t),
                    "crosses_midnight": crosses_midnight,
                    "created_weekdays": created,
                    "updated_weekdays": updated,
                    "removed_weekdays": removed,
                },
                created_at=utcnow(),
            ))
            try:
                await session.commit()
            except IntegrityError as e:
                await session.rollback()
                logger.error(f"IntegrityError save schedule: {e}")
                await interaction.followup.send(
                    embed=build_error_embed("Lưu lịch thất bại do xung đột dữ liệu."),
                    ephemeral=True,
                )
                return

        # Embed xác nhận
        wd_str = ", ".join(WEEKDAY_SHORT[w] for w in weekdays)
        time_str = f"{start_t.strftime('%H:%M')} → {end_t.strftime('%H:%M')}"
        if crosses_midnight:
            time_str += " (qua đêm)"

        embed = discord.Embed(
            title="✅ Đã đăng ký lịch trực",
            description=(
                f"**{discord.utils.escape_markdown(interaction.user.display_name)}**, "
                "lịch trực của bạn đã được lưu:"
            ),
            color=COLOR_SUCCESS,
        )
        embed.add_field(name="🕐 Khung giờ", value=f"`{time_str}`", inline=True)
        embed.add_field(name="📆 Thứ trực", value=f"**{wd_str}**", inline=True)

        status_lines = []
        if created:
            status_lines.append(f"➕ Tạo mới {len(created)} ngày: {', '.join(WEEKDAY_SHORT[w] for w in created)}")
        if updated:
            status_lines.append(f"✏️ Cập nhật {len(updated)} ngày: {', '.join(WEEKDAY_SHORT[w] for w in updated)}")
        if removed:
            status_lines.append(f"🗑️ Gỡ {len(removed)} ngày cũ: {', '.join(WEEKDAY_SHORT[w] for w in removed)}")
        if not status_lines:
            status_lines.append("➕ Tạo mới")
        embed.add_field(name="📝 Trạng thái", value="\n".join(status_lines), inline=False)

        embed.set_footer(text="Bot sẽ tự động nhắc bạn trước mỗi ca trực • /lich nhac để chỉnh mốc nhắc")
        await interaction.followup.send(embed=embed, ephemeral=True)

        # Notify staff channel nếu là UPDATE (sửa lịch) hoặc có gỡ
        if updated or removed:
            await self.cog._notify_staff_schedule_change(
                interaction, "✏️ Sửa lịch trực",
                updated_weekdays=updated,
                time_str=time_str,
                weekdays=weekdays,
                removed_weekdays=removed,
            )


# ─── Cog ──────────────────────────────────────────────────────────────────────

class ScheduleCog(commands.Cog):
    """Cog quản lý lịch trực + báo cáo tuân thủ"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    lich_group = app_commands.Group(name="lich", description="Quản lý lịch trực")

    # ─── /dangky ────────────────────────────────────────────────────────────

    @app_commands.command(name="dangky", description="Đăng ký lịch trực cố định hàng tuần")
    @app_commands.checks.cooldown(rate=5, per=60.0)
    async def dangky(self, interaction: discord.Interaction):
        """Mở modal nhập lịch trực"""
        async with AsyncSessionLocal() as session:
            if not await require_member(interaction, session):
                await send_no_permission(interaction, DutyRole.MEMBER)
                return

            # Check channel restriction
            config = await _get_config(session, interaction.guild_id)
            if config and config.schedule_channel_id and interaction.channel_id != config.schedule_channel_id:
                await interaction.response.send_message(
                    embed=build_error_embed(
                        f"Chỉ được đăng ký trong <#{config.schedule_channel_id}>"
                    ),
                    ephemeral=True,
                )
                return

        await interaction.response.send_modal(DangKyModal(self))

    # ─── /lich xem ──────────────────────────────────────────────────────────

    @lich_group.command(name="xem", description="Xem lịch trực của mình hoặc người khác")
    @app_commands.describe(thanh_vien="Bỏ trống = xem của mình")
    async def lich_xem(
        self,
        interaction: discord.Interaction,
        thanh_vien: discord.Member | None = None,
    ):
        await interaction.response.defer(ephemeral=True)

        async with AsyncSessionLocal() as session:
            if not await require_member(interaction, session):
                await send_no_permission(interaction, DutyRole.MEMBER)
                return

            target = thanh_vien or interaction.user
            rows = await session.execute(
                select(MemberSchedule)
                .where(MemberSchedule.guild_id == interaction.guild_id)
                .where(MemberSchedule.user_id == target.id)
                .where(MemberSchedule.is_active == True)  # noqa: E712
                .order_by(MemberSchedule.weekday.asc(), MemberSchedule.start_time.asc())
            )
            schedules = rows.scalars().all()

        embed = _build_schedule_embed(target, schedules)
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ─── /lich xoa ──────────────────────────────────────────────────────────

    @lich_group.command(name="xoa", description="Xoá 1 entry lịch trực theo ID")
    @app_commands.describe(id="ID entry (xem qua /lich xem)")
    async def lich_xoa(self, interaction: discord.Interaction, id: int):
        await interaction.response.defer(ephemeral=True)

        async with AsyncSessionLocal() as session:
            row = await session.execute(
                select(MemberSchedule)
                .where(MemberSchedule.id == id)
                .where(MemberSchedule.guild_id == interaction.guild_id)
            )
            sched = row.scalar_one_or_none()
            if not sched:
                await interaction.followup.send(
                    embed=build_error_embed(f"Không tìm thấy lịch ID `{id}` trong server này."),
                    ephemeral=True,
                )
                return

            # Chỉ chủ lịch HOẶC admin được xoá
            is_owner = sched.user_id == interaction.user.id
            if not is_owner:
                async with AsyncSessionLocal() as s2:
                    if not await require_mod(interaction, s2):
                        await send_no_permission(interaction, DutyRole.MOD)
                        return

            snapshot = {
                "schedule_id": sched.id,
                "user_id": str(sched.user_id),
                "weekday": sched.weekday,
                "start": str(sched.start_time),
                "end": str(sched.end_time),
            }
            await session.delete(sched)
            session.add(AuditLog(
                guild_id=interaction.guild_id,
                user_id=interaction.user.id,
                username=str(interaction.user),
                action=AuditAction.SCHEDULE_DELETED,
                detail=snapshot,
                created_at=utcnow(),
            ))
            await session.commit()

        await interaction.followup.send(
            embed=build_success_embed(
                f"Đã xoá entry **#{id}** "
                f"({WEEKDAY_LABELS[snapshot['weekday']]} "
                f"{snapshot['start']}–{snapshot['end']})."
            ),
            ephemeral=True,
        )
        # Notify staff channel
        await self._notify_staff_schedule_change(
            interaction, "🗑️ Xoá lịch trực",
            updated_weekdays=[snapshot["weekday"]],
            time_str=f"{snapshot['start']}–{snapshot['end']}",
            weekdays=[snapshot["weekday"]],
        )

    # ─── /lich nhac ─────────────────────────────────────────────────────────

    @lich_group.command(name="nhac", description="Tuỳ chỉnh mốc nhắc trước ca (vd: 60,30,5)")
    @app_commands.describe(
        moc="Các mốc nhắc trước ca (phút), cách nhau dấu phẩy. Bỏ trống = dùng default",
    )
    async def lich_nhac(
        self,
        interaction: discord.Interaction,
        moc: str | None = None,
    ):
        await interaction.response.defer(ephemeral=True)

        # Parse mốc nhắc
        custom_offsets: list[int] | None
        if moc is None or moc.strip() == "":
            custom_offsets = None  # reset về default
        else:
            try:
                custom_offsets = sorted({
                    int(x.strip()) for x in moc.split(",") if x.strip()
                }, reverse=True)
                for n in custom_offsets:
                    if not (0 < n <= 240):
                        raise ValueError(f"Mốc {n} phải từ 1-240 phút")
            except ValueError as e:
                await interaction.followup.send(
                    embed=build_error_embed(
                        f"Mốc không hợp lệ: {e}. Ví dụ đúng: `60,30,5`"
                    ),
                    ephemeral=True,
                )
                return

        async with AsyncSessionLocal() as session:
            rows = await session.execute(
                select(MemberSchedule)
                .where(MemberSchedule.guild_id == interaction.guild_id)
                .where(MemberSchedule.user_id == interaction.user.id)
            )
            schedules = rows.scalars().all()
            if not schedules:
                await interaction.followup.send(
                    embed=build_error_embed("Bạn chưa có lịch trực. Dùng `/dangky` trước."),
                    ephemeral=True,
                )
                return

            for s in schedules:
                s.custom_remind_offsets = custom_offsets
                s.updated_at = utcnow()
            await session.commit()

        if custom_offsets is None:
            msg = "Đã reset về mốc nhắc **mặc định** của server."
        else:
            msg = f"Đã đặt mốc nhắc: **{', '.join(map(str, custom_offsets))} phút trước ca**."

        await interaction.followup.send(
            embed=build_success_embed(msg, title="🔔 Cập nhật mốc nhắc"),
            ephemeral=True,
        )

    # ─── /lich tatca (mod) ──────────────────────────────────────────────────

    @lich_group.command(name="tatca", description="Xem lịch trực toàn server (Mod+)")
    async def lich_tatca(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        async with AsyncSessionLocal() as session:
            if not await require_mod(interaction, session):
                await send_no_permission(interaction, DutyRole.MOD)
                return

            rows = await session.execute(
                select(MemberSchedule)
                .where(MemberSchedule.guild_id == interaction.guild_id)
                .where(MemberSchedule.is_active == True)  # noqa: E712
                .order_by(MemberSchedule.weekday.asc(), MemberSchedule.start_time.asc())
            )
            schedules = rows.scalars().all()

        embed = discord.Embed(
            title=f"📅 Lịch trực toàn server — {discord.utils.escape_markdown(interaction.guild.name)}",
            color=COLOR_INFO,
        )

        if not schedules:
            embed.description = "_Chưa có ai đăng ký lịch_"
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        # Group theo weekday
        by_weekday: dict[int, list[MemberSchedule]] = {}
        for s in schedules:
            by_weekday.setdefault(s.weekday, []).append(s)

        for wd in sorted(by_weekday.keys()):
            entries = by_weekday[wd]
            lines = []
            for s in entries:
                member = interaction.guild.get_member(s.user_id)
                name = member.display_name if member else f"User#{s.user_id}"
                cross = " 🌙" if s.crosses_midnight else ""
                lines.append(
                    f"`{s.start_time.strftime('%H:%M')}–{s.end_time.strftime('%H:%M')}`"
                    f"{cross} • {discord.utils.escape_markdown(name)} `(#{s.id})`"
                )
            embed.add_field(
                name=f"📆 {WEEKDAY_LABELS[wd]} ({len(entries)} người)",
                value="\n".join(lines)[:1024],
                inline=False,
            )

        embed.set_footer(text=f"Tổng {len(schedules)} entry • {len(by_weekday)} ngày trong tuần có lịch")
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ─── /lich tongket ──────────────────────────────────────────────────────

    @lich_group.command(name="tongket", description="Báo cáo tuân thủ lịch trực")
    @app_commands.describe(
        ky="Kỳ thống kê",
        thanh_vien="Bỏ trống = tổng kết toàn server (Mod+)",
    )
    @app_commands.choices(ky=make_period_choices())
    async def lich_tongket(
        self,
        interaction: discord.Interaction,
        ky: str = "week",
        thanh_vien: discord.Member | None = None,
    ):
        await interaction.response.defer(ephemeral=True)

        async with AsyncSessionLocal() as session:
            # Quyền: xem của mình → MEMBER; xem all hoặc người khác → MOD
            target_other = thanh_vien is not None and thanh_vien.id != interaction.user.id
            need_all = thanh_vien is None  # tổng toàn server
            if target_other or need_all:
                if not await require_mod(interaction, session):
                    await send_no_permission(interaction, DutyRole.MOD)
                    return
            else:
                if not await require_member(interaction, session):
                    await send_no_permission(interaction, DutyRole.MEMBER)
                    return

            cfg = await _get_config(session, interaction.guild_id)
            tz = (cfg.timezone if cfg else "Asia/Ho_Chi_Minh") or "Asia/Ho_Chi_Minh"
            try:
                start, end = get_period_range(ky, tz_str=tz)
            except ValueError as e:
                await interaction.followup.send(
                    embed=build_error_embed(str(e)), ephemeral=True
                )
                return

            target_id = thanh_vien.id if thanh_vien else None
            entries = await compute_compliance(
                session, interaction.guild_id, target_id, start, end, tz,
            )

        embed = _build_compliance_embed(
            interaction.guild, entries, ky, target=thanh_vien,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ─── Helper: notify staff channel khi sửa/xoá lịch ──────────────────────

    async def _notify_staff_schedule_change(
        self,
        interaction: discord.Interaction,
        title: str,
        updated_weekdays: list[int],
        time_str: str,
        weekdays: list[int],
        removed_weekdays: list[int] | None = None,
    ):
        """Gửi embed sang staff channel để admin/mod biết có sửa lịch"""
        async with AsyncSessionLocal() as session:
            cfg = await _get_config(session, interaction.guild_id)
        if not cfg or not cfg.staff_channel_id:
            return
        ch = interaction.guild.get_channel(cfg.staff_channel_id) if interaction.guild else None
        if not ch:
            return

        wd_str = ", ".join(WEEKDAY_SHORT[w] for w in weekdays) if weekdays else "(không có)"
        embed = discord.Embed(
            title=title,
            description=(
                f"**{discord.utils.escape_markdown(interaction.user.display_name)}** "
                "vừa thay đổi lịch trực."
            ),
            color=0xFEE75C,
        )
        embed.add_field(name="👤 Member", value=interaction.user.mention, inline=True)
        embed.add_field(name="🕐 Khung giờ", value=f"`{time_str}`", inline=True)
        embed.add_field(name="📆 Ngày hiện tại", value=f"**{wd_str}**", inline=True)
        if removed_weekdays:
            removed_str = ", ".join(WEEKDAY_SHORT[w] for w in removed_weekdays)
            embed.add_field(
                name="🗑️ Đã gỡ ngày",
                value=f"~~{removed_str}~~",
                inline=False,
            )
        embed.set_footer(text=f"Cập nhật lúc {utcnow().strftime('%H:%M %d/%m/%Y')} UTC")
        try:
            await ch.send(embed=embed)
        except discord.HTTPException as e:
            logger.warning(f"Không gửi được notif staff channel: {e}")


# ─── Helpers build embed ─────────────────────────────────────────────────────

async def _get_config(session, guild_id: int) -> GuildConfig | None:
    r = await session.execute(
        select(GuildConfig).where(GuildConfig.guild_id == guild_id)
    )
    return r.scalar_one_or_none()


def _build_schedule_embed(
    target: discord.Member | discord.User,
    schedules: list[MemberSchedule],
) -> discord.Embed:
    """Embed liệt kê lịch trực của 1 user (group theo thứ)"""
    embed = discord.Embed(
        title=f"📅 Lịch trực — {discord.utils.escape_markdown(target.display_name)}",
        color=COLOR_INFO,
    )
    if not schedules:
        embed.description = (
            "_Chưa có lịch nào_\n\n"
            "Dùng `/dangky` để đăng ký lịch trực cố định hàng tuần."
        )
        return embed

    # Group by weekday
    by_wd: dict[int, list[MemberSchedule]] = {}
    for s in schedules:
        by_wd.setdefault(s.weekday, []).append(s)

    total_minutes = 0
    for wd in sorted(by_wd.keys()):
        entries = by_wd[wd]
        lines = []
        for s in entries:
            cross = " 🌙" if s.crosses_midnight else ""
            # Tính minutes: nếu cross-midnight thì +24h
            if s.crosses_midnight or s.end_time <= s.start_time:
                start_dt = datetime.combine(date.today(), s.start_time)
                end_dt = datetime.combine(date.today() + timedelta(days=1), s.end_time)
            else:
                start_dt = datetime.combine(date.today(), s.start_time)
                end_dt = datetime.combine(date.today(), s.end_time)
            mins = int((end_dt - start_dt).total_seconds() // 60)
            total_minutes += mins
            offsets_str = ""
            if s.custom_remind_offsets:
                offsets_str = f" • 🔔 {','.join(map(str, s.custom_remind_offsets))}p"
            lines.append(
                f"`#{s.id}` `{s.start_time.strftime('%H:%M')}–{s.end_time.strftime('%H:%M')}`"
                f"{cross} ({mins}p){offsets_str}"
            )
        embed.add_field(
            name=f"📆 {WEEKDAY_LABELS[wd]}",
            value="\n".join(lines),
            inline=False,
        )

    h, m = divmod(total_minutes, 60)
    total_str = f"{h} giờ {m} phút" if h else f"{m} phút"
    embed.set_footer(text=f"Tổng {len(schedules)} ca/tuần • {total_str}/tuần")
    return embed


def _build_compliance_embed(
    guild: discord.Guild | None,
    entries: list,
    period: str,
    target: discord.Member | None = None,
) -> discord.Embed:
    """
    Embed báo cáo tuân thủ. Chi tiết: từng user, từng ca, status.
    """
    period_label = get_period_label(period)
    title_target = f" — {target.display_name}" if target else ""
    embed = discord.Embed(
        title=f"📊 Tuân thủ lịch trực — {period_label}{title_target}",
        color=COLOR_INFO,
    )

    if not entries:
        embed.description = "_Không có dữ liệu trong khoảng thời gian này_"
        return embed

    # Đếm theo status
    counters = {
        STATUS_ON_TIME: 0,
        STATUS_LATE: 0,
        STATUS_MISSED: 0,
        STATUS_OFF_SCHEDULE: 0,
        STATUS_ON_LEAVE: 0,
    }
    for e in entries:
        counters[e.status] = counters.get(e.status, 0) + 1

    # Tỷ lệ đúng giờ chỉ tính trên ca PHẢI trực (loại ca nghỉ phép đã duyệt)
    countable = sum(
        counters[s] for s in (STATUS_ON_TIME, STATUS_LATE, STATUS_MISSED)
    )
    rate = (counters[STATUS_ON_TIME] / countable * 100) if countable else 0
    total_in_schedule = countable + counters[STATUS_ON_LEAVE]

    embed.add_field(
        name="🎯 Tỷ lệ đúng giờ",
        value=f"**{rate:.0f}%** ({counters[STATUS_ON_TIME]}/{total_in_schedule})",
        inline=True,
    )
    embed.add_field(
        name="📈 Phân loại",
        value=(
            f"✅ Đúng giờ: **{counters[STATUS_ON_TIME]}**\n"
            f"⏰ Thiếu giờ: **{counters[STATUS_LATE]}**\n"
            f"🚫 Vắng: **{counters[STATUS_MISSED]}**\n"
            f"🆓 Ngoài lịch: **{counters[STATUS_OFF_SCHEDULE]}**\n"
            f"🏖 Nghỉ phép: **{counters[STATUS_ON_LEAVE]}**"
        ),
        inline=True,
    )

    # Group by user → show top 10 entries detail
    by_user: dict[int, list] = {}
    for e in entries:
        by_user.setdefault(e.user_id, []).append(e)

    SHOW_USERS = 8
    user_keys = sorted(by_user.keys(), key=lambda uid: by_user[uid][0].username.lower())
    for uid in user_keys[:SHOW_USERS]:
        u_entries = by_user[uid]
        username = u_entries[0].username
        lines = []
        # Tối đa 6 dòng / user trong embed
        for e in u_entries[:6]:
            icon = {
                STATUS_ON_TIME: "✅",
                STATUS_LATE: "⏰",
                STATUS_MISSED: "🚫",
                STATUS_OFF_SCHEDULE: "🆓",
                STATUS_ON_LEAVE: "🏖",
            }.get(e.status, "•")
            if e.schedule:
                wd_label = WEEKDAY_SHORT[e.schedule.weekday]
                slot = (
                    f"{wd_label} "
                    f"{e.schedule.start_time.strftime('%H:%M')}-{e.schedule.end_time.strftime('%H:%M')}"
                )
            else:
                slot = "ngoài lịch"
            extra = f" ({e.overlap_minutes}p)" if e.overlap_minutes else ""
            lines.append(f"{icon} `{e.occurrence_date.strftime('%d/%m')}` {slot}{extra}")
        if len(u_entries) > 6:
            lines.append(f"_... +{len(u_entries) - 6} ca khác_")
        embed.add_field(
            name=f"👤 {discord.utils.escape_markdown(username)}",
            value="\n".join(lines),
            inline=False,
        )

    if len(user_keys) > SHOW_USERS:
        embed.add_field(
            name="⋯",
            value=f"_Còn **{len(user_keys) - SHOW_USERS}** thành viên khác. Xem chi tiết trên web dashboard._",
            inline=False,
        )

    embed.set_footer(text=f"Tổng {len(entries)} ca / {len(user_keys)} thành viên")
    return embed


async def setup(bot: commands.Bot):
    await bot.add_cog(ScheduleCog(bot))
