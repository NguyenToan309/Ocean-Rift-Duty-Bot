"""
schedule_tasks.py — Background loops cho hệ thống lịch trực:
- pre_shift_remind_loop: chạy mỗi phút, nhắc trước ca theo mốc default/custom
- end_of_day_check_loop: chạy mỗi giờ, vào 23h check ai có lịch nhưng không log
- onboarding_scan_loop: chạy mỗi 6 giờ, DM nhân viên Medic chưa đăng ký lịch
- on_member_role_update: real-time, khi member nhận role Medic mới → DM ngay

Tất cả đăng ký vào bot qua start_background_tasks(bot).
"""
from __future__ import annotations
import logging
from datetime import datetime, date, time, timedelta, timezone
from typing import TYPE_CHECKING

import discord
from discord.ext import tasks
import pytz
from sqlalchemy import select, and_, or_, func

from models.base import AsyncSessionLocal
from models.guild import GuildConfig
from models.duty_log import DutyLog
from models.schedule import (
    MemberSchedule, ScheduleReminder, OnboardingLog, WEEKDAY_LABELS, WEEKDAY_SHORT,
)
from models.leave import LeaveRequest, LeaveRequestType, LeaveRequestStatus
from models.audit_log import AuditLog, AuditAction
from bot.utils.time_utils import utcnow, to_local
from bot.utils.schedule_engine import (
    list_upcoming_occurrences, schedule_occurrence_to_utc, is_user_on_leave,
)

if TYPE_CHECKING:
    from discord.ext import commands

logger = logging.getLogger(__name__)


# ─── Loop 1: nhắc trước ca ───────────────────────────────────────────────────

@tasks.loop(minutes=1)
async def pre_shift_remind_loop(bot: "commands.Bot"):
    """
    Chạy mỗi phút. Logic:
    1. Cho mỗi guild đã setup
    2. Lấy upcoming occurrences trong 75 phút tới
    3. Cho mỗi occurrence:
       - Lấy mốc nhắc (custom hoặc default của guild)
       - Cho mỗi mốc M phút: nếu hiện tại nằm trong [start - M, start - M + 1 phút]
         → check user_id chưa nghỉ phép, chưa log, chưa nhắc → DM + tag channel
    """
    try:
        await _pre_shift_tick(bot)
    except Exception as e:
        logger.error(f"[remind-loop] Lỗi tick: {e}", exc_info=True)


async def _pre_shift_tick(bot: "commands.Bot"):
    now_utc = utcnow()

    async with AsyncSessionLocal() as session:
        cfg_rows = await session.execute(select(GuildConfig).where(GuildConfig.is_active == True))  # noqa: E712
        configs = cfg_rows.scalars().all()

        for cfg in configs:
            guild = bot.get_guild(cfg.guild_id)
            if not guild:
                continue

            tz = cfg.timezone or "Asia/Ho_Chi_Minh"
            occurrences = await list_upcoming_occurrences(
                session, cfg.guild_id, tz, now_utc, horizon_minutes=75,
            )

            for occ in occurrences:
                sched = occ.schedule
                offsets = sched.custom_remind_offsets or cfg.default_remind_offsets or [60, 30, 5]

                for minutes_before in offsets:
                    remind_at = occ.start_dt_utc - timedelta(minutes=minutes_before)
                    # Trong cửa sổ 1 phút quanh remind_at?
                    if not (remind_at <= now_utc < remind_at + timedelta(minutes=1)):
                        continue

                    reminder_type = f"pre_{minutes_before}"
                    # Check đã nhắc chưa
                    existing = await session.execute(
                        select(ScheduleReminder)
                        .where(ScheduleReminder.schedule_id == sched.id)
                        .where(ScheduleReminder.occurrence_date == occ.occurrence_date)
                        .where(ScheduleReminder.reminder_type == reminder_type)
                    )
                    if existing.scalar_one_or_none():
                        continue

                    # User đang nghỉ phép → skip
                    if await is_user_on_leave(session, cfg.guild_id, sched.user_id, occ.occurrence_date):
                        continue

                    # User đã có log overlap → skip
                    has_log = await _user_has_log_overlap(
                        session, cfg.guild_id, sched.user_id,
                        occ.start_dt_utc, occ.end_dt_utc,
                    )
                    if has_log:
                        continue

                    # Gửi DM + tag channel
                    await _send_pre_shift_reminder(
                        bot, guild, cfg, sched, occ, minutes_before,
                    )

                    session.add(ScheduleReminder(
                        schedule_id=sched.id,
                        occurrence_date=occ.occurrence_date,
                        reminder_type=reminder_type,
                        sent_at=now_utc,
                    ))

                # Mốc trước hết ca 5 phút (nhắc submit log)
                pre_end_at = occ.end_dt_utc - timedelta(minutes=5)
                if (
                    pre_end_at <= now_utc < pre_end_at + timedelta(minutes=1)
                    and not await is_user_on_leave(session, cfg.guild_id, sched.user_id, occ.occurrence_date)
                ):
                    rem_type = "pre_end_5"
                    existing = await session.execute(
                        select(ScheduleReminder)
                        .where(ScheduleReminder.schedule_id == sched.id)
                        .where(ScheduleReminder.occurrence_date == occ.occurrence_date)
                        .where(ScheduleReminder.reminder_type == rem_type)
                    )
                    if not existing.scalar_one_or_none():
                        await _send_pre_end_reminder(bot, guild, cfg, sched, occ)
                        session.add(ScheduleReminder(
                            schedule_id=sched.id,
                            occurrence_date=occ.occurrence_date,
                            reminder_type=rem_type,
                            sent_at=now_utc,
                        ))

        await session.commit()


async def _user_has_log_overlap(
    session, guild_id: int, user_id: int,
    start_utc: datetime, end_utc: datetime,
) -> bool:
    """Check user có log duty overlap với khoảng [start, end] không"""
    r = await session.execute(
        select(DutyLog.id)
        .where(DutyLog.guild_id == guild_id)
        .where(DutyLog.user_id == user_id)
        .where(DutyLog.started_at < end_utc)
        .where(DutyLog.ended_at > start_utc)
        .limit(1)
    )
    return r.scalar_one_or_none() is not None


async def _send_pre_shift_reminder(
    bot, guild: discord.Guild, cfg: GuildConfig,
    sched: MemberSchedule, occ, minutes_before: int,
):
    """Gửi DM + tag channel nhắc trước ca"""
    member = guild.get_member(sched.user_id)
    if not member:
        return

    tz = pytz.timezone(cfg.timezone or "Asia/Ho_Chi_Minh")
    start_local = occ.start_dt_utc.astimezone(tz)
    end_local = occ.end_dt_utc.astimezone(tz)
    weekday_label = WEEKDAY_LABELS[start_local.weekday()]

    embed = discord.Embed(
        title=f"🔔 Còn {minutes_before} phút nữa đến ca trực",
        description=f"**{member.display_name}** ơi, ca trực của bạn sắp bắt đầu!",
        color=0x5865F2,
    )
    embed.add_field(
        name="📆 Ca trực",
        value=f"{weekday_label}, {start_local.strftime('%d/%m/%Y')}",
        inline=True,
    )
    embed.add_field(
        name="🕐 Thời gian",
        value=f"`{start_local.strftime('%H:%M')} → {end_local.strftime('%H:%M')}`",
        inline=True,
    )
    embed.set_footer(text="Đừng quên gửi LOG DUTY khi trực! • Liên hệ ban lãnh đạo nếu cần hỗ trợ")

    # DM
    try:
        await member.send(embed=embed)
    except discord.HTTPException as e:
        logger.debug(f"Không DM được {member}: {e}")

    # Tag channel
    if cfg.remind_channel_id:
        ch = guild.get_channel(cfg.remind_channel_id)
        if ch:
            try:
                await ch.send(content=member.mention, embed=embed)
            except discord.HTTPException as e:
                logger.debug(f"Không gửi được vào remind channel: {e}")


async def _send_pre_end_reminder(
    bot, guild, cfg, sched, occ,
):
    """5 phút trước hết ca → DM 'đừng quên submit log'"""
    member = guild.get_member(sched.user_id)
    if not member:
        return

    tz = pytz.timezone(cfg.timezone or "Asia/Ho_Chi_Minh")
    end_local = occ.end_dt_utc.astimezone(tz)

    embed = discord.Embed(
        title="⏰ Ca trực sắp hết",
        description=(
            f"**{member.display_name}**, ca trực của bạn sẽ kết thúc lúc "
            f"`{end_local.strftime('%H:%M')}`.\n"
            "Đừng quên submit **LOG DUTY** trong channel chấm công nhé!"
        ),
        color=0xFEE75C,
    )
    embed.set_footer(text="Liên hệ ban lãnh đạo nếu cần hỗ trợ")

    try:
        await member.send(embed=embed)
    except discord.HTTPException:
        pass


# ─── Loop 2: End-of-day check ───────────────────────────────────────────────

@tasks.loop(minutes=10)
async def end_of_day_check_loop(bot: "commands.Bot"):
    """
    Chạy mỗi 10 phút. Vào 23h-23h59 (giờ guild local) → quét ai có lịch hôm nay
    nhưng không có log duty → DM "có quên chấm công không?"
    """
    try:
        await _eod_tick(bot)
    except Exception as e:
        logger.error(f"[eod-loop] Lỗi: {e}", exc_info=True)


async def _eod_tick(bot):
    now_utc = utcnow()
    async with AsyncSessionLocal() as session:
        cfgs = (await session.execute(select(GuildConfig).where(GuildConfig.is_active == True))).scalars().all()  # noqa

        for cfg in cfgs:
            tz = pytz.timezone(cfg.timezone or "Asia/Ho_Chi_Minh")
            local_now = now_utc.astimezone(tz)
            # Chỉ chạy trong khung 23h-23h59 local
            if local_now.hour != 23:
                continue

            today = local_now.date()
            wd = today.weekday()

            # Lấy schedules hôm nay
            scheds = (await session.execute(
                select(MemberSchedule)
                .where(MemberSchedule.guild_id == cfg.guild_id)
                .where(MemberSchedule.weekday == wd)
                .where(MemberSchedule.is_active == True)  # noqa: E712
            )).scalars().all()

            guild = bot.get_guild(cfg.guild_id)
            if not guild:
                continue

            for sched in scheds:
                # User đã nghỉ phép → skip
                if await is_user_on_leave(session, cfg.guild_id, sched.user_id, today):
                    continue

                # Check đã nhắc EOD hôm nay chưa
                exists = await session.execute(
                    select(ScheduleReminder)
                    .where(ScheduleReminder.schedule_id == sched.id)
                    .where(ScheduleReminder.occurrence_date == today)
                    .where(ScheduleReminder.reminder_type == "eod_missing")
                )
                if exists.scalar_one_or_none():
                    continue

                # Check user có log nào overlap với ca hôm nay không
                start_utc, end_utc = schedule_occurrence_to_utc(sched, today, cfg.timezone or "Asia/Ho_Chi_Minh")
                has_log = await _user_has_log_overlap(
                    session, cfg.guild_id, sched.user_id, start_utc, end_utc,
                )
                if has_log:
                    continue

                # DM nhắc
                member = guild.get_member(sched.user_id)
                if not member:
                    continue

                embed = discord.Embed(
                    title="🤔 Bạn có quên chấm công hôm nay?",
                    description=(
                        f"**{member.display_name}**, hôm nay bạn có lịch trực "
                        f"**{WEEKDAY_LABELS[wd]} "
                        f"{sched.start_time.strftime('%H:%M')}-{sched.end_time.strftime('%H:%M')}** "
                        "nhưng bot chưa thấy LOG DUTY của bạn.\n\n"
                        "Nếu đã trực mà quên gửi log → vui lòng forward LOG DUTY ngay!\n"
                        "Nếu hôm nay không trực được → cân nhắc dùng `/xinnghi`."
                    ),
                    color=0xFEE75C,
                )
                embed.set_footer(text="Liên hệ ban lãnh đạo nếu cần hỗ trợ")
                try:
                    await member.send(embed=embed)
                except discord.HTTPException:
                    pass

                session.add(ScheduleReminder(
                    schedule_id=sched.id,
                    occurrence_date=today,
                    reminder_type="eod_missing",
                    sent_at=now_utc,
                ))

        await session.commit()


# ─── Loop 3: Onboarding scan ──────────────────────────────────────────────────

@tasks.loop(hours=6)
async def onboarding_scan_loop(bot: "commands.Bot"):
    """
    Chạy mỗi 6h. Quét guild members có role Medic → ai chưa có MemberSchedule → DM nhắc.
    Cooldown: tối đa 1 nhắc/24h/user.
    """
    try:
        await _onboarding_tick(bot)
    except Exception as e:
        logger.error(f"[onboarding-loop] Lỗi: {e}", exc_info=True)


async def _onboarding_tick(bot):
    now = utcnow()
    cooldown_cutoff = now - timedelta(hours=24)

    async with AsyncSessionLocal() as session:
        cfgs = (await session.execute(select(GuildConfig).where(GuildConfig.is_active == True))).scalars().all()  # noqa

        for cfg in cfgs:
            if not cfg.medic_role_id:
                continue
            guild = bot.get_guild(cfg.guild_id)
            if not guild:
                continue
            role = guild.get_role(cfg.medic_role_id)
            if not role:
                continue

            for member in role.members:
                if member.bot:
                    continue
                # Đã có schedule chưa?
                has = await session.execute(
                    select(MemberSchedule.id)
                    .where(MemberSchedule.guild_id == cfg.guild_id)
                    .where(MemberSchedule.user_id == member.id)
                    .limit(1)
                )
                if has.scalar_one_or_none() is not None:
                    continue

                # Cooldown 24h
                ob = await session.execute(
                    select(OnboardingLog)
                    .where(OnboardingLog.guild_id == cfg.guild_id)
                    .where(OnboardingLog.user_id == member.id)
                )
                ob_row = ob.scalar_one_or_none()
                if ob_row and ob_row.last_reminded_at > cooldown_cutoff:
                    continue

                await _send_onboarding_reminder(member, cfg, guild)

                if ob_row:
                    ob_row.last_reminded_at = now
                else:
                    session.add(OnboardingLog(
                        guild_id=cfg.guild_id,
                        user_id=member.id,
                        last_reminded_at=now,
                    ))

                session.add(AuditLog(
                    guild_id=cfg.guild_id,
                    user_id=member.id,
                    username=str(member),
                    action=AuditAction.ONBOARDING_REMINDED,
                    detail={"role_id": str(cfg.medic_role_id)},
                    created_at=now,
                ))

        await session.commit()


async def _send_onboarding_reminder(member: discord.Member, cfg: GuildConfig, guild: discord.Guild):
    embed = discord.Embed(
        title="🎯 Hãy đăng ký lịch trực",
        description=(
            f"Chào **{member.display_name}**!\n\n"
            "Bạn đã được cấp role **Medic** nhưng chưa đăng ký lịch trực.\n"
            "Vui lòng dùng lệnh `/dangky` để đăng ký lịch cố định hàng tuần.\n\n"
            "Sau khi đăng ký, bot sẽ tự động nhắc bạn trước mỗi ca."
        ),
        color=0x5865F2,
    )
    if cfg.schedule_channel_id:
        embed.add_field(
            name="📍 Channel đăng ký",
            value=f"<#{cfg.schedule_channel_id}>",
            inline=False,
        )
    embed.set_footer(text="Liên hệ ban lãnh đạo nếu cần hỗ trợ")

    # DM trước; nếu fail thì tag in onboarding channel (= remind_channel)
    try:
        await member.send(embed=embed)
        return
    except discord.HTTPException:
        pass

    # Fallback: tag trong remind channel hoặc schedule channel
    fallback_id = cfg.remind_channel_id or cfg.schedule_channel_id
    if fallback_id:
        ch = guild.get_channel(fallback_id)
        if ch:
            try:
                await ch.send(content=member.mention, embed=embed)
            except discord.HTTPException:
                pass


# ─── Real-time: nhận role Medic mới → DM ngay ────────────────────────────────

async def on_member_role_update(before: discord.Member, after: discord.Member, bot):
    """
    Listener gắn với event on_member_update. Khi user nhận role Medic mới
    (role không có trước, có sau) → DM onboarding ngay (không đợi loop 6h).
    """
    try:
        if before.roles == after.roles:
            return

        async with AsyncSessionLocal() as session:
            cfg_row = await session.execute(
                select(GuildConfig).where(GuildConfig.guild_id == after.guild.id)
            )
            cfg = cfg_row.scalar_one_or_none()
            if not cfg or not cfg.medic_role_id:
                return

            had = any(r.id == cfg.medic_role_id for r in before.roles)
            has_now = any(r.id == cfg.medic_role_id for r in after.roles)
            if not has_now or had:
                return  # Không phải vừa nhận role Medic

            # Đã có schedule chưa?
            existing = await session.execute(
                select(MemberSchedule.id)
                .where(MemberSchedule.guild_id == after.guild.id)
                .where(MemberSchedule.user_id == after.id)
                .limit(1)
            )
            if existing.scalar_one_or_none() is not None:
                return

            await _send_onboarding_reminder(after, cfg, after.guild)
            now = utcnow()
            ob_row = (await session.execute(
                select(OnboardingLog)
                .where(OnboardingLog.guild_id == after.guild.id)
                .where(OnboardingLog.user_id == after.id)
            )).scalar_one_or_none()
            if ob_row:
                ob_row.last_reminded_at = now
            else:
                session.add(OnboardingLog(
                    guild_id=after.guild.id,
                    user_id=after.id,
                    last_reminded_at=now,
                ))
            await session.commit()

    except Exception as e:
        logger.error(f"[on_member_update] {e}", exc_info=True)


# ─── Loop 4: xử lý đơn xin nghỉ duyệt qua web ────────────────────────────────

@tasks.loop(seconds=30)
async def process_web_decisions_loop(bot: "commands.Bot"):
    """
    Chạy mỗi 30s. Quét LeaveRequest đã được duyệt qua WEB nhưng bot chưa xử lý:
      - status != PENDING (đã có quyết định)
      - decided_at IS NOT NULL
      - processed_at IS NULL (bot chưa xử lý)

    Cho mỗi đơn:
      1. DM kết quả cho member (kèm note nếu có)
      2. Update embed Discord vote message (nếu có vote_message_id)
      3. Nếu RESIGN approved → auto cleanup (xoá lịch + gỡ role)
      4. Set processed_at để không xử lý lại
    """
    try:
        await _process_web_decisions_tick(bot)
    except Exception as e:
        logger.error(f"[web-decision-loop] Lỗi: {e}", exc_info=True)


async def _process_web_decisions_tick(bot: "commands.Bot"):
    async with AsyncSessionLocal() as session:
        rows = await session.execute(
            select(LeaveRequest)
            .where(LeaveRequest.status != LeaveRequestStatus.PENDING)
            .where(LeaveRequest.decided_at.isnot(None))
            .where(LeaveRequest.processed_at.is_(None))
            .limit(20)
        )
        pending_decisions = rows.scalars().all()

        if not pending_decisions:
            return

        for req in pending_decisions:
            try:
                await _handle_one_web_decision(bot, session, req)
            except Exception as e:
                logger.error(f"[web-decision] Lỗi xử lý req #{req.id}: {e}", exc_info=True)

        await session.commit()


async def _handle_one_web_decision(bot: "commands.Bot", session, req: LeaveRequest):
    """Xử lý 1 đơn đã duyệt qua web"""
    guild = bot.get_guild(req.guild_id)
    if not guild:
        # Bot chưa join guild → mark processed để không loop
        req.processed_at = utcnow()
        return

    member = guild.get_member(req.user_id)
    decided_by_user = guild.get_member(req.decided_by) if req.decided_by else None

    approved = req.status == LeaveRequestStatus.APPROVED
    is_resign = req.request_type == LeaveRequestType.RESIGN

    cleanup_report: dict | None = None
    if approved and is_resign:
        # Lazy import to avoid circular
        from bot.cogs.leave import auto_cleanup_after_resign_approval
        try:
            cleanup_report = await auto_cleanup_after_resign_approval(
                session, bot, req.guild_id, req.user_id,
                req.decided_by or 0,
                reason=f"Web approval (#{req.id}): {req.decision_note or 'no note'}",
            )
        except Exception as e:
            logger.error(f"[web-decision] cleanup fail #{req.id}: {e}", exc_info=True)

    # DM member
    if member:
        try:
            await _dm_decision_result(member, req, approved, is_resign, decided_by_user, cleanup_report)
        except Exception as e:
            logger.debug(f"[web-decision] DM fail: {e}")

    # Update embed Discord vote message
    if req.vote_message_id and req.vote_channel_id:
        try:
            ch = guild.get_channel(req.vote_channel_id)
            if ch:
                msg = await ch.fetch_message(req.vote_message_id)
                from bot.cogs.leave import _build_vote_embed
                new_embed = _build_vote_embed(req, member, decided_by=decided_by_user)
                await msg.edit(embed=new_embed)
        except Exception as e:
            logger.debug(f"[web-decision] Update embed fail: {e}")

    req.processed_at = utcnow()
    logger.info(
        f"[web-decision] Đã xử lý req #{req.id} "
        f"(type={req.request_type}, status={req.status}, user={req.user_id})"
    )


async def _dm_decision_result(
    member, req: LeaveRequest, approved: bool, is_resign: bool,
    decided_by_user, cleanup_report: dict | None,
):
    """Gửi DM thông báo kết quả cho member"""
    decided_by_label = (
        decided_by_user.mention if decided_by_user else f"<@{req.decided_by}>"
    )

    if approved:
        if is_resign:
            title = "✅ Đơn xin out ngành đã được duyệt"
            desc = (
                f"Đơn xin out ngành (từ **{req.start_date.strftime('%d/%m/%Y')}**) "
                "đã được duyệt qua web dashboard.\nCảm ơn bạn đã đóng góp cho ngành.\n\n"
                "**Hệ thống đã tự động xử lý:**\n"
            )
            if cleanup_report:
                lines = []
                if cleanup_report["schedules_deleted"] > 0:
                    lines.append(f"• 🗑️ Đã xoá **{cleanup_report['schedules_deleted']}** entry lịch trực")
                removed = cleanup_report.get("roles_removed") or []
                skipped = cleanup_report.get("roles_skipped") or []
                if removed:
                    lines.append(
                        f"• 🎭 Đã gỡ **{len(removed)}** role: " +
                        ", ".join(f"`{n}`" for n in removed[:5]) +
                        (f" +{len(removed)-5}" if len(removed) > 5 else "")
                    )
                if skipped:
                    lines.append(f"• ⚠️ {len(skipped)} role chưa gỡ được (bot thiếu quyền)")
                if cleanup_report.get("global_error"):
                    lines.append(f"• ⚠️ {cleanup_report['global_error']}")
                lines.append("• 📊 Lịch sử chấm công vẫn được giữ lại để minh bạch")
                desc += "\n".join(lines)
        else:
            title = "✅ Đơn xin nghỉ phép đã được duyệt"
            desc = (
                f"Đơn xin nghỉ từ **{req.start_date.strftime('%d/%m/%Y')}** "
                f"đến **{req.end_date.strftime('%d/%m/%Y') if req.end_date else 'không xác định'}** "
                "đã được duyệt qua web dashboard.\n"
                "Bot sẽ không nhắc bạn về ca trực trong khoảng này."
            )
        color = 0x57F287
    else:
        title = f"❌ Đơn {('xin out ngành' if is_resign else 'xin nghỉ phép')} bị từ chối"
        desc = f"Đơn **#{req.id}** đã bị từ chối bởi {decided_by_label} qua web dashboard."
        color = 0xED4245

    embed = discord.Embed(title=title, description=desc, color=color)
    if req.decision_note:
        embed.add_field(name="📝 Ghi chú từ staff", value=req.decision_note[:1024], inline=False)
    embed.set_footer(text="Nếu cần hỗ trợ vui lòng liên hệ ban lãnh đạo")
    await member.send(embed=embed)


# ─── before_loop: chờ bot ready ──────────────────────────────────────────────
# Discord.py tasks.loop chạy ngay phút đầu khi bot khởi động.
# Lúc đó bot có thể chưa cache xong guild members → guild.get_member() trả None.
# Dùng before_loop để đợi bot ready trước khi loop chạy lần đầu.

@pre_shift_remind_loop.before_loop
async def _before_pre_shift(bot: "commands.Bot" = None):
    # bot arg không được truyền tự động qua before_loop → dùng global wait_until_ready
    pass


@end_of_day_check_loop.before_loop
async def _before_eod():
    pass


@onboarding_scan_loop.before_loop
async def _before_onboarding():
    pass


# ─── Wire-up ─────────────────────────────────────────────────────────────────

def start_background_tasks(bot: "commands.Bot"):
    """
    Gọi 1 lần trong setup_hook() để khởi động tất cả loops.
    Trước khi loop chạy → đợi bot ready bằng wait_until_ready
    để tránh truy cập guild members lúc cache còn trống.
    """
    # Override before_loop để đợi bot ready
    async def _wait_ready():
        await bot.wait_until_ready()

    pre_shift_remind_loop.before_loop(_wait_ready)
    end_of_day_check_loop.before_loop(_wait_ready)
    onboarding_scan_loop.before_loop(_wait_ready)
    process_web_decisions_loop.before_loop(_wait_ready)

    if not pre_shift_remind_loop.is_running():
        pre_shift_remind_loop.start(bot)
    if not end_of_day_check_loop.is_running():
        end_of_day_check_loop.start(bot)
    if not onboarding_scan_loop.is_running():
        onboarding_scan_loop.start(bot)
    if not process_web_decisions_loop.is_running():
        process_web_decisions_loop.start(bot)
    logger.info("Đã khởi động background tasks: pre_shift, eod_check, onboarding_scan, process_web_decisions")
