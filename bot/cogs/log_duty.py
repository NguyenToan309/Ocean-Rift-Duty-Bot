"""
log_duty.py — Cog xử lý /log upload và /log view
Luồng upload: nhận ảnh → OCR → parse → validate → confirm → lưu DB
Luồng forward: nhận text → parse → validate → confirm → lưu DB
"""
import logging
import io
from datetime import datetime

import discord
from discord.ext import commands
from discord import app_commands
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from models.base import AsyncSessionLocal
from models.duty_log import DutyLog
from models.guild import GuildConfig
from models.audit_log import AuditLog, AuditAction
from bot.utils.ocr import extract_duty_from_image
from bot.utils.parser import parse_duty_text
from bot.utils.permissions import require_member, require_mod, require_admin, send_no_permission, DutyRole
from bot.utils.embed_builder import (
    build_log_confirm_embed, build_log_view_embed, build_all_logs_table_embed,
    build_error_embed, build_success_embed
)
from bot.utils.time_utils import to_utc, utcnow

logger = logging.getLogger(__name__)

PAGE_SIZE = 10  # Số log hiển thị mỗi trang


class ConfirmLogView(discord.ui.View):
    """Nút Xác nhận / Huỷ khi upload log"""

    def __init__(self, parsed_data: dict, submitter_id: int, guild_id: int):
        super().__init__(timeout=60)
        self.parsed_data = parsed_data
        self.submitter_id = submitter_id
        self.guild_id = guild_id
        self.confirmed = False

    @discord.ui.button(label="✅ Xác nhận lưu", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Chỉ người upload mới được xác nhận
        if interaction.user.id != self.submitter_id:
            await interaction.response.send_message(
                "Chỉ người upload mới được xác nhận log này.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)
        self.confirmed = True

        async with AsyncSessionLocal() as session:
            try:
                await _save_duty_log(
                    session=session,
                    guild_id=self.guild_id,
                    user_id=self.parsed_data["user_discord_id"],
                    username=self.parsed_data["username"],
                    started_at=self.parsed_data["started_at"],
                    ended_at=self.parsed_data["ended_at"],
                    duration_minutes=self.parsed_data["duration_minutes"],
                    raw_text=self.parsed_data.get("raw_text"),
                    source=self.parsed_data.get("source", "forward"),
                    source_message_id=self.parsed_data.get("source_message_id"),
                    submitted_by=self.submitter_id,
                )

                # Ghi audit log
                session.add(AuditLog(
                    guild_id=self.guild_id,
                    user_id=self.submitter_id,
                    username=str(interaction.user),
                    action=AuditAction.LOG_UPLOADED,
                    detail={
                        "for_user": self.parsed_data["username"],
                        "duration_minutes": self.parsed_data["duration_minutes"],
                        "source": self.parsed_data.get("source"),
                    },
                    created_at=utcnow(),
                ))
                await session.commit()

            except Exception as e:
                await session.rollback()
                logger.error(f"Lỗi lưu duty log: {e}", exc_info=True)
                await interaction.followup.send(
                    embed=build_error_embed(f"Lưu thất bại: {e}"), ephemeral=True
                )
                self.stop()
                return

        embed = build_success_embed(
            f"Đã lưu log trực cho **{self.parsed_data['username']}**!\n"
            f"⏱ {self.parsed_data['duration_minutes']} phút"
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

        # Disable tất cả nút sau khi đã xác nhận (ephemeral message edit có thể fail)
        for child in self.children:
            child.disabled = True
        try:
            await interaction.edit_original_response(view=self)
        except discord.HTTPException:
            pass  # Bỏ qua nếu không edit được (ephemeral đã expire)
        self.stop()

    @discord.ui.button(label="❌ Huỷ", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.submitter_id:
            await interaction.response.send_message("Không phải log của bạn.", ephemeral=True)
            return

        await interaction.response.send_message("Đã huỷ lưu log.", ephemeral=True)
        for child in self.children:
            child.disabled = True
        try:
            await interaction.edit_original_response(view=self)
        except discord.HTTPException:
            pass
        self.stop()


async def _save_duty_log(
    session: AsyncSession,
    guild_id: int,
    user_id: int,
    username: str,
    started_at: datetime,
    ended_at: datetime,
    duration_minutes: int,
    raw_text: str | None,
    source: str,
    source_message_id: int | None,
    submitted_by: int,
) -> DutyLog:
    """
    Lưu DutyLog vào DB. Kiểm tra duplicate bằng 2 tầng:
    1. source_message_id (nếu auto-scan / forward Discord)
    2. (guild_id, user_id, started_at, ended_at) — phòng cho /log forward và OCR upload
       trùng nội dung nhưng từ message khác. 2 ca trực cùng user và cùng start+end là vô lý.
    """
    # Tầng 1: source_message_id
    if source_message_id:
        existing = await session.execute(
            select(DutyLog).where(DutyLog.source_message_id == source_message_id)
        )
        if existing.scalar_one_or_none():
            raise ValueError("Log này đã được lưu trước đó (duplicate message)")

    # Tầng 2: cùng user + cùng start + cùng end trong guild
    dup = await session.execute(
        select(DutyLog)
        .where(DutyLog.guild_id == guild_id)
        .where(DutyLog.user_id == user_id)
        .where(DutyLog.started_at == started_at)
        .where(DutyLog.ended_at == ended_at)
        .limit(1)
    )
    if dup.scalar_one_or_none():
        raise ValueError(
            f"Đã tồn tại ca trực của **{username}** từ "
            f"`{started_at.strftime('%H:%M %d/%m/%Y')}` đến "
            f"`{ended_at.strftime('%H:%M %d/%m/%Y')}` (trùng dữ liệu)"
        )

    log = DutyLog(
        guild_id=guild_id,
        user_id=user_id,
        username=username,
        started_at=started_at,
        ended_at=ended_at,
        duration_minutes=duration_minutes,
        raw_text=raw_text,
        source=source,
        source_message_id=source_message_id,
        submitted_by=submitted_by,
        created_at=utcnow(),
    )
    session.add(log)
    return log


def _normalize_name(s: str | None) -> str:
    """Lowercase + strip non-alphanumeric (chấp nhận tiếng Việt) để so sánh tên fuzzy"""
    if not s:
        return ""
    import re
    # Giữ chữ + số (Unicode), bỏ space + ký tự đặc biệt
    return re.sub(r"[^a-z0-9àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ]", "", s.lower())


def _username_matches_author(parsed_name: str, author: discord.abc.User) -> bool:
    """
    Kiểm tra tên parsed từ LOG DUTY có khớp với Discord author không.
    So sánh fuzzy với: name, global_name, display_name, nick (nếu là Member).
    Match nếu một bên là substring của bên kia (sau khi normalize).
    """
    parsed_n = _normalize_name(parsed_name)
    if not parsed_n:
        return False

    candidates: list[str] = [
        getattr(author, "name", "") or "",
        getattr(author, "global_name", None) or "",
        getattr(author, "display_name", "") or "",
        getattr(author, "nick", None) or "",
    ]

    for c in candidates:
        c_n = _normalize_name(c)
        if not c_n:
            continue
        if parsed_n == c_n or parsed_n in c_n or c_n in parsed_n:
            return True
    return False


class LogDutyCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    log_group = app_commands.Group(name="log", description="Quản lý log chấm công")

    # ─────────────────────────────────────────────────────────────────
    # Auto-scan: tự động parse mọi tin nhắn LOG DUTY trong channel đã setup
    # User chỉ cần gửi/forward tin nhắn → bot tự lưu, không cần slash command
    # ─────────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # Bỏ qua MỌI tin nhắn của bot (kể cả bot khác hay webhook)
        if message.author.bot:
            return
        if not message.guild:
            return

        # Lấy config guild — phải đã setup
        async with AsyncSessionLocal() as session:
            config = await _get_guild_config(session, message.guild.id)

        if not config or not config.is_active:
            return

        # Chỉ scan trong channel đã set; nếu chưa set log_channel_id thì BỎ QUA
        # (an toàn hơn — tránh quét bừa toàn bộ server)
        if not config.log_channel_id:
            return
        if message.channel.id != config.log_channel_id:
            return

        # Trích xuất tất cả text candidates: content gốc + forward snapshots + embeds
        candidates = self._extract_message_text(message)
        if not candidates:
            logger.debug(f"[auto-scan] Không có text candidates từ msg {message.id}")
            return

        logger.debug(
            f"[auto-scan] Quét msg {message.id} từ {message.author}: "
            f"{len(candidates)} candidate(s), kích thước: "
            f"{[len(c) for c in candidates]}"
        )

        # Thử parse từng đoạn; lấy match đầu tiên hợp lệ
        parsed = None
        for text in candidates:
            result = parse_duty_text(text)
            if result is None:
                continue
            errors = result.validate()
            if errors:
                logger.info(f"[auto-scan] Parse được nhưng validation lỗi: {errors}")
                try:
                    await message.add_reaction("⚠️")
                except discord.HTTPException:
                    pass
                return
            parsed = result
            break

        if not parsed:
            logger.debug(f"[auto-scan] Không tìm thấy LOG DUTY trong msg {message.id}")
            return

        # ── Verify STRICT: tên trong LOG DUTY phải khớp với người gửi ──
        # Auto-scan KHÔNG có bypass cho MOD/ADMIN — mọi người chỉ được tự gửi log của mình.
        # Mod muốn log hộ phải dùng /log upload ten:<tên> (slash command có bypass)
        if not _username_matches_author(parsed.username, message.author):
            logger.info(
                f"[auto-scan] Mismatch: parsed='{parsed.username}' "
                f"vs author='{message.author}' (id={message.author.id}). Reject."
            )
            try:
                await message.add_reaction("🚫")
                # Reply private hint (auto-delete sau 20s để không spam channel)
                await message.reply(
                    embed=build_error_embed(
                        f"Tên trong LOG DUTY là **{discord.utils.escape_markdown(parsed.username)}** "
                        f"nhưng bạn là **{discord.utils.escape_markdown(message.author.display_name)}**.\n"
                        "Mỗi người chỉ được tự gửi log của chính mình.\n"
                        "→ Mod muốn log hộ: dùng `/log upload ten:<tên>` hoặc `/log forward`.",
                        title="🚫 Tên không khớp",
                    ),
                    mention_author=False,
                    delete_after=20,
                )
            except discord.HTTPException:
                pass
            return

        # Tên đã khớp → log gắn vào account của người gửi (chính chủ)
        target = message.author

        # Lưu DB — duplicate sẽ raise ValueError do source_message_id unique
        async with AsyncSessionLocal() as session:
            try:
                await _save_duty_log(
                    session=session,
                    guild_id=message.guild.id,
                    user_id=target.id,
                    username=parsed.username,
                    started_at=to_utc(parsed.started_at),
                    ended_at=to_utc(parsed.ended_at),
                    duration_minutes=parsed.duration_minutes,
                    raw_text=parsed.raw_text,
                    source="message",
                    source_message_id=message.id,
                    submitted_by=message.author.id,
                )
                session.add(AuditLog(
                    guild_id=message.guild.id,
                    user_id=message.author.id,
                    username=str(message.author),
                    action=AuditAction.LOG_UPLOADED,
                    detail={
                        "for_user": parsed.username,
                        "duration_minutes": parsed.duration_minutes,
                        "source": "message",
                        "auto": True,
                        "channel_id": str(message.channel.id),
                    },
                    created_at=utcnow(),
                ))
                await session.commit()
                logger.info(
                    f"[auto-scan] Đã lưu log: guild={message.guild.id} "
                    f"user={parsed.username} duration={parsed.duration_minutes}p"
                )
                try:
                    await message.add_reaction("✅")
                except discord.HTTPException:
                    pass

            except ValueError as e:
                # Duplicate (source_message_id đã tồn tại) — react 🔁
                logger.debug(f"[auto-scan] Duplicate skip: {e}")
                try:
                    await message.add_reaction("🔁")
                except discord.HTTPException:
                    pass

            except Exception as e:
                await session.rollback()
                logger.error(f"[auto-scan] Lỗi lưu log: {e}", exc_info=True)
                try:
                    await message.add_reaction("❌")
                except discord.HTTPException:
                    pass

    @staticmethod
    def _extract_message_text(message: discord.Message) -> list[str]:
        """
        Trả về list các đoạn text có thể chứa LOG DUTY:
        - Nội dung trực tiếp của message
        - Forward snapshots (Discord forward feature)
        - Mô tả + fields của các embed
        """
        out: list[str] = []
        if message.content:
            out.append(message.content)

        # Forward feature: message.message_snapshots (discord.py 2.4+)
        for snap in getattr(message, "message_snapshots", None) or []:
            content = getattr(snap, "content", None)
            if content:
                out.append(content)
            for embed in getattr(snap, "embeds", None) or []:
                t = LogDutyCog._embed_to_text(embed)
                if t:
                    out.append(t)

        # Embeds trực tiếp (bot khác có thể post embed)
        for embed in message.embeds:
            t = LogDutyCog._embed_to_text(embed)
            if t:
                out.append(t)

        return out

    @staticmethod
    def _embed_to_text(embed: discord.Embed) -> str:
        """Ghép tất cả phần text của embed thành 1 chuỗi"""
        parts: list[str] = []
        if embed.title:
            parts.append(embed.title)
        if embed.description:
            parts.append(embed.description)
        for field in embed.fields:
            if field.name:
                parts.append(field.name)
            if field.value:
                parts.append(field.value)
        if embed.footer and embed.footer.text:
            parts.append(embed.footer.text)
        return "\n".join(parts)

    @log_group.command(name="upload", description="Upload ảnh LOG DUTY → OCR tự động lưu")
    @app_commands.describe(
        anh="Ảnh chụp màn hình LOG DUTY (JPG/PNG/WEBP, tối đa 5MB)",
        ten="Tên Discord của người trực (để ghép với log)")
    @app_commands.checks.cooldown(rate=5, per=60.0)
    async def log_upload(
        self,
        interaction: discord.Interaction,
        anh: discord.Attachment,
        ten: str | None = None,
    ):
        await interaction.response.defer(ephemeral=True)

        async with AsyncSessionLocal() as session:
            if not await require_member(interaction, session):
                await send_no_permission(interaction, DutyRole.MEMBER)
                return

            # Kiểm tra channel whitelist
            config = await _get_guild_config(session, interaction.guild_id)
            if config and config.log_channel_id and interaction.channel_id != config.log_channel_id:
                await interaction.followup.send(
                    embed=build_error_embed(
                        f"Chỉ được dùng lệnh này trong <#{config.log_channel_id}>"
                    ),
                    ephemeral=True,
                )
                return

        # Validate và tải ảnh
        mime = anh.content_type or "image/unknown"
        if mime not in {"image/jpeg", "image/png", "image/webp"}:
            await interaction.followup.send(
                embed=build_error_embed("Chỉ chấp nhận ảnh JPG, PNG hoặc WEBP."),
                ephemeral=True,
            )
            return

        if anh.size > 5 * 1024 * 1024:
            await interaction.followup.send(
                embed=build_error_embed("Ảnh quá lớn. Tối đa 5MB."),
                ephemeral=True,
            )
            return

        image_bytes = await anh.read()

        # OCR
        parsed = await extract_duty_from_image(image_bytes, mime)
        if parsed is None:
            await interaction.followup.send(
                embed=build_error_embed(
                    "Không tìm thấy định dạng LOG DUTY trong ảnh.\n"
                    "Hãy đảm bảo ảnh chứa đầy đủ các dòng: Tên, Thời gian làm việc, Bắt đầu, Kết thúc."
                ),
                ephemeral=True,
            )
            return

        # Validate logic
        errors = parsed.validate()
        if errors:
            await interaction.followup.send(
                embed=build_error_embed("Dữ liệu không hợp lệ:\n• " + "\n• ".join(errors)),
                ephemeral=True,
            )
            return

        # Nếu tên trong ảnh khác tên truyền vào, dùng tên truyền vào (override)
        display_name = ten or parsed.username

        # ── Verify tên khớp người dùng (member); MOD+ bypass ──
        async with AsyncSessionLocal() as session:
            is_mod = await require_mod(interaction, session)

        if not is_mod and not _username_matches_author(display_name, interaction.user):
            await interaction.followup.send(
                embed=build_error_embed(
                    f"Tên trong LOG DUTY là **{discord.utils.escape_markdown(display_name)}** "
                    f"nhưng bạn là **{discord.utils.escape_markdown(interaction.user.display_name)}**.\n"
                    "Chỉ được upload log của chính mình. Mod+ mới có thể upload hộ người khác.",
                    title="🚫 Tên không khớp",
                ),
                ephemeral=True,
            )
            return

        # Đã verify → log gắn với account interaction.user
        # (MOD bypass: dùng _find_member_by_name để map tên trong ảnh → user khác)
        if is_mod and ten:
            target_user = _find_member_by_name(interaction.guild, ten)
            target_id = target_user.id if target_user else interaction.user.id
        else:
            target_id = interaction.user.id

        parsed_data = {
            "username": display_name,
            "user_discord_id": target_id,
            "duration_minutes": parsed.duration_minutes,
            "started_at": to_utc(parsed.started_at),
            "ended_at": to_utc(parsed.ended_at),
            "raw_text": parsed.raw_text,
            "source": "ocr",
            "source_message_id": None,
        }

        async with AsyncSessionLocal() as session:
            config = await _get_guild_config(session, interaction.guild_id)
            tz = config.timezone if config else None

        embed = build_log_confirm_embed(parsed_data, tz, parsed.is_loose_match)
        view = ConfirmLogView(parsed_data, interaction.user.id, interaction.guild_id)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    @log_group.command(name="forward", description="Paste text LOG DUTY để lưu thủ công")
    @app_commands.describe(text="Nội dung LOG DUTY (copy paste từ bot khác)")
    @app_commands.checks.cooldown(rate=5, per=60.0)
    async def log_forward(
        self,
        interaction: discord.Interaction,
        text: str,
    ):
        await interaction.response.defer(ephemeral=True)

        async with AsyncSessionLocal() as session:
            if not await require_member(interaction, session):
                await send_no_permission(interaction, DutyRole.MEMBER)
                return

        parsed = parse_duty_text(text)
        if parsed is None:
            await interaction.followup.send(
                embed=build_error_embed(
                    "Không nhận diện được định dạng LOG DUTY.\n"
                    "Vui lòng copy đúng định dạng chuẩn."
                ),
                ephemeral=True,
            )
            return

        errors = parsed.validate()
        if errors:
            await interaction.followup.send(
                embed=build_error_embed("Dữ liệu không hợp lệ:\n• " + "\n• ".join(errors)),
                ephemeral=True,
            )
            return

        # ── Verify tên khớp người dùng; MOD+ bypass ──
        async with AsyncSessionLocal() as session:
            is_mod = await require_mod(interaction, session)

        if not is_mod and not _username_matches_author(parsed.username, interaction.user):
            await interaction.followup.send(
                embed=build_error_embed(
                    f"Tên trong LOG DUTY là **{discord.utils.escape_markdown(parsed.username)}** "
                    f"nhưng bạn là **{discord.utils.escape_markdown(interaction.user.display_name)}**.\n"
                    "Chỉ được paste log của chính mình. Mod+ có thể paste hộ người khác.",
                    title="🚫 Tên không khớp",
                ),
                ephemeral=True,
            )
            return

        # MOD bypass: tìm member theo tên parsed; còn lại gắn vào author
        if is_mod:
            target_user = _find_member_by_name(interaction.guild, parsed.username)
            target_id = target_user.id if target_user else interaction.user.id
        else:
            target_id = interaction.user.id

        parsed_data = {
            "username": parsed.username,
            "user_discord_id": target_id,
            "duration_minutes": parsed.duration_minutes,
            "started_at": to_utc(parsed.started_at),
            "ended_at": to_utc(parsed.ended_at),
            "raw_text": parsed.raw_text,
            "source": "forward",
            "source_message_id": None,
        }

        async with AsyncSessionLocal() as session:
            config = await _get_guild_config(session, interaction.guild_id)
            tz = config.timezone if config else None

        embed = build_log_confirm_embed(parsed_data, tz, parsed.is_loose_match)
        view = ConfirmLogView(parsed_data, interaction.user.id, interaction.guild_id)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    @log_group.command(name="view", description="Xem lịch sử chấm công")
    @app_commands.describe(
        tat_ca="Xem TẤT CẢ thành viên dạng bảng (cần MOD+)",
        thanh_vien="Xem log của thành viên cụ thể (cần MOD+). Bỏ trống = xem của mình",
        ten="Filter theo username trong log (vd: 'Imjay'). Cần MOD+",
        trang="Số trang (mặc định: 1)"
    )
    @app_commands.checks.cooldown(rate=10, per=60.0)
    async def log_view(
        self,
        interaction: discord.Interaction,
        tat_ca: bool = False,
        thanh_vien: discord.Member | None = None,
        ten: str | None = None,
        trang: int = 1,
    ):
        await interaction.response.defer(ephemeral=True)

        # tat_ca dùng table → 20 dòng/trang; còn lại group theo ngày → 30 entries
        VIEW_PAGE_SIZE = 20 if tat_ca else 30

        async with AsyncSessionLocal() as session:
            # Quyền: xem all/người khác/ten đều cần MOD
            viewing_other = (
                tat_ca or
                (thanh_vien and thanh_vien.id != interaction.user.id) or
                (ten is not None)
            )
            if viewing_other:
                if not await require_mod(interaction, session):
                    await send_no_permission(interaction, DutyRole.MOD)
                    return
            else:
                if not await require_member(interaction, session):
                    await send_no_permission(interaction, DutyRole.MEMBER)
                    return

            # Build query
            base_q = select(DutyLog).where(DutyLog.guild_id == interaction.guild_id)
            count_q = (
                select(
                    func.count(DutyLog.id),
                    func.coalesce(func.sum(DutyLog.duration_minutes), 0),
                    func.count(func.distinct(DutyLog.user_id)),
                )
                .where(DutyLog.guild_id == interaction.guild_id)
            )

            target_label: str
            if tat_ca:
                # Không filter, lấy tất cả
                target_label = "ALL"
            elif ten:
                base_q = base_q.where(func.lower(DutyLog.username).like(f"%{ten.lower()}%"))
                count_q = count_q.where(func.lower(DutyLog.username).like(f"%{ten.lower()}%"))
                target_label = f"username ~ '{ten}'"
            else:
                target = thanh_vien or interaction.user
                base_q = base_q.where(DutyLog.user_id == target.id)
                count_q = count_q.where(DutyLog.user_id == target.id)
                target_label = str(target.display_name)

            # Đếm tổng + tổng phút + số người
            count_row = (await session.execute(count_q)).first()
            total = count_row[0] or 0
            grand_total = count_row[1] or 0
            unique_users = count_row[2] or 0
            total_pages = max(1, (total + VIEW_PAGE_SIZE - 1) // VIEW_PAGE_SIZE)

            offset = (max(trang, 1) - 1) * VIEW_PAGE_SIZE
            # Khi xem all: order user_id asc rồi started desc để rows cùng user gần nhau
            order_by = (
                [DutyLog.user_id.asc(), DutyLog.started_at.desc()]
                if tat_ca else
                [DutyLog.started_at.desc()]
            )
            rows = await session.execute(
                base_q.order_by(*order_by).offset(offset).limit(VIEW_PAGE_SIZE)
            )
            logs = rows.scalars().all()

            config = await _get_guild_config(session, interaction.guild_id)
            tz = config.timezone if config else None
            guild_name = config.guild_name if config else (interaction.guild.name if interaction.guild else "")

        log_dicts = [
            {
                "id": log.id,
                "started_at": log.started_at,
                "ended_at": log.ended_at,
                "duration_minutes": log.duration_minutes,
                "source": log.source,
                "username": log.username,
            }
            for log in logs
        ]

        if tat_ca:
            embed = build_all_logs_table_embed(
                logs=log_dicts,
                page=trang, total_pages=total_pages,
                total_count=total, grand_total_minutes=grand_total,
                unique_users=unique_users, guild_name=guild_name,
                guild_tz=tz,
            )
        else:
            embed = build_log_view_embed(
                target_label, log_dicts, trang, total_pages, tz,
                total_count=total, grand_total_minutes=grand_total,
            )
        embed.add_field(
            name="🗑️ Xóa log",
            value=f"Dùng `/log delete id:<số>` để xóa. **CHỈ Admin** mới có quyền xóa log.",
            inline=False,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @log_group.command(name="delete", description="Xóa 1 ca trực theo ID (CHỈ Admin)")
    @app_commands.describe(id="ID của ca trực (xem qua /log view)")
    @app_commands.checks.cooldown(rate=5, per=60.0)
    async def log_delete(
        self,
        interaction: discord.Interaction,
        id: int,
    ):
        await interaction.response.defer(ephemeral=True)

        async with AsyncSessionLocal() as session:
            # Quyền: CHỈ ADMIN, không có ngoại lệ (kể cả Mod và chính chủ)
            if not await require_admin(interaction, session):
                await send_no_permission(interaction, DutyRole.ADMIN)
                return

            # Lấy log
            result = await session.execute(
                select(DutyLog).where(DutyLog.id == id).where(DutyLog.guild_id == interaction.guild_id)
            )
            log = result.scalar_one_or_none()

            if log is None:
                await interaction.followup.send(
                    embed=build_error_embed(f"Không tìm thấy log với ID `{id}` trong server này."),
                    ephemeral=True,
                )
                return

            # Snapshot để audit
            snapshot = {
                "log_id": log.id,
                "for_user_id": log.user_id,
                "for_username": log.username,
                "started_at": log.started_at.isoformat() if log.started_at else None,
                "ended_at": log.ended_at.isoformat() if log.ended_at else None,
                "duration_minutes": log.duration_minutes,
                "source": log.source,
            }

            await session.delete(log)
            session.add(AuditLog(
                guild_id=interaction.guild_id,
                user_id=interaction.user.id,
                username=str(interaction.user),
                action=AuditAction.LOG_DELETED,
                detail=snapshot,
                created_at=utcnow(),
            ))
            await session.commit()

        await interaction.followup.send(
            embed=build_success_embed(
                f"Đã xóa log **#{id}** của **{snapshot['for_username']}** "
                f"({snapshot['duration_minutes']} phút)."
            ),
            ephemeral=True,
        )

    @log_upload.error
    @log_forward.error
    @log_view.error
    @log_delete.error
    async def on_cooldown(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.CommandOnCooldown):
            await interaction.response.send_message(
                embed=build_error_embed(
                    f"Bạn dùng lệnh quá nhanh! Thử lại sau **{error.retry_after:.0f}s**."
                ),
                ephemeral=True,
            )
        else:
            logger.error(f"Lỗi command log: {error}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    embed=build_error_embed("Đã xảy ra lỗi không mong muốn."), ephemeral=True
                )


def _find_member_by_name(guild: discord.Guild, name: str) -> discord.Member | None:
    """Tìm member theo display_name hoặc username (không phân biệt hoa thường)"""
    name_lower = name.lower().strip()
    for member in guild.members:
        if member.display_name.lower() == name_lower or member.name.lower() == name_lower:
            return member
    return None


async def _get_guild_config(session: AsyncSession, guild_id: int) -> GuildConfig | None:
    result = await session.execute(
        select(GuildConfig).where(GuildConfig.guild_id == guild_id)
    )
    return result.scalar_one_or_none()


async def setup(bot: commands.Bot):
    await bot.add_cog(LogDutyCog(bot))
