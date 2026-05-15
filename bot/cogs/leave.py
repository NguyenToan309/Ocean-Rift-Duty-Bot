"""
leave.py — Cog xử lý /xinnghi (xin nghỉ phép) và /xinoutnganh (xin out hẳn).

Workflow chung:
  1. Member dùng lệnh → modal nhập ngày + lý do
  2. Bot tạo embed trong leave_channel với 2 emoji react ✅/❌
  3. Bot DM xác nhận cho member
  4. Staff (Admin/Mod) react ✅ hoặc ❌
  5. Bot update DB → DM kết quả cho member → ghi audit log
  6. Nếu approved + RESIGN → đánh dấu user out (không nhắc nữa)
  7. Nếu approved + LEAVE → bot skip remind trong khoảng nghỉ
"""
from __future__ import annotations
import logging
from datetime import datetime, date, timedelta

import discord
from discord.ext import commands
from discord import app_commands
from sqlalchemy import select

from sqlalchemy import delete

from models.base import AsyncSessionLocal
from models.guild import GuildConfig
from models.leave import LeaveRequest, LeaveRequestType, LeaveRequestStatus
from models.schedule import MemberSchedule, OnboardingLog
from models.audit_log import AuditLog, AuditAction
from bot.utils.permissions import (
    require_member, require_mod, send_no_permission, DutyRole, check_permission,
)
from bot.utils.embed_builder import (
    build_error_embed, build_success_embed, build_info_embed,
    COLOR_INFO, COLOR_SUCCESS, COLOR_ERROR, COLOR_WARNING,
)
from bot.utils.time_utils import utcnow

logger = logging.getLogger(__name__)

EMOJI_APPROVE = "✅"
EMOJI_REJECT = "❌"


# ─── Parse date input ────────────────────────────────────────────────────────

def _parse_date(s: str) -> date:
    """Parse 'DD/MM/YYYY' hoặc 'DD/MM' (year hiện tại) → date"""
    s = s.strip()
    parts = s.replace("-", "/").replace(".", "/").split("/")
    if len(parts) == 2:
        d, m = int(parts[0]), int(parts[1])
        y = datetime.now().year
    elif len(parts) == 3:
        d, m, y = int(parts[0]), int(parts[1]), int(parts[2])
        if y < 100:
            y += 2000
    else:
        raise ValueError(f"Ngày không hợp lệ: '{s}'. Dùng DD/MM/YYYY")
    try:
        return date(y, m, d)
    except ValueError as e:
        raise ValueError(f"Ngày không hợp lệ: {e}")


# ─── Modals ──────────────────────────────────────────────────────────────────

class XinNghiModal(discord.ui.Modal, title="🏖 Đơn xin nghỉ phép"):
    """Modal nhập ngày bắt đầu, ngày kết thúc, lý do nghỉ"""

    start_date_input = discord.ui.TextInput(
        label="Ngày bắt đầu nghỉ (DD/MM/YYYY)",
        placeholder="01/05/2026",
        required=True,
        max_length=10,
    )
    end_date_input = discord.ui.TextInput(
        label="Ngày kết thúc nghỉ (DD/MM/YYYY)",
        placeholder="03/05/2026",
        required=True,
        max_length=10,
    )
    reason_input = discord.ui.TextInput(
        label="Lý do",
        placeholder="VD: Có việc gia đình...",
        required=True,
        style=discord.TextStyle.paragraph,
        max_length=500,
    )

    def __init__(self, cog: "LeaveCog"):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            sd = _parse_date(self.start_date_input.value)
            ed = _parse_date(self.end_date_input.value)
            if ed < sd:
                raise ValueError("Ngày kết thúc phải sau ngày bắt đầu")
            if sd < date.today() - timedelta(days=1):
                raise ValueError("Ngày bắt đầu không thể ở quá khứ")
        except ValueError as e:
            await interaction.followup.send(
                embed=build_error_embed(str(e), title="❌ Sai định dạng"),
                ephemeral=True,
            )
            return

        await self.cog._submit_request(
            interaction,
            request_type=LeaveRequestType.LEAVE,
            start_date=sd,
            end_date=ed,
            reason=self.reason_input.value.strip(),
        )


class XinOutNganhModal(discord.ui.Modal, title="🚪 Đơn xin out ngành"):
    """Modal nhập ngày bắt đầu out + lý do (không có ngày kết thúc — out vĩnh viễn)"""

    start_date_input = discord.ui.TextInput(
        label="Ngày out (DD/MM/YYYY)",
        placeholder="01/05/2026",
        required=True,
        max_length=10,
    )
    reason_input = discord.ui.TextInput(
        label="Lý do xin out",
        placeholder="VD: Bận học, không thể tiếp tục...",
        required=True,
        style=discord.TextStyle.paragraph,
        max_length=500,
    )

    def __init__(self, cog: "LeaveCog"):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            sd = _parse_date(self.start_date_input.value)
        except ValueError as e:
            await interaction.followup.send(
                embed=build_error_embed(str(e), title="❌ Sai định dạng"),
                ephemeral=True,
            )
            return

        await self.cog._submit_request(
            interaction,
            request_type=LeaveRequestType.RESIGN,
            start_date=sd,
            end_date=None,
            reason=self.reason_input.value.strip(),
        )


# ─── Cog ──────────────────────────────────────────────────────────────────────

class LeaveCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ─── Slash commands ─────────────────────────────────────────────────────

    @app_commands.command(name="xinnghi", description="Gửi đơn xin nghỉ phép tạm thời")
    @app_commands.checks.cooldown(rate=3, per=300.0)
    async def xinnghi(self, interaction: discord.Interaction):
        async with AsyncSessionLocal() as session:
            if not await require_member(interaction, session):
                await send_no_permission(interaction, DutyRole.MEMBER)
                return
        await interaction.response.send_modal(XinNghiModal(self))

    @app_commands.command(name="xinoutnganh", description="Xin out hẳn khỏi ngành (cần staff duyệt)")
    @app_commands.checks.cooldown(rate=2, per=3600.0)   # 2/giờ
    async def xinoutnganh(self, interaction: discord.Interaction):
        async with AsyncSessionLocal() as session:
            if not await require_member(interaction, session):
                await send_no_permission(interaction, DutyRole.MEMBER)
                return
        await interaction.response.send_modal(XinOutNganhModal(self))

    # ─── Submit request (chung cho cả LEAVE và RESIGN) ──────────────────────

    async def _submit_request(
        self,
        interaction: discord.Interaction,
        request_type: str,
        start_date: date,
        end_date: date | None,
        reason: str,
    ):
        async with AsyncSessionLocal() as session:
            cfg = await _get_config(session, interaction.guild_id)
            if not cfg or not cfg.leave_channel_id:
                await interaction.followup.send(
                    embed=build_error_embed(
                        "Server chưa cấu hình **channel xin nghỉ**.\n"
                        "Admin: dùng `/setup channel-xinnghi`."
                    ),
                    ephemeral=True,
                )
                return

            channel = interaction.guild.get_channel(cfg.leave_channel_id) if interaction.guild else None
            if not channel:
                await interaction.followup.send(
                    embed=build_error_embed("Channel xin nghỉ không tồn tại."),
                    ephemeral=True,
                )
                return

            # Tạo bản ghi LeaveRequest (status=pending)
            req = LeaveRequest(
                guild_id=interaction.guild_id,
                user_id=interaction.user.id,
                username=str(interaction.user.display_name),
                request_type=request_type,
                status=LeaveRequestStatus.PENDING,
                start_date=start_date,
                end_date=end_date,
                reason=reason,
                detail={
                    "avatar_url": str(interaction.user.display_avatar.url) if interaction.user.display_avatar else None,
                    "name": str(interaction.user),
                },
                created_at=utcnow(),
            )
            session.add(req)
            await session.flush()   # lấy req.id

            # Build embed staff vote
            embed = _build_vote_embed(req, interaction.user)

            try:
                msg = await channel.send(embed=embed)
                await msg.add_reaction(EMOJI_APPROVE)
                await msg.add_reaction(EMOJI_REJECT)
            except discord.HTTPException as e:
                await session.rollback()
                logger.error(f"Không gửi được vote message: {e}")
                await interaction.followup.send(
                    embed=build_error_embed(
                        "Không gửi được đơn lên channel staff. Liên hệ admin."
                    ),
                    ephemeral=True,
                )
                return

            req.vote_message_id = msg.id
            req.vote_channel_id = channel.id

            session.add(AuditLog(
                guild_id=interaction.guild_id,
                user_id=interaction.user.id,
                username=str(interaction.user),
                action=(
                    AuditAction.LEAVE_REQUESTED
                    if request_type == LeaveRequestType.LEAVE
                    else AuditAction.RESIGN_REQUESTED
                ),
                detail={
                    "request_id": req.id,
                    "start_date": str(start_date),
                    "end_date": str(end_date) if end_date else None,
                    "reason": reason[:200],
                },
                created_at=utcnow(),
            ))
            await session.commit()

        # DM xác nhận cho member
        try:
            label = "xin nghỉ phép" if request_type == LeaveRequestType.LEAVE else "xin out ngành"
            dm_embed = discord.Embed(
                title="📨 Đã gửi đơn",
                description=(
                    f"Đơn **{label}** của bạn đã được gửi đến staff để duyệt.\n"
                    "Bạn sẽ nhận được DM khi có kết quả."
                ),
                color=COLOR_INFO,
            )
            dm_embed.add_field(name="Mã đơn", value=f"#{req.id}", inline=True)
            dm_embed.add_field(name="Lý do", value=reason[:200], inline=False)
            dm_embed.set_footer(text="Nếu cần hỗ trợ vui lòng liên hệ ban lãnh đạo")
            await interaction.user.send(embed=dm_embed)
        except discord.HTTPException:
            pass

        await interaction.followup.send(
            embed=build_success_embed(
                f"Đã gửi đơn **#{req.id}** lên channel <#{channel.id}> để staff duyệt.\n"
                "Bot sẽ DM bạn khi có kết quả."
            ),
            ephemeral=True,
        )

    # ─── Listen react ──────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        """Listen staff react ✅/❌ trên vote message → update LeaveRequest"""
        if payload.user_id == self.bot.user.id:
            return
        if str(payload.emoji) not in (EMOJI_APPROVE, EMOJI_REJECT):
            return
        if payload.guild_id is None:
            return

        async with AsyncSessionLocal() as session:
            row = await session.execute(
                select(LeaveRequest).where(LeaveRequest.vote_message_id == payload.message_id)
            )
            req = row.scalar_one_or_none()
            if req is None or req.status != LeaveRequestStatus.PENDING:
                return

            # Verify ai react là Admin/Mod
            guild = self.bot.get_guild(payload.guild_id)
            if not guild:
                return
            staff_member = guild.get_member(payload.user_id)
            if not staff_member:
                return

            class _FakeInteraction:
                """Mini fake interaction object để dùng với check_permission"""
                def __init__(self, guild, user):
                    self.guild = guild
                    self.guild_id = guild.id
                    self.user = user

            fake_int = _FakeInteraction(guild, staff_member)
            is_mod = await check_permission(fake_int, DutyRole.MOD, session)
            if not is_mod:
                # Remove react vì không có quyền
                try:
                    channel = guild.get_channel(payload.channel_id)
                    if channel:
                        msg = await channel.fetch_message(payload.message_id)
                        await msg.remove_reaction(payload.emoji, staff_member)
                except discord.HTTPException:
                    pass
                return

            # Update status
            approved = str(payload.emoji) == EMOJI_APPROVE
            new_status = LeaveRequestStatus.APPROVED if approved else LeaveRequestStatus.REJECTED
            req.status = new_status
            req.decided_by = payload.user_id
            req.decided_at = utcnow()

            audit_action = (
                AuditAction.LEAVE_APPROVED if (approved and req.request_type == LeaveRequestType.LEAVE)
                else AuditAction.LEAVE_REJECTED if (not approved and req.request_type == LeaveRequestType.LEAVE)
                else AuditAction.RESIGN_APPROVED if approved
                else AuditAction.RESIGN_REJECTED
            )
            session.add(AuditLog(
                guild_id=payload.guild_id,
                user_id=payload.user_id,
                username=str(staff_member),
                action=audit_action,
                detail={"request_id": req.id, "for_user": str(req.user_id)},
                created_at=utcnow(),
            ))

            # ── Auto-cleanup khi RESIGN được duyệt ──
            cleanup_report: dict | None = None
            if approved and req.request_type == LeaveRequestType.RESIGN:
                cleanup_report = await auto_cleanup_after_resign_approval(
                    session, self.bot, payload.guild_id, req.user_id, payload.user_id,
                )

            # Đánh dấu đã xử lý ngay (react Discord = sync) để bot loop không xử lý lại
            req.processed_at = utcnow()

            await session.commit()

        # Update message embed (mark approved/rejected)
        try:
            channel = guild.get_channel(payload.channel_id)
            if channel:
                msg = await channel.fetch_message(payload.message_id)
                user = guild.get_member(req.user_id)
                new_embed = _build_vote_embed(req, user, decided_by=staff_member)
                await msg.edit(embed=new_embed)
        except discord.HTTPException:
            pass

        # DM kết quả cho người xin
        try:
            user = guild.get_member(req.user_id)
            if user:
                if approved:
                    if req.request_type == LeaveRequestType.LEAVE:
                        dm_title = "✅ Đơn xin nghỉ đã được duyệt"
                        dm_desc = (
                            f"Đơn xin nghỉ từ **{req.start_date.strftime('%d/%m/%Y')}** "
                            f"đến **{req.end_date.strftime('%d/%m/%Y') if req.end_date else 'không xác định'}** "
                            "đã được duyệt.\nBot sẽ không nhắc bạn về ca trực trong khoảng này."
                        )
                    else:
                        dm_title = "✅ Đơn xin out ngành đã được duyệt"
                        dm_desc = (
                            f"Đơn xin out ngành (từ **{req.start_date.strftime('%d/%m/%Y')}**) "
                            "đã được duyệt. Cảm ơn bạn đã đóng góp cho ngành.\n\n"
                            "**Hệ thống đã tự động xử lý:**\n"
                        )
                        if cleanup_report:
                            lines = []
                            if cleanup_report["schedules_deleted"] > 0:
                                lines.append(f"• 🗑️ Đã xoá **{cleanup_report['schedules_deleted']}** entry lịch trực")
                            removed = cleanup_report.get("roles_removed") or []
                            skipped = cleanup_report.get("roles_skipped") or []
                            if removed:
                                lines.append(f"• 🎭 Đã gỡ **{len(removed)}** role: " + ", ".join(f"`{n}`" for n in removed[:5]))
                                if len(removed) > 5:
                                    lines[-1] += f" +{len(removed) - 5}"
                            if skipped:
                                lines.append(f"• ⚠️ Có **{len(skipped)}** role chưa gỡ được (do bot thiếu quyền)")
                            if cleanup_report.get("global_error"):
                                lines.append(f"• ⚠️ {cleanup_report['global_error']}")
                            lines.append(
                                "• 📊 Lịch sử chấm công vẫn được giữ lại để minh bạch"
                            )
                            dm_desc += "\n".join(lines)
                    dm_embed = discord.Embed(
                        title=dm_title, description=dm_desc, color=COLOR_SUCCESS,
                    )
                else:
                    dm_embed = discord.Embed(
                        title="❌ Đơn không được duyệt",
                        description=(
                            f"Đơn **#{req.id}** đã bị từ chối bởi {staff_member.mention}.\n"
                            "Nếu cần hỗ trợ vui lòng liên hệ ban lãnh đạo."
                        ),
                        color=COLOR_ERROR,
                    )
                dm_embed.set_footer(text="Nếu cần hỗ trợ vui lòng liên hệ ban lãnh đạo")
                await user.send(embed=dm_embed)
        except discord.HTTPException:
            pass


# ─── Helpers ─────────────────────────────────────────────────────────────────

async def auto_cleanup_after_resign_approval(
    session,
    bot: commands.Bot,
    guild_id: int,
    user_id: int,
    decided_by: int,
    reason: str = "Đơn xin out ngành được duyệt",
) -> dict:
    """
    Sau khi đơn /xinoutnganh được DUYỆT (hoặc /sathai), tự động cleanup:
      1. Xoá tất cả MemberSchedule (ScheduleReminder cascade theo FK)
      2. Xoá OnboardingLog (tránh DM lại nếu rejoin)
      3. Gỡ TẤT CẢ role trong cleanup_role_ids (+ medic_role_id) trên Discord

    KHÔNG xoá: duty_logs, audit_logs, users (giữ lịch sử + minh bạch).
    Trả về dict report để ghi audit log.
    """
    report = {
        "schedules_deleted": 0,
        "onboarding_deleted": 0,
        "roles_removed": [],          # list role names đã gỡ thành công
        "roles_skipped": [],          # list dict {id, reason}
        "global_error": None,
    }

    # 1. Xoá MemberSchedule
    res = await session.execute(
        delete(MemberSchedule)
        .where(MemberSchedule.guild_id == guild_id)
        .where(MemberSchedule.user_id == user_id)
    )
    report["schedules_deleted"] = res.rowcount or 0

    # 2. Xoá OnboardingLog
    res = await session.execute(
        delete(OnboardingLog)
        .where(OnboardingLog.guild_id == guild_id)
        .where(OnboardingLog.user_id == user_id)
    )
    report["onboarding_deleted"] = res.rowcount or 0

    # 3. Gỡ tất cả role trong cleanup_role_ids + medic_role_id
    cfg_row = await session.execute(
        select(GuildConfig).where(GuildConfig.guild_id == guild_id)
    )
    cfg = cfg_row.scalar_one_or_none()
    if not cfg:
        report["global_error"] = "Không tìm thấy guild config"
        return report

    # Gộp danh sách role IDs (dedupe)
    role_ids: set[int] = set()
    for rid in (cfg.cleanup_role_ids or []):
        try:
            role_ids.add(int(rid))
        except (TypeError, ValueError):
            pass
    if cfg.medic_role_id:
        role_ids.add(int(cfg.medic_role_id))

    if not role_ids:
        report["global_error"] = "Chưa có role trong cleanup_role_ids hoặc medic_role"
        return report

    guild = bot.get_guild(guild_id)
    if not guild:
        report["global_error"] = "Bot không thấy guild này"
        return report

    member = guild.get_member(user_id)
    if not member:
        report["global_error"] = "Member không còn trong guild"
        return report

    # Tập hợp các role thật sự member đang có nằm trong cleanup list
    roles_to_remove = [r for r in member.roles if r.id in role_ids]
    if not roles_to_remove:
        report["global_error"] = "Member không có role nào trong cleanup list"
        return report

    # Gỡ batch (atomic-ish) — Discord API support remove nhiều role 1 lần
    try:
        await member.remove_roles(
            *roles_to_remove,
            reason=f"Auto-cleanup: {reason} (bởi user {decided_by})",
            atomic=True,
        )
        report["roles_removed"] = [r.name for r in roles_to_remove]
    except discord.Forbidden:
        # Nếu batch fail (có role bot không gỡ được) → thử từng role 1
        for r in roles_to_remove:
            try:
                await member.remove_roles(
                    r, reason=f"Auto-cleanup: {reason}",
                )
                report["roles_removed"].append(r.name)
            except discord.Forbidden:
                report["roles_skipped"].append(
                    {"id": str(r.id), "name": r.name, "reason": "Bot không có quyền"}
                )
            except discord.HTTPException as e:
                report["roles_skipped"].append(
                    {"id": str(r.id), "name": r.name, "reason": f"Discord error: {e}"}
                )
    except discord.HTTPException as e:
        report["global_error"] = f"Discord API error: {e}"

    # Audit log auto-cleanup
    session.add(AuditLog(
        guild_id=guild_id,
        user_id=decided_by,
        username=f"system_auto_cleanup_for_{user_id}",
        action=AuditAction.RESIGN_APPROVED,
        detail={
            "auto_cleanup": True,
            "for_user": str(user_id),
            "reason": reason[:200],
            "report": report,
        },
        created_at=utcnow(),
    ))
    return report


async def _get_config(session, guild_id: int) -> GuildConfig | None:
    r = await session.execute(
        select(GuildConfig).where(GuildConfig.guild_id == guild_id)
    )
    return r.scalar_one_or_none()


def _build_vote_embed(
    req: LeaveRequest,
    user: discord.Member | discord.User | None,
    decided_by: discord.Member | None = None,
) -> discord.Embed:
    """Embed hiển thị đơn xin nghỉ trong channel staff"""
    is_resign = req.request_type == LeaveRequestType.RESIGN
    if req.status == LeaveRequestStatus.APPROVED:
        title = ("✅ ĐÃ DUYỆT — Đơn xin out ngành" if is_resign else "✅ ĐÃ DUYỆT — Đơn xin nghỉ phép")
        color = COLOR_SUCCESS
    elif req.status == LeaveRequestStatus.REJECTED:
        title = ("❌ TỪ CHỐI — Đơn xin out ngành" if is_resign else "❌ TỪ CHỐI — Đơn xin nghỉ phép")
        color = COLOR_ERROR
    else:
        title = ("🚪 Đơn xin out ngành" if is_resign else "🏖 Đơn xin nghỉ phép")
        color = COLOR_WARNING

    embed = discord.Embed(title=title, description=f"Mã đơn: `#{req.id}`", color=color)

    user_label = (user.mention if user else f"<@{req.user_id}>")
    embed.add_field(name="👤 Người xin", value=user_label, inline=True)
    embed.add_field(name="📛 Tên", value=discord.utils.escape_markdown(req.username), inline=True)
    embed.add_field(name="​", value="​", inline=True)
    embed.add_field(
        name="📅 Từ ngày",
        value=f"`{req.start_date.strftime('%d/%m/%Y')}`",
        inline=True,
    )
    if req.end_date:
        days = (req.end_date - req.start_date).days + 1
        embed.add_field(
            name="📅 Đến ngày",
            value=f"`{req.end_date.strftime('%d/%m/%Y')}` ({days} ngày)",
            inline=True,
        )
    else:
        embed.add_field(name="📅 Đến ngày", value="_không xác định_", inline=True)
    embed.add_field(name="​", value="​", inline=True)

    embed.add_field(
        name="📝 Lý do",
        value=discord.utils.escape_markdown(req.reason)[:1024],
        inline=False,
    )

    if user and getattr(user, "display_avatar", None):
        embed.set_thumbnail(url=user.display_avatar.url)

    if req.status == LeaveRequestStatus.PENDING:
        embed.add_field(
            name="🗳 Vote",
            value=f"Staff hãy react {EMOJI_APPROVE} để **duyệt** hoặc {EMOJI_REJECT} để **từ chối**",
            inline=False,
        )
    elif decided_by is not None:
        embed.add_field(
            name="👮 Quyết định bởi",
            value=f"{decided_by.mention} • {utcnow().strftime('%H:%M %d/%m/%Y')} UTC",
            inline=False,
        )

    embed.set_footer(text=f"Gửi lúc {req.created_at.strftime('%H:%M %d/%m/%Y')} UTC")
    return embed


async def setup(bot: commands.Bot):
    await bot.add_cog(LeaveCog(bot))
