"""
log_duty.py — Cog xử lý /log upload, /log forward, /log view, /log delete
Luồng upload: nhận ảnh → OCR → parse → validate → confirm → lưu DB
Luồng forward: nhận text → parse → validate → confirm → lưu DB
Auto-scan: on_message tự động parse LOG DUTY trong log_channel
"""
import logging
import io
from datetime import datetime, timedelta

import discord
from discord.ext import commands
from discord import app_commands
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from models.base import AsyncSessionLocal
from models.duty_log import DutyLog
from models.guild import GuildConfig
from models.audit_log import AuditLog, AuditAction
from bot.utils.ocr import extract_duty_from_image, warmup_ocr
from bot.utils.parser import parse_duty_text
from bot.utils.permissions import require_member, require_mod, require_admin, send_no_permission, DutyRole
from bot.utils.embed_builder import (
    build_log_confirm_embed, build_log_view_embed, build_all_logs_table_embed,
    build_error_embed, build_success_embed,
    build_log_accepted_embed, build_log_rejected_embed,
    build_log_invalid_embed, build_log_name_mismatch_embed,
    build_log_duplicate_embed,
    build_log_impersonation_embed, build_log_ambiguous_name_embed,
)
from bot.utils.time_utils import to_utc, utcnow

logger = logging.getLogger(__name__)

PAGE_SIZE = 10


class ConfirmLogView(discord.ui.View):
    """Nút Xác nhận / Huỷ khi upload log. Timeout 60 giây."""

    def __init__(self, parsed_data: dict, submitter_id: int, guild_id: int):
        super().__init__(timeout=60)
        self.parsed_data = parsed_data
        self.submitter_id = submitter_id
        self.guild_id = guild_id
        self.confirmed = False
        self._message: discord.WebhookMessage | None = None  # set sau followup.send

    def set_message(self, msg: discord.WebhookMessage) -> None:
        """Lưu reference đến message để on_timeout có thể edit"""
        self._message = msg

    async def on_timeout(self) -> None:
        """Disable tất cả nút và thông báo hết giờ khi view timeout"""
        for child in self.children:
            child.disabled = True
        if self._message:
            try:
                await self._message.edit(
                    content="⏰ Hết thời gian xác nhận (60 giây). Hãy chạy lại lệnh nếu muốn lưu.",
                    view=self,
                )
            except discord.HTTPException:
                pass

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
                    discord_handle=self.parsed_data.get("discord_handle"),
                    exit_reason=self.parsed_data.get("exit_reason"),
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

            except ValueError as e:
                await session.rollback()
                await interaction.followup.send(
                    embed=build_error_embed(str(e)), ephemeral=True
                )
                # Disable nút sau khi lỗi để không submit lại
                for child in self.children:
                    child.disabled = True
                try:
                    await interaction.edit_original_response(view=self)
                except discord.HTTPException:
                    pass
                self.stop()
                return

            except IntegrityError as e:
                # DB-level uq_duty_log_entry vi phạm → race condition Layer 2
                # (2 user submit cùng ca trực đồng thời). Hiển thị message thân thiện.
                await session.rollback()
                logger.info(f"Race condition duplicate caught at DB level: {e.orig}")
                await interaction.followup.send(
                    embed=build_error_embed(
                        "Ca trực này vừa được lưu (có thể bạn nhấn 2 lần hoặc submit trùng).\n"
                        "Vui lòng kiểm tra lại với `/log view`."
                    ),
                    ephemeral=True,
                )
                for child in self.children:
                    child.disabled = True
                try:
                    await interaction.edit_original_response(view=self)
                except discord.HTTPException:
                    pass
                self.stop()
                return

            except Exception as e:
                await session.rollback()
                logger.error(f"Lỗi lưu duty log: {e}", exc_info=True)
                await interaction.followup.send(
                    embed=build_error_embed("Lưu thất bại do lỗi hệ thống. Thử lại sau."),
                    ephemeral=True,
                )
                for child in self.children:
                    child.disabled = True
                try:
                    await interaction.edit_original_response(view=self)
                except discord.HTTPException:
                    pass
                self.stop()
                return

        embed = build_success_embed(
            f"Đã lưu log trực cho **{self.parsed_data['username']}**!\n"
            f"⏱ {self.parsed_data['duration_minutes']} phút"
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

        for child in self.children:
            child.disabled = True
        try:
            await interaction.edit_original_response(view=self)
        except discord.HTTPException:
            pass
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
    discord_handle: str | None = None,
    exit_reason: str | None = None,
) -> DutyLog:
    """
    Lưu DutyLog vào DB với 3 tầng bảo vệ:

    Tầng 0 — Kiểm tra tương lai:
        Ca trực không được bắt đầu > 30 phút trong tương lai.
        Cho phép bất kỳ ngày nào trong quá khứ.

    Tầng 1 — source_message_id (auto-scan / Discord forward):
        Chặn cùng message Discord được scan 2 lần.

    Tầng 2 — (guild_id, user_id, started_at, ended_at) exact duplicate:
        Chặn cùng ca trực được submit lại dưới dạng text/ảnh khác nhau.
        DB constraint uq_duty_log_entry là backup phòng race condition.

    Tầng 3 — Overlap check:
        Chặn ca trực mới chồng lấp thời gian với ca trực đã tồn tại của cùng user.
        Ví dụ: đã có 08:00-12:00, không thể thêm 10:00-14:00.
        Cho phép ca liên tiếp (kết thúc = bắt đầu ca tiếp).
    """
    now = utcnow()

    # ── Tầng -1: Username lock — chống impersonation triệt để ──
    # Mỗi `username` (sau normalize) trong 1 guild chỉ được thuộc về 1 user_id duy nhất.
    # User đầu tiên submit log với tên X → tên X locked vào user_id đó forever.
    # User khác cố gắng dùng tên X → REJECT.
    #
    # Đây là phòng tuyến cuối: ngay cả khi attacker bypass identity check
    # (đổi nick thành tên victim), DB sẽ chặn vì username đã có owner khác.
    parsed_lower = username.strip().lower()
    if parsed_lower:
        existing_owner = await session.execute(
            select(DutyLog.user_id)
            .where(DutyLog.guild_id == guild_id)
            .where(func.lower(func.trim(DutyLog.username)) == parsed_lower)
            .order_by(DutyLog.id.asc())
            .limit(1)
        )
        first_owner_id = existing_owner.scalar_one_or_none()
        if first_owner_id is not None and first_owner_id != user_id:
            logger.warning(
                f"[username-lock] User {user_id} cố gắng dùng tên '{username}' "
                f"đã thuộc về user {first_owner_id} (lưu trước đó)"
            )
            raise ValueError(
                f"Tên **{username}** đã được dùng bởi tài khoản khác trước đây. "
                "Bạn không thể chấm công với tên này.\n\n"
                "Nếu đây là tên thật của bạn (có user khác đã chiếm trước), "
                "**vui lòng liên hệ ban lãnh đạo** để xử lý."
            )

    # ── Tầng 0: Không cho phép ca trực ở tương lai ──
    if started_at > now + timedelta(minutes=30):
        raise ValueError(
            f"Không thể log ca trực chưa bắt đầu.\n"
            f"Giờ bắt đầu trong log: **{started_at.strftime('%H:%M %d/%m/%Y')} UTC**\n"
            f"Thời gian hiện tại: **{now.strftime('%H:%M %d/%m/%Y')} UTC**\n"
            "→ Chỉ được log ca trực đã hoặc đang diễn ra."
        )
    if ended_at > now + timedelta(minutes=5):
        raise ValueError(
            f"Không thể log ca trực chưa kết thúc.\n"
            f"Giờ kết thúc trong log: **{ended_at.strftime('%H:%M %d/%m/%Y')} UTC**\n"
            "→ Vui lòng chờ ca trực kết thúc rồi mới nộp log."
        )

    # ── Tầng 1: source_message_id unique (auto-scan) ──
    if source_message_id:
        existing = await session.execute(
            select(DutyLog).where(DutyLog.source_message_id == source_message_id)
        )
        if existing.scalar_one_or_none():
            raise ValueError("Log này đã được lưu trước đó (duplicate message)")

    # ── Tầng 2: Exact duplicate (guild, user, start, end) ──
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
            f"Ca trực **{username}** từ "
            f"`{started_at.strftime('%H:%M %d/%m/%Y')}` đến "
            f"`{ended_at.strftime('%H:%M %d/%m/%Y')}` đã được lưu rồi."
        )

    # ── Tầng 3: Overlap check — chồng lấp thời gian ──
    # A chồng B khi: A.start < B.end AND A.end > B.start
    # Cho phép ca liên tiếp (A.end == B.start)
    overlap = await session.execute(
        select(DutyLog)
        .where(DutyLog.guild_id == guild_id)
        .where(DutyLog.user_id == user_id)
        .where(DutyLog.started_at < ended_at)    # ca cũ bắt đầu trước khi ca mới kết thúc
        .where(DutyLog.ended_at > started_at)    # ca cũ kết thúc sau khi ca mới bắt đầu
        .limit(1)
    )
    conflicting = overlap.scalar_one_or_none()
    if conflicting:
        raise ValueError(
            f"Ca trực này **chồng lấp** với ca trực đã tồn tại của **{username}**:\n"
            f"• Đã có: `{conflicting.started_at.strftime('%H:%M %d/%m/%Y')}` → "
            f"`{conflicting.ended_at.strftime('%H:%M %d/%m/%Y')}` "
            f"({conflicting.duration_minutes} phút)\n"
            f"• Muốn thêm: `{started_at.strftime('%H:%M %d/%m/%Y')}` → "
            f"`{ended_at.strftime('%H:%M %d/%m/%Y')}` "
            f"({duration_minutes} phút)\n"
            "→ Hai ca trực không được trùng thời gian."
        )

    # ── Auto-link với MemberSchedule (nếu có lịch khớp) ──
    schedule_id: int | None = None
    try:
        from bot.utils.schedule_engine import find_matching_schedule
        from models.guild import GuildConfig
        # Lấy timezone của guild để engine tính weekday đúng
        cfg_row = await session.execute(
            select(GuildConfig.timezone).where(GuildConfig.guild_id == guild_id)
        )
        guild_tz = cfg_row.scalar_one_or_none() or "Asia/Ho_Chi_Minh"
        matched = await find_matching_schedule(
            session, guild_id, user_id, started_at, ended_at, guild_tz
        )
        if matched:
            schedule_id = matched.id
    except Exception as e:
        # Auto-link là nice-to-have, không nên fail save log
        logger.debug(f"Auto-link schedule skipped: {type(e).__name__}: {e}")

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
        schedule_id=schedule_id,
        discord_handle=discord_handle,
        exit_reason=exit_reason,
        created_at=utcnow(),
    )
    session.add(log)
    # Flush ngay để bắt IntegrityError do race condition: 2 request đồng thời
    # có thể cùng qua 3 tầng check ở application (vì check không atomic), nhưng
    # chỉ 1 INSERT thành công nhờ DB unique constraint (source_message_id /
    # uq_duty_log_entry). Catch lỗi và trả message thân thiện thay vì 500 chung.
    try:
        await session.flush()
    except IntegrityError as e:
        await session.rollback()
        err_msg = str(getattr(e, "orig", None) or e)
        if "source_message_id" in err_msg:
            raise ValueError("Log này đã được lưu trước đó (duplicate message)")
        if "uq_duty_log_entry" in err_msg:
            raise ValueError(
                f"Ca trực **{username}** từ "
                f"`{started_at.strftime('%H:%M %d/%m/%Y')}` đến "
                f"`{ended_at.strftime('%H:%M %d/%m/%Y')}` đã được lưu rồi."
            )
        raise
    return log


def _normalize_name(s: str | None) -> str:
    """Lowercase + strip non-alphanumeric (chấp nhận tiếng Việt) để so sánh tên fuzzy"""
    if not s:
        return ""
    import re
    return re.sub(
        r"[^a-z0-9àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ]",
        "", s.lower()
    )


def _strip_role_tag(name: str | None) -> str:
    """
    Bỏ các prefix kiểu role/squad tag để lấy tên thuần.
    Hỗ trợ:
      "[VT] Tom Nguyễn"   → "Tom Nguyễn"
      "(EMS) Tom Nguyễn"  → "Tom Nguyễn"
      "【VT】Tom Nguyễn"   → "Tom Nguyễn"
      "VT | Tom Nguyễn"   → "Tom Nguyễn"
      "VT - Tom Nguyễn"   → "Tom Nguyễn" (nếu VT ngắn)

    Trả về tên đã strip. Nếu không có pattern → trả về tên gốc.
    """
    import re
    if not name:
        return ""
    s = name.strip()
    # [ABC] / (ABC) / 【ABC】 / 「ABC」 prefix (tag dài tối đa 15 ký tự)
    s = re.sub(r"^[\[\(\{【「]([^\]\)\}】」]{1,15})[\]\)\}】」]\s*", "", s)
    # "ABC | " hoặc "ABC• " prefix (tag dài tối đa 15 ký tự trước |)
    s = re.sub(r"^[^|•]{1,15}[|•]\s*", "", s)
    return s.strip()


def _identity_candidates(author: "discord.abc.User | discord.Member") -> list[str]:
    """
    Trả về tất cả tên định danh khả dĩ của 1 user — bao gồm cả raw và sau khi
    strip role tag prefix. Dùng để so sánh STRICT exact match.
    """
    raw_fields = [
        getattr(author, "name", "") or "",
        getattr(author, "global_name", None) or "",
        getattr(author, "display_name", "") or "",
        getattr(author, "nick", None) or "",
    ]
    out: list[str] = []
    for raw in raw_fields:
        if not raw:
            continue
        out.append(raw)
        stripped = _strip_role_tag(raw)
        if stripped and stripped != raw:
            out.append(stripped)
    return out


def _resolve_name_owner(
    guild: discord.Guild | None,
    parsed_name: str,
) -> tuple[str, list[discord.Member]]:
    """
    Tìm tất cả member trong guild khớp với parsed_name (qua _username_matches_author).
    Dùng để chống IMPERSONATION: user không thể đổi nick thành tên người khác để chấm công hộ.

    Returns:
        ("ok",        [member])    — chỉ DUY NHẤT 1 người khớp (an toàn)
        ("ambiguous", [members])   — nhiều người khớp (cần đặt nick rõ ràng hơn)
        ("none",      [])          — không ai trong server có tên này
    """
    if guild is None:
        return "none", []
    parsed_n = _normalize_name(parsed_name)
    if not parsed_n:
        return "none", []

    matches: list[discord.Member] = []
    for m in guild.members:
        if _username_matches_author(parsed_name, m):
            matches.append(m)

    if not matches:
        return "none", []
    if len(matches) > 1:
        return "ambiguous", matches
    return "ok", matches


def _username_matches_author(parsed_name: str, author: discord.abc.User) -> bool:
    """
    STRICT: parsed_name phải KHỚP CHÍNH XÁC (sau normalize) với một trong các tên
    định danh của Discord user — bao gồm cả raw và sau khi strip role tag prefix.

    Strip 2 chiều: cả parsed_name VÀ candidate đều thử strip tag trước khi compare.
    Tag mẫu hỗ trợ (≤15 ký tự trước dấu | hoặc trong [...] / (...) / 【...】):
      - "TTS | Tên", "BS | Tên", "PK | Tên", "TK | Tên"
      - "QLBS | Tên", "TKBS | Tên", "VP | Tên", "VT | Tên"
      - "[EMS] Tên", "(VT) Tên", "【EMS】Tên"

    Không match substring lỏng (đã bỏ ở audit để chống impersonation).
    """
    if not parsed_name:
        return False

    # Tạo set các biến thể của parsed name: raw + stripped
    parsed_variants: set[str] = set()
    pn_raw = _normalize_name(parsed_name)
    if pn_raw:
        parsed_variants.add(pn_raw)
    pn_stripped = _normalize_name(_strip_role_tag(parsed_name))
    if pn_stripped:
        parsed_variants.add(pn_stripped)
    if not parsed_variants:
        return False

    # So sánh với mọi biến thể của candidate
    for candidate in _identity_candidates(author):
        cand_n = _normalize_name(candidate)
        if cand_n and cand_n in parsed_variants:
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
        if not config.log_channel_id:
            return
        if message.channel.id != config.log_channel_id:
            return

        # Trích xuất tất cả text candidates: content gốc + forward snapshots + embeds
        candidates = self._extract_message_text(message)
        if not candidates:
            return

        logger.debug(
            f"[auto-scan] Quét msg {message.id} từ {message.author}: "
            f"{len(candidates)} candidate(s)"
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
                    await message.reply(
                        embed=build_log_invalid_embed(errors, message.author),
                        mention_author=False,
                        delete_after=60,
                    )
                except discord.HTTPException:
                    pass
                return
            parsed = result
            break

        if not parsed:
            return

        # ── Verify STRICT: tên trong LOG DUTY phải DUY NHẤT thuộc về người gửi ──
        # Iterate toàn bộ guild members → tìm ai khớp với parsed.username.
        # Chống IMPERSONATION: user không thể đổi nick thành tên người khác để chấm công hộ.
        status, matches = _resolve_name_owner(message.guild, parsed.username)
        if status == "none":
            logger.info(
                f"[auto-scan] Tên không thuộc ai: parsed='{parsed.username}' "
                f"author={message.author} (id={message.author.id})"
            )
            try:
                await message.add_reaction("🚫")
                await message.reply(
                    embed=build_log_name_mismatch_embed(parsed.username, message.author),
                    mention_author=False,
                    delete_after=60,
                )
            except discord.HTTPException:
                pass
            return
        if status == "ambiguous":
            logger.warning(
                f"[auto-scan] Ambiguous name: parsed='{parsed.username}' "
                f"matches={[m.display_name for m in matches]}"
            )
            try:
                await message.add_reaction("⚠️")
                await message.reply(
                    embed=build_log_ambiguous_name_embed(
                        parsed.username, matches, message.author
                    ),
                    mention_author=False,
                    delete_after=90,
                )
            except discord.HTTPException:
                pass
            return
        # status == "ok": có duy nhất 1 người khớp
        if matches[0].id != message.author.id:
            logger.warning(
                f"[auto-scan] IMPERSONATION: author={message.author.id} "
                f"({message.author.display_name}) cố gắng chấm công cho "
                f"{matches[0].id} ({matches[0].display_name})"
            )
            try:
                await message.add_reaction("🚫")
                await message.reply(
                    embed=build_log_impersonation_embed(
                        parsed.username, matches[0], message.author
                    ),
                    mention_author=False,
                    delete_after=90,
                )
                # Audit log impersonation attempt
                async with AsyncSessionLocal() as audit_session:
                    audit_session.add(AuditLog(
                        guild_id=message.guild.id,
                        user_id=message.author.id,
                        username=str(message.author),
                        action=AuditAction.LOG_REJECTED,
                        detail={
                            "reason": "impersonation",
                            "parsed_name": parsed.username,
                            "real_owner_id": str(matches[0].id),
                            "real_owner_name": matches[0].display_name,
                        },
                        created_at=utcnow(),
                    ))
                    await audit_session.commit()
            except discord.HTTPException:
                pass
            return

        # Lưu DB
        async with AsyncSessionLocal() as session:
            try:
                await _save_duty_log(
                    session=session,
                    guild_id=message.guild.id,
                    user_id=message.author.id,
                    username=parsed.username,
                    started_at=to_utc(parsed.started_at),
                    ended_at=to_utc(parsed.ended_at),
                    duration_minutes=parsed.duration_minutes,
                    raw_text=parsed.raw_text,
                    source="message",
                    source_message_id=message.id,
                    submitted_by=message.author.id,
                    discord_handle=parsed.discord_handle,
                    exit_reason=parsed.exit_reason,
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
                # ✅ Embed đẹp xác nhận đã lưu — kèm thông tin ca trực để member kiểm tra
                try:
                    await message.add_reaction("✅")
                    config_tz = config.timezone if config else None
                    await message.reply(
                        embed=build_log_accepted_embed(parsed, message.author, config_tz),
                        mention_author=False,
                    )
                except discord.HTTPException:
                    pass

            except ValueError as e:
                err_str = str(e)
                # Duplicate → react 🔁 + embed nhẹ
                if "đã được lưu" in err_str or "duplicate" in err_str.lower():
                    logger.debug(f"[auto-scan] Duplicate skip: {e}")
                    try:
                        await message.add_reaction("🔁")
                        await message.reply(
                            embed=build_log_duplicate_embed(message.author),
                            mention_author=False,
                            delete_after=30,
                        )
                    except discord.HTTPException:
                        pass
                else:
                    # Overlap, tương lai, etc. → reject embed đầy đủ
                    logger.info(f"[auto-scan] Validation reject: {e}")
                    try:
                        await message.add_reaction("🚫")
                        await message.reply(
                            embed=build_log_rejected_embed(parsed, err_str, message.author),
                            mention_author=False,
                            delete_after=60,
                        )
                    except discord.HTTPException:
                        pass

            except IntegrityError as e:
                # Race condition Layer 2 (DB UniqueConstraint) — coi như duplicate
                await session.rollback()
                logger.info(f"[auto-scan] DB-level duplicate (race): {e.orig}")
                try:
                    await message.add_reaction("🔁")
                    await message.reply(
                        embed=build_log_duplicate_embed(message.author),
                        mention_author=False,
                        delete_after=30,
                    )
                except discord.HTTPException:
                    pass

            except Exception as e:
                await session.rollback()
                logger.error(f"[auto-scan] Lỗi lưu log: {e}", exc_info=True)
                try:
                    await message.add_reaction("❌")
                    await message.reply(
                        embed=build_error_embed(
                            "Đã xảy ra lỗi hệ thống khi lưu log. "
                            "Vui lòng thử lại sau ít phút.\n\n"
                            "_Nếu cần hỗ trợ vui lòng liên hệ ban lãnh đạo._",
                            title="❌ Lỗi hệ thống",
                        ),
                        mention_author=False,
                        delete_after=30,
                    )
                except discord.HTTPException:
                    pass

    @staticmethod
    def _extract_message_text(message: discord.Message) -> list[str]:
        """
        Trả về list các đoạn text có thể chứa LOG DUTY:
        - Nội dung trực tiếp của message
        - Forward snapshots (Discord forward feature, discord.py 2.4+)
        - Mô tả + fields của các embed
        """
        out: list[str] = []
        if message.content:
            out.append(message.content)

        for snap in getattr(message, "message_snapshots", None) or []:
            content = getattr(snap, "content", None)
            if content:
                out.append(content)
            for embed in getattr(snap, "embeds", None) or []:
                t = LogDutyCog._embed_to_text(embed)
                if t:
                    out.append(t)

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

    @log_group.command(name="upload", description="Upload ảnh LOG DUTY của bạn → OCR tự động lưu")
    @app_commands.describe(
        anh="Ảnh chụp màn hình LOG DUTY (JPG/PNG/WEBP, tối đa 5MB)",
    )
    @app_commands.checks.cooldown(rate=5, per=60.0)
    async def log_upload(
        self,
        interaction: discord.Interaction,
        anh: discord.Attachment,
    ):
        """
        STRICT MODE: Mỗi user chỉ được upload log của CHÍNH MÌNH.
        Mod/Admin cũng KHÔNG được upload hộ — đảm bảo tính chính xác và truy vết.
        Tên trong LOG DUTY phải khớp display_name/name/global_name/nick của người gửi.
        """
        await interaction.response.defer(ephemeral=True)

        async with AsyncSessionLocal() as session:
            if not await require_member(interaction, session):
                await send_no_permission(interaction, DutyRole.MEMBER)
                return

            config = await _get_guild_config(session, interaction.guild_id)
            if config and config.log_channel_id and interaction.channel_id != config.log_channel_id:
                await interaction.followup.send(
                    embed=build_error_embed(
                        f"Chỉ được dùng lệnh này trong <#{config.log_channel_id}>"
                    ),
                    ephemeral=True,
                )
                return

        # Validate ảnh
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

        # OCR — chạy trong thread pool, không block event loop
        parsed = await extract_duty_from_image(image_bytes, mime)
        if parsed is None:
            await interaction.followup.send(
                embed=build_error_embed(
                    "Không tìm thấy định dạng LOG DUTY trong ảnh.\n"
                    "Hãy đảm bảo ảnh chứa đầy đủ: **Tên**, **Thời gian làm việc**, "
                    "**Thời gian bắt đầu**, **Thời gian kết thúc**.\n"
                    "Nếu ảnh mờ, hãy thử chụp lại rõ hơn hoặc dùng `/log forward` để paste text."
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

        # ── STRICT: tên DUY NHẤT thuộc về người gửi (chống impersonation qua nick) ──
        status, matches = _resolve_name_owner(interaction.guild, parsed.username)
        if status == "none":
            await interaction.followup.send(
                embed=build_log_name_mismatch_embed(parsed.username, interaction.user),
                ephemeral=True,
            )
            return
        if status == "ambiguous":
            await interaction.followup.send(
                embed=build_log_ambiguous_name_embed(parsed.username, matches, interaction.user),
                ephemeral=True,
            )
            return
        if matches[0].id != interaction.user.id:
            logger.warning(
                f"[/log upload] IMPERSONATION: user={interaction.user.id} "
                f"({interaction.user.display_name}) cố gắng chấm công cho "
                f"{matches[0].id} ({matches[0].display_name})"
            )
            async with AsyncSessionLocal() as audit_session:
                audit_session.add(AuditLog(
                    guild_id=interaction.guild_id,
                    user_id=interaction.user.id,
                    username=str(interaction.user),
                    action=AuditAction.LOG_REJECTED,
                    detail={
                        "reason": "impersonation",
                        "source": "ocr",
                        "parsed_name": parsed.username,
                        "real_owner_id": str(matches[0].id),
                    },
                    created_at=utcnow(),
                ))
                await audit_session.commit()
            await interaction.followup.send(
                embed=build_log_impersonation_embed(
                    parsed.username, matches[0], interaction.user
                ),
                ephemeral=True,
            )
            return

        target_id = interaction.user.id
        parsed_data = {
            "username": parsed.username,
            "user_discord_id": target_id,
            "duration_minutes": parsed.duration_minutes,
            "started_at": to_utc(parsed.started_at),
            "ended_at": to_utc(parsed.ended_at),
            "raw_text": parsed.raw_text,
            "source": "ocr",
            "source_message_id": None,
            "discord_handle": parsed.discord_handle,
            "exit_reason": parsed.exit_reason,
        }

        async with AsyncSessionLocal() as session:
            config = await _get_guild_config(session, interaction.guild_id)
            tz = config.timezone if config else None

        embed = build_log_confirm_embed(parsed_data, tz, parsed.is_loose_match)
        view = ConfirmLogView(parsed_data, interaction.user.id, interaction.guild_id)
        msg = await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        view.set_message(msg)

    @log_group.command(name="forward", description="Paste text LOG DUTY của bạn để lưu thủ công")
    @app_commands.describe(text="Nội dung LOG DUTY (copy paste từ bot chấm công)")
    @app_commands.checks.cooldown(rate=5, per=60.0)
    async def log_forward(
        self,
        interaction: discord.Interaction,
        text: str,
    ):
        """
        STRICT MODE: Mỗi user chỉ được forward log của CHÍNH MÌNH.
        Mod/Admin cũng KHÔNG được forward hộ — đảm bảo tính chính xác và truy vết.
        """
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
                    "Vui lòng copy đúng định dạng:\n"
                    "```\nLOG DUTY\nTên: ...\nThời gian làm việc: X phút\n"
                    "Thời gian bắt đầu: DD/MM/YYYY HH:MM:SS\n"
                    "Thời gian kết thúc: DD/MM/YYYY HH:MM:SS\n```"
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

        # ── STRICT: tên DUY NHẤT thuộc về người gửi (chống impersonation qua nick) ──
        status, matches = _resolve_name_owner(interaction.guild, parsed.username)
        if status == "none":
            await interaction.followup.send(
                embed=build_log_name_mismatch_embed(parsed.username, interaction.user),
                ephemeral=True,
            )
            return
        if status == "ambiguous":
            await interaction.followup.send(
                embed=build_log_ambiguous_name_embed(parsed.username, matches, interaction.user),
                ephemeral=True,
            )
            return
        if matches[0].id != interaction.user.id:
            logger.warning(
                f"[/log forward] IMPERSONATION: user={interaction.user.id} "
                f"({interaction.user.display_name}) cố gắng chấm công cho "
                f"{matches[0].id} ({matches[0].display_name})"
            )
            async with AsyncSessionLocal() as audit_session:
                audit_session.add(AuditLog(
                    guild_id=interaction.guild_id,
                    user_id=interaction.user.id,
                    username=str(interaction.user),
                    action=AuditAction.LOG_REJECTED,
                    detail={
                        "reason": "impersonation",
                        "source": "forward",
                        "parsed_name": parsed.username,
                        "real_owner_id": str(matches[0].id),
                    },
                    created_at=utcnow(),
                ))
                await audit_session.commit()
            await interaction.followup.send(
                embed=build_log_impersonation_embed(
                    parsed.username, matches[0], interaction.user
                ),
                ephemeral=True,
            )
            return

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
            "discord_handle": parsed.discord_handle,
            "exit_reason": parsed.exit_reason,
        }

        async with AsyncSessionLocal() as session:
            config = await _get_guild_config(session, interaction.guild_id)
            tz = config.timezone if config else None

        embed = build_log_confirm_embed(parsed_data, tz, parsed.is_loose_match)
        view = ConfirmLogView(parsed_data, interaction.user.id, interaction.guild_id)
        msg = await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        view.set_message(msg)

    @log_group.command(name="view", description="Xem lịch sử chấm công")
    @app_commands.describe(
        tat_ca="Xem TẤT CẢ thành viên dạng bảng (cần MOD+)",
        thanh_vien="Xem log của thành viên cụ thể (cần MOD+). Bỏ trống = xem của mình",
        ten="Filter theo username trong log. Cần MOD+",
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

        VIEW_PAGE_SIZE = 20 if tat_ca else 30

        async with AsyncSessionLocal() as session:
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

            count_row = (await session.execute(count_q)).first()
            total = count_row[0] or 0
            grand_total = count_row[1] or 0
            unique_users = count_row[2] or 0
            total_pages = max(1, (total + VIEW_PAGE_SIZE - 1) // VIEW_PAGE_SIZE)

            offset = (max(trang, 1) - 1) * VIEW_PAGE_SIZE
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
            value="Dùng `/log delete id:<số>` để xóa. **CHỈ Admin** mới có quyền xóa log.",
            inline=False,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @log_group.command(
        name="scan",
        description="Quét lịch sử kênh chấm công để bắt LOG DUTY bị bỏ sót (Mod+)",
    )
    @app_commands.describe(
        limit="Số tin nhắn quét gần nhất (mặc định 200, tối đa 1000)",
    )
    @app_commands.checks.cooldown(rate=1, per=120.0)
    async def log_scan(self, interaction: discord.Interaction, limit: int = 200):
        await interaction.response.defer(ephemeral=True, thinking=True)
        async with AsyncSessionLocal() as session:
            if not await require_mod(interaction, session):
                await send_no_permission(interaction, DutyRole.MOD)
                return
            config = await _get_guild_config(session, interaction.guild_id)

        if not config or not config.log_channel_id:
            await interaction.followup.send(
                embed=build_error_embed(
                    "Server chưa setup channel chấm công. Dùng `/setup channel` trước."
                ),
                ephemeral=True,
            )
            return

        limit = max(1, min(int(limit), 1000))
        from bot.tasks.schedule_tasks import backfill_scan_guild
        stats = await backfill_scan_guild(
            self.bot, interaction.guild, config.log_channel_id, limit=limit,
        )

        if "error" in stats:
            err_map = {
                "channel_not_found": "Không tìm thấy channel chấm công.",
                "no_permission_read_history": "Bot không có quyền **Read Message History** trong channel chấm công.",
            }
            msg = err_map.get(stats["error"], f"Lỗi: {stats['error']}")
            await interaction.followup.send(embed=build_error_embed(msg), ephemeral=True)
            return

        channel_mention = f"<#{config.log_channel_id}>"
        embed = discord.Embed(
            title="🔍  Quét backfill hoàn tất",
            description=(
                f"Đã quét **{stats['scanned']}** tin nhắn gần nhất trong {channel_mention}.\n\n"
                f"```diff\n"
                f"+ {stats['saved']} log MỚI đã lưu\n"
                f"  {stats['dup']} đã có trong DB (skip)\n"
                f"  {stats['invalid']} parse được nhưng validate lỗi\n"
                f"  {stats['no_match']} tên không khớp author (skip)\n"
                f"```"
            ),
            color=0x10B981 if stats['saved'] > 0 else 0x64748B,
        )
        embed.set_footer(text="Job idempotent — chạy lại nhiều lần không sinh duplicate")
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
            if not await require_admin(interaction, session):
                await send_no_permission(interaction, DutyRole.ADMIN)
                return

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

    @log_group.command(
        name="rename",
        description="Đổi tên người chấm công — áp dụng cho mọi log cũ (CHỈ Admin)",
    )
    @app_commands.describe(
        old_name="Tên cũ trong log (case-insensitive)",
        new_name="Tên mới sẽ ghi lên các log đó",
        reason="Lý do đổi (≥3 ký tự, sẽ ghi audit log)",
    )
    @app_commands.checks.cooldown(rate=3, per=60.0)
    async def log_rename(
        self,
        interaction: discord.Interaction,
        old_name: str,
        new_name: str,
        reason: str,
    ):
        """Mass-rename: update mọi DutyLog có username == old_name trong guild.

        Use case: nhân viên đổi tên character → các log cũ vẫn lưu tên cũ,
        admin chạy lệnh này để đồng bộ tên. Username lock (Tầng -1 ở
        _save_duty_log) sẽ tự động ánh xạ user_id → tên mới sau khi rename.
        """
        await interaction.response.defer(ephemeral=True)

        old_clean = old_name.strip()
        new_clean = new_name.strip()
        reason_clean = reason.strip()

        if len(old_clean) == 0 or len(new_clean) == 0:
            await interaction.followup.send(
                embed=build_error_embed("Tên cũ và tên mới không được rỗng."),
                ephemeral=True,
            )
            return
        if len(reason_clean) < 3:
            await interaction.followup.send(
                embed=build_error_embed("Phải ghi lý do (≥3 ký tự) để lưu audit log."),
                ephemeral=True,
            )
            return
        if old_clean.lower() == new_clean.lower():
            await interaction.followup.send(
                embed=build_error_embed("Tên cũ và tên mới giống nhau (so sánh case-insensitive)."),
                ephemeral=True,
            )
            return
        if len(new_clean) > 100:
            await interaction.followup.send(
                embed=build_error_embed("Tên mới quá dài (tối đa 100 ký tự)."),
                ephemeral=True,
            )
            return

        async with AsyncSessionLocal() as session:
            if not await require_admin(interaction, session):
                await send_no_permission(interaction, DutyRole.ADMIN)
                return

            # Tìm tất cả log khớp tên cũ (lowercase + trimmed)
            matched = await session.execute(
                select(DutyLog)
                .where(DutyLog.guild_id == interaction.guild_id)
                .where(func.lower(func.trim(DutyLog.username)) == old_clean.lower())
            )
            logs = list(matched.scalars().all())

            if not logs:
                await interaction.followup.send(
                    embed=build_error_embed(
                        f"Không có log nào của **{old_clean}** trong server này. "
                        "Kiểm tra lại chính tả (so sánh không phân biệt hoa thường)."
                    ),
                    ephemeral=True,
                )
                return

            # Verify tên mới chưa thuộc về user_id khác (tránh conflict username lock)
            new_owner = await session.execute(
                select(DutyLog.user_id)
                .where(DutyLog.guild_id == interaction.guild_id)
                .where(func.lower(func.trim(DutyLog.username)) == new_clean.lower())
                .limit(1)
            )
            new_owner_id = new_owner.scalar_one_or_none()
            current_owner_id = logs[0].user_id
            if new_owner_id is not None and new_owner_id != current_owner_id:
                await interaction.followup.send(
                    embed=build_error_embed(
                        f"Tên mới **{new_clean}** đã thuộc về user khác (ID `{new_owner_id}`). "
                        "Không thể rename — sẽ gây xung đột username lock."
                    ),
                    ephemeral=True,
                )
                return

            # Snapshot user_ids bị ảnh hưởng để ghi audit
            affected_user_ids = sorted({l.user_id for l in logs})
            affected_count = len(logs)

            # Mass update
            for log in logs:
                log.username = new_clean

            session.add(AuditLog(
                guild_id=interaction.guild_id,
                user_id=interaction.user.id,
                username=str(interaction.user),
                action=AuditAction.LOG_RENAMED,
                detail={
                    "old_name": old_clean,
                    "new_name": new_clean,
                    "affected_logs": affected_count,
                    "affected_user_ids": [str(u) for u in affected_user_ids],
                    "reason": reason_clean,
                },
                created_at=utcnow(),
            ))
            await session.commit()

        await interaction.followup.send(
            embed=build_success_embed(
                f"Đã đổi tên **{affected_count}** log từ "
                f"`{old_clean}` → `{new_clean}`. "
                f"Áp dụng cho {len(affected_user_ids)} user_id."
            ),
            ephemeral=True,
        )

    @log_upload.error
    @log_forward.error
    @log_view.error
    @log_delete.error
    @log_rename.error
    async def on_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.CommandOnCooldown):
            await interaction.response.send_message(
                embed=build_error_embed(
                    f"Bạn dùng lệnh quá nhanh! Thử lại sau **{error.retry_after:.0f}s**."
                ),
                ephemeral=True,
            )
        else:
            logger.error(f"Lỗi command log: {error}", exc_info=True)
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        embed=build_error_embed("Đã xảy ra lỗi không mong muốn."), ephemeral=True
                    )
                else:
                    await interaction.followup.send(
                        embed=build_error_embed("Đã xảy ra lỗi không mong muốn."), ephemeral=True
                    )
            except discord.HTTPException:
                pass


async def _get_guild_config(session: AsyncSession, guild_id: int) -> GuildConfig | None:
    result = await session.execute(
        select(GuildConfig).where(GuildConfig.guild_id == guild_id)
    )
    return result.scalar_one_or_none()


async def setup(bot: commands.Bot):
    await bot.add_cog(LogDutyCog(bot))
    # Pre-warm EasyOCR model khi bot start để tránh lag ở lần upload đầu tiên
    import asyncio
    asyncio.create_task(warmup_ocr())
