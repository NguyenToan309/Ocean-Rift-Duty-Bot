"""
staff.py — Cog quản lý chức vụ nhân sự y tế.

Slash commands:
  /nhansu list [group]            — Liệt kê nhân sự (filter theo nhóm)
  /nhansu info @user              — Xem chi tiết 1 nhân sự
  /nhansu set @user position note — Đổi chức vụ (Admin, bắt buộc note)
  /nhansu add @user position note — Thêm nhân sự mới (Admin, bắt buộc note)
  /nhansu remove @user note       — Gỡ nhân sự (Admin, soft delete, bắt buộc note)

Strict audit policy: mọi mutation đều phải có `lydo` (≥3 chars).
"""
from __future__ import annotations
import logging
from typing import List

import discord
from discord.ext import commands
from discord import app_commands
from sqlalchemy import select

from models.base import AsyncSessionLocal
from models.staff_member import (
    StaffMember, StaffPosition, POSITION_METADATA, GROUP_METADATA,
    is_valid_position,
)
from models.audit_log import AuditLog, AuditAction
from bot.utils.permissions import (
    require_admin, require_mod, send_no_permission, DutyRole,
)
from bot.utils.embed_builder import (
    build_success_embed, build_error_embed, build_info_embed,
)
from bot.utils.time_utils import utcnow
from web.utils.discord_role_sync import sync_staff_position_role


def _format_sync_result(r: dict | None) -> str:
    """Format kết quả role sync để hiển thị trong embed."""
    if not r:
        return ""
    parts = []
    if r.get("added_role_id"):
        parts.append(f"• ✅ Đã cấp role <@&{r['added_role_id']}>")
    if r.get("removed_role_id"):
        parts.append(f"• ⛔ Đã gỡ role <@&{r['removed_role_id']}>")
    if r.get("skipped_reason"):
        parts.append(f"• ⓘ {r['skipped_reason']}")
    if r.get("errors"):
        for err in r["errors"][:3]:
            parts.append(f"• ⚠️ {err}")
    return "\n".join(parts)

logger = logging.getLogger(__name__)


# ─── Autocomplete: position choices ──────────────────────────────────────────

POSITION_CHOICES = [
    app_commands.Choice(name=f"{POSITION_METADATA[p]['icon']} {POSITION_METADATA[p]['label']}", value=p)
    for p in sorted(StaffPosition.ALL, key=lambda x: POSITION_METADATA[x]["level"])
]

GROUP_CHOICES = [
    app_commands.Choice(name="🏥 Lãnh đạo", value="LANH_DAO"),
    app_commands.Choice(name="🩺 Y tế", value="Y_TE"),
    app_commands.Choice(name="🎓 Đào tạo", value="DAO_TAO"),
]


def _format_staff_line(m: StaffMember) -> str:
    meta = POSITION_METADATA.get(m.position, {})
    icon = meta.get("icon", "•")
    label = meta.get("label", m.position)
    inactive = " *(đã nghỉ)*" if not m.is_active else ""
    return f"{icon} **{m.username}** — {label}{inactive}"


class StaffCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    nhansu_group = app_commands.Group(
        name="nhansu",
        description="Quản lý chức vụ nhân sự y tế",
    )

    # ─── /nhansu list ────────────────────────────────────────────────────────

    @nhansu_group.command(name="list", description="Liệt kê nhân sự trong server")
    @app_commands.describe(nhom="Filter theo nhóm (để trống = tất cả)")
    @app_commands.choices(nhom=GROUP_CHOICES)
    async def list_cmd(
        self,
        interaction: discord.Interaction,
        nhom: app_commands.Choice[str] | None = None,
    ):
        await interaction.response.defer(ephemeral=True)
        async with AsyncSessionLocal() as session:
            if not await require_mod(interaction, session):
                await send_no_permission(interaction, DutyRole.MOD)
                return

            q = select(StaffMember).where(StaffMember.guild_id == interaction.guild_id)
            q = q.where(StaffMember.is_active == True)  # noqa: E712
            rows = await session.execute(q)
            members = list(rows.scalars().all())

        # Filter group
        if nhom:
            members = [m for m in members if POSITION_METADATA.get(m.position, {}).get("group") == nhom.value]

        if not members:
            await interaction.followup.send(
                embed=build_info_embed("Chưa có nhân sự nào trong danh sách."),
                ephemeral=True,
            )
            return

        # Sort theo level
        members.sort(key=lambda m: (POSITION_METADATA.get(m.position, {}).get("level", 99), m.username))

        # Group by group code
        groups: dict[str, list[StaffMember]] = {}
        for m in members:
            g = POSITION_METADATA.get(m.position, {}).get("group", "OTHER")
            groups.setdefault(g, []).append(m)

        embed = discord.Embed(
            title=f"👥 Danh sách nhân sự ({len(members)} người)",
            color=0x0F766E,
        )
        for group_code in ("LANH_DAO", "Y_TE", "DAO_TAO"):
            if group_code not in groups:
                continue
            meta = GROUP_METADATA[group_code]
            lines = [_format_staff_line(m) for m in groups[group_code]]
            # Discord embed field max 1024 chars
            value = "\n".join(lines)
            if len(value) > 1000:
                value = value[:1000] + "\n..."
            embed.add_field(
                name=f"{meta['icon']} {meta['label']} ({len(groups[group_code])})",
                value=value,
                inline=False,
            )

        embed.set_footer(text="Dùng /nhansu info @user để xem chi tiết")
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ─── /nhansu info ────────────────────────────────────────────────────────

    @nhansu_group.command(name="info", description="Xem chi tiết 1 nhân sự")
    @app_commands.describe(nguoi="Nhân sự cần xem")
    async def info_cmd(
        self,
        interaction: discord.Interaction,
        nguoi: discord.Member,
    ):
        await interaction.response.defer(ephemeral=True)
        async with AsyncSessionLocal() as session:
            if not await require_mod(interaction, session):
                # Member tự xem mình thì OK
                if interaction.user.id != nguoi.id:
                    await send_no_permission(interaction, DutyRole.MOD)
                    return

            row = await session.execute(
                select(StaffMember)
                .where(StaffMember.guild_id == interaction.guild_id)
                .where(StaffMember.user_id == nguoi.id)
            )
            m = row.scalar_one_or_none()

        if not m:
            await interaction.followup.send(
                embed=build_info_embed(
                    f"**{nguoi.display_name}** chưa có trong danh sách nhân sự.\n"
                    f"Admin có thể thêm bằng `/nhansu add`."
                ),
                ephemeral=True,
            )
            return

        meta = POSITION_METADATA.get(m.position, {})
        color_hex = meta.get("color", "#5865F2").lstrip("#")
        try:
            color = int(color_hex, 16)
        except ValueError:
            color = 0x5865F2

        embed = discord.Embed(
            title=f"{meta.get('icon', '👤')} {m.username}",
            description=f"**Chức vụ:** {meta.get('label', m.position)}",
            color=color,
        )
        if nguoi.display_avatar:
            embed.set_thumbnail(url=nguoi.display_avatar.url)
        embed.add_field(name="Discord ID", value=f"`{m.user_id}`", inline=True)
        embed.add_field(
            name="Trạng thái",
            value="🟢 Đang hoạt động" if m.is_active else "⚪ Đã nghỉ",
            inline=True,
        )
        if m.joined_at:
            embed.add_field(
                name="Ngày vào",
                value=m.joined_at.strftime("%d/%m/%Y"),
                inline=True,
            )
        if m.note:
            embed.add_field(name="Ghi chú", value=m.note[:1000], inline=False)
        embed.set_footer(text=f"Cập nhật: {m.updated_at.strftime('%d/%m/%Y %H:%M')}")
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ─── /nhansu add ─────────────────────────────────────────────────────────

    @nhansu_group.command(name="add", description="Thêm nhân sự mới (Admin)")
    @app_commands.describe(
        nguoi="Nhân sự cần thêm",
        chucvu="Chức vụ",
        ngay_vao_lam="Ngày vào làm — định dạng DD/MM/YYYY (optional)",
        lydo="Lý do thêm (BẮT BUỘC ≥3 ký tự)",
    )
    @app_commands.choices(chucvu=POSITION_CHOICES)
    async def add_cmd(
        self,
        interaction: discord.Interaction,
        nguoi: discord.Member,
        chucvu: app_commands.Choice[str],
        lydo: str,
        ngay_vao_lam: str | None = None,
    ):
        await interaction.response.defer(ephemeral=True)

        if len(lydo.strip()) < 3:
            await interaction.followup.send(
                embed=build_error_embed("Lý do bắt buộc ≥3 ký tự."),
                ephemeral=True,
            )
            return

        # Parse ngay_vao_lam DD/MM/YYYY → datetime aware (timezone của guild)
        joined_at_dt = None
        if ngay_vao_lam:
            try:
                from datetime import datetime as _dt
                joined_at_dt = _dt.strptime(ngay_vao_lam.strip(), "%d/%m/%Y")
                # Localize bằng UTC để consistency với column DateTime(timezone=True)
                from datetime import timezone as _tz
                joined_at_dt = joined_at_dt.replace(tzinfo=_tz.utc)
            except ValueError:
                await interaction.followup.send(
                    embed=build_error_embed(
                        f"Ngày vào làm sai định dạng (`{ngay_vao_lam}`). Dùng DD/MM/YYYY, vd: `01/06/2026`."
                    ),
                    ephemeral=True,
                )
                return

        async with AsyncSessionLocal() as session:
            if not await require_admin(interaction, session):
                await send_no_permission(interaction, DutyRole.ADMIN)
                return

            existing = await session.execute(
                select(StaffMember)
                .where(StaffMember.guild_id == interaction.guild_id)
                .where(StaffMember.user_id == nguoi.id)
            )
            if existing.scalar_one_or_none():
                await interaction.followup.send(
                    embed=build_error_embed(
                        f"**{nguoi.display_name}** đã có trong danh sách. "
                        f"Dùng `/nhansu set` để đổi chức vụ."
                    ),
                    ephemeral=True,
                )
                return

            m = StaffMember(
                guild_id=interaction.guild_id,
                user_id=nguoi.id,
                username=nguoi.display_name,
                position=chucvu.value,
                joined_at=joined_at_dt,
                is_active=True,
            )
            session.add(m)

            session.add(AuditLog(
                guild_id=interaction.guild_id,
                user_id=interaction.user.id,
                username=str(interaction.user),
                action=AuditAction.STAFF_ADDED,
                detail={
                    "staff_user_id": str(nguoi.id),
                    "staff_username": nguoi.display_name,
                    "position": chucvu.value,
                    "joined_at": joined_at_dt.isoformat() if joined_at_dt else None,
                    "note": lydo.strip(),
                    "via": "discord",
                },
                created_at=utcnow(),
            ))

            # Auto-sync Discord role
            sync_result = await sync_staff_position_role(
                session=session,
                guild_id=interaction.guild_id,
                user_id=nguoi.id,
                new_position=chucvu.value,
                old_position=None,
                actor_id=interaction.user.id,
                actor_username=str(interaction.user),
                reason=f"/nhansu add: {lydo.strip()}",
            )

            await session.commit()

        meta = POSITION_METADATA[chucvu.value]
        sync_text = _format_sync_result(sync_result)
        await interaction.followup.send(
            embed=build_success_embed(
                f"Đã thêm **{nguoi.display_name}** vào danh sách:\n"
                f"• Chức vụ: {meta['icon']} **{meta['label']}**\n"
                f"• Lý do: _{lydo.strip()}_"
                + (f"\n\n**Auto-sync role Discord:**\n{sync_text}" if sync_text else "")
            ),
            ephemeral=True,
        )

    # ─── /nhansu set ─────────────────────────────────────────────────────────

    @nhansu_group.command(name="set", description="Đổi chức vụ nhân sự (Admin)")
    @app_commands.describe(
        nguoi="Nhân sự cần đổi",
        chucvu="Chức vụ mới",
        lydo="Lý do đổi (BẮT BUỘC ≥3 ký tự)",
    )
    @app_commands.choices(chucvu=POSITION_CHOICES)
    async def set_cmd(
        self,
        interaction: discord.Interaction,
        nguoi: discord.Member,
        chucvu: app_commands.Choice[str],
        lydo: str,
    ):
        await interaction.response.defer(ephemeral=True)

        if len(lydo.strip()) < 3:
            await interaction.followup.send(
                embed=build_error_embed("Lý do bắt buộc ≥3 ký tự."),
                ephemeral=True,
            )
            return

        async with AsyncSessionLocal() as session:
            if not await require_admin(interaction, session):
                await send_no_permission(interaction, DutyRole.ADMIN)
                return

            row = await session.execute(
                select(StaffMember)
                .where(StaffMember.guild_id == interaction.guild_id)
                .where(StaffMember.user_id == nguoi.id)
            )
            m = row.scalar_one_or_none()
            if not m:
                # Auto-create nếu chưa có (tiện hơn cho admin)
                m = StaffMember(
                    guild_id=interaction.guild_id,
                    user_id=nguoi.id,
                    username=nguoi.display_name,
                    position=chucvu.value,
                    is_active=True,
                )
                session.add(m)
                action = AuditAction.STAFF_ADDED
                before = None
            else:
                before = {"position": m.position}
                m.position = chucvu.value
                m.username = nguoi.display_name  # Sync display name
                action = AuditAction.STAFF_UPDATED

            session.add(AuditLog(
                guild_id=interaction.guild_id,
                user_id=interaction.user.id,
                username=str(interaction.user),
                action=action,
                detail={
                    "staff_user_id": str(nguoi.id),
                    "staff_username": nguoi.display_name,
                    "changes": {
                        "position": {"before": before.get("position") if before else None, "after": chucvu.value},
                    } if before else None,
                    "position": chucvu.value,
                    "note": lydo.strip(),
                    "via": "discord",
                },
                created_at=utcnow(),
            ))

            # Auto-sync Discord role nếu position đổi (hoặc lần đầu set)
            old_pos_for_sync = before.get("position") if before else None
            sync_result = None
            if old_pos_for_sync != chucvu.value:
                sync_result = await sync_staff_position_role(
                    session=session,
                    guild_id=interaction.guild_id,
                    user_id=nguoi.id,
                    new_position=chucvu.value,
                    old_position=old_pos_for_sync,
                    actor_id=interaction.user.id,
                    actor_username=str(interaction.user),
                    reason=f"/nhansu set: {lydo.strip()}",
                )

            await session.commit()

        meta = POSITION_METADATA[chucvu.value]
        sync_text = _format_sync_result(sync_result)
        await interaction.followup.send(
            embed=build_success_embed(
                f"Đã cập nhật **{nguoi.display_name}**:\n"
                f"• Chức vụ: {meta['icon']} **{meta['label']}**\n"
                f"• Lý do: _{lydo.strip()}_"
                + (f"\n\n**Auto-sync role Discord:**\n{sync_text}" if sync_text else "")
            ),
            ephemeral=True,
        )

    # ─── /nhansu remove ──────────────────────────────────────────────────────

    @nhansu_group.command(name="remove", description="Gỡ nhân sự khỏi danh sách (Admin, soft delete)")
    @app_commands.describe(
        nguoi="Nhân sự cần gỡ",
        lydo="Lý do (BẮT BUỘC ≥3 ký tự, vd: nghỉ việc, chuyển công tác)",
    )
    async def remove_cmd(
        self,
        interaction: discord.Interaction,
        nguoi: discord.Member,
        lydo: str,
    ):
        await interaction.response.defer(ephemeral=True)

        if len(lydo.strip()) < 3:
            await interaction.followup.send(
                embed=build_error_embed("Lý do bắt buộc ≥3 ký tự."),
                ephemeral=True,
            )
            return

        async with AsyncSessionLocal() as session:
            if not await require_admin(interaction, session):
                await send_no_permission(interaction, DutyRole.ADMIN)
                return

            row = await session.execute(
                select(StaffMember)
                .where(StaffMember.guild_id == interaction.guild_id)
                .where(StaffMember.user_id == nguoi.id)
            )
            m = row.scalar_one_or_none()
            if not m:
                await interaction.followup.send(
                    embed=build_error_embed(f"**{nguoi.display_name}** không có trong danh sách."),
                    ephemeral=True,
                )
                return

            snapshot = {
                "position": m.position,
                "department": m.department,
                "username": m.username,
            }
            old_position_for_sync = m.position
            m.is_active = False

            session.add(AuditLog(
                guild_id=interaction.guild_id,
                user_id=interaction.user.id,
                username=str(interaction.user),
                action=AuditAction.STAFF_REMOVED,
                detail={
                    "staff_user_id": str(nguoi.id),
                    "snapshot": snapshot,
                    "note": lydo.strip(),
                    "via": "discord",
                    "hard_delete": False,
                },
                created_at=utcnow(),
            ))

            # Auto-gỡ role Discord
            sync_result = await sync_staff_position_role(
                session=session,
                guild_id=interaction.guild_id,
                user_id=nguoi.id,
                new_position=None,
                old_position=old_position_for_sync,
                actor_id=interaction.user.id,
                actor_username=str(interaction.user),
                reason=f"/nhansu remove: {lydo.strip()}",
            )

            await session.commit()

        sync_text = _format_sync_result(sync_result)
        await interaction.followup.send(
            embed=build_success_embed(
                f"Đã gỡ **{nguoi.display_name}** khỏi danh sách hoạt động.\n"
                f"_(Vẫn giữ lịch sử trong audit log)_\n"
                f"• Lý do: _{lydo.strip()}_"
                + (f"\n\n**Auto-sync role Discord:**\n{sync_text}" if sync_text else "")
            ),
            ephemeral=True,
        )


class SyncCog(commands.Cog):
    """Owner-only command để force-sync slash commands không cần restart."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="sync", description="[Owner] Force-sync slash commands cho guild này")
    async def sync_cmd(self, interaction: discord.Interaction):
        # Chỉ bot owner mới dùng được
        app_info = await self.bot.application_info()
        if interaction.user.id != app_info.owner.id:
            await interaction.response.send_message(
                embed=build_error_embed("Chỉ bot owner mới dùng được lệnh này."),
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)
        try:
            guild_obj = discord.Object(id=interaction.guild_id)
            self.bot.tree.copy_global_to(guild=guild_obj)
            synced = await self.bot.tree.sync(guild=guild_obj)
            cmd_names = sorted([c.name for c in synced])
            await interaction.followup.send(
                embed=build_success_embed(
                    f"Đã sync **{len(synced)}** slash commands cho guild này.\n\n"
                    f"**Commands:** `{'`, `'.join(cmd_names)}`\n\n"
                    f"_(Bấm Ctrl+R trong Discord để refresh client nếu chưa thấy)_"
                ),
                ephemeral=True,
            )
        except Exception as e:
            await interaction.followup.send(
                embed=build_error_embed(f"Sync lỗi: {type(e).__name__}: {e}"),
                ephemeral=True,
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(StaffCog(bot))
    await bot.add_cog(SyncCog(bot))
