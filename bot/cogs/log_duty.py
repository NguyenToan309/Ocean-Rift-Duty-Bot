"""
log_duty.py â€” Cog xá»­ lÃ½ /log upload, /log forward, /log view, /log delete
Luá»“ng upload: nháº­n áº£nh â†’ OCR â†’ parse â†’ validate â†’ confirm â†’ lÆ°u DB
Luá»“ng forward: nháº­n text â†’ parse â†’ validate â†’ confirm â†’ lÆ°u DB
Auto-scan: on_message tá»± Ä‘á»™ng parse LOG DUTY trong log_channel
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
    build_error_embed, build_success_embed, build_info_embed,
    build_log_accepted_embed, build_log_rejected_embed,
    build_log_invalid_embed, build_log_name_mismatch_embed,
    build_log_duplicate_embed,
    build_log_impersonation_embed, build_log_ambiguous_name_embed,
)
from bot.utils.time_utils import to_utc, utcnow

logger = logging.getLogger(__name__)

PAGE_SIZE = 10


class ConfirmLogView(discord.ui.View):
    """NÃºt XÃ¡c nháº­n / Huá»· khi upload log. Timeout 60 giÃ¢y."""

    def __init__(self, parsed_data: dict, submitter_id: int, guild_id: int):
        super().__init__(timeout=60)
        self.parsed_data = parsed_data
        self.submitter_id = submitter_id
        self.guild_id = guild_id
        self.confirmed = False
        self._message: discord.WebhookMessage | None = None  # set sau followup.send

    def set_message(self, msg: discord.WebhookMessage) -> None:
        """LÆ°u reference Ä‘áº¿n message Ä‘á»ƒ on_timeout cÃ³ thá»ƒ edit"""
        self._message = msg

    async def on_timeout(self) -> None:
        """Disable táº¥t cáº£ nÃºt vÃ  thÃ´ng bÃ¡o háº¿t giá» khi view timeout"""
        for child in self.children:
            child.disabled = True
        if self._message:
            try:
                await self._message.edit(
                    content="â° Háº¿t thá»i gian xÃ¡c nháº­n (60 giÃ¢y). HÃ£y cháº¡y láº¡i lá»‡nh náº¿u muá»‘n lÆ°u.",
                    view=self,
                )
            except discord.HTTPException:
                pass

    @discord.ui.button(label="âœ… XÃ¡c nháº­n lÆ°u", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Chá»‰ ngÆ°á»i upload má»›i Ä‘Æ°á»£c xÃ¡c nháº­n
        if interaction.user.id != self.submitter_id:
            await interaction.response.send_message(
                "Chá»‰ ngÆ°á»i upload má»›i Ä‘Æ°á»£c xÃ¡c nháº­n log nÃ y.", ephemeral=True
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

            except ValueError as e:
                await session.rollback()
                await interaction.followup.send(
                    embed=build_error_embed(str(e)), ephemeral=True
                )
                # Disable nÃºt sau khi lá»—i Ä‘á»ƒ khÃ´ng submit láº¡i
                for child in self.children:
                    child.disabled = True
                try:
                    await interaction.edit_original_response(view=self)
                except discord.HTTPException:
                    pass
                self.stop()
                return

            except IntegrityError as e:
                # DB-level uq_duty_log_entry vi pháº¡m â†’ race condition Layer 2
                # (2 user submit cÃ¹ng ca trá»±c Ä‘á»“ng thá»i). Hiá»ƒn thá»‹ message thÃ¢n thiá»‡n.
                await session.rollback()
                logger.info(f"Race condition duplicate caught at DB level: {e.orig}")
                await interaction.followup.send(
                    embed=build_error_embed(
                        "Ca trá»±c nÃ y vá»«a Ä‘Æ°á»£c lÆ°u (cÃ³ thá»ƒ báº¡n nháº¥n 2 láº§n hoáº·c submit trÃ¹ng).\n"
                        "Vui lÃ²ng kiá»ƒm tra láº¡i vá»›i `/log view`."
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
                logger.error(f"Lá»—i lÆ°u duty log: {e}", exc_info=True)
                await interaction.followup.send(
                    embed=build_error_embed("LÆ°u tháº¥t báº¡i do lá»—i há»‡ thá»‘ng. Thá»­ láº¡i sau."),
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
            f"ÄÃ£ lÆ°u log trá»±c cho **{self.parsed_data['username']}**!\n"
            f"â± {self.parsed_data['duration_minutes']} phÃºt"
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

        for child in self.children:
            child.disabled = True
        try:
            await interaction.edit_original_response(view=self)
        except discord.HTTPException:
            pass
        self.stop()

    @discord.ui.button(label="âŒ Huá»·", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.submitter_id:
            await interaction.response.send_message("KhÃ´ng pháº£i log cá»§a báº¡n.", ephemeral=True)
            return

        await interaction.response.send_message("ÄÃ£ huá»· lÆ°u log.", ephemeral=True)
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
    LÆ°u DutyLog vÃ o DB vá»›i 3 táº§ng báº£o vá»‡:

    Táº§ng 0 â€” Kiá»ƒm tra tÆ°Æ¡ng lai:
        Ca trá»±c khÃ´ng Ä‘Æ°á»£c báº¯t Ä‘áº§u > 30 phÃºt trong tÆ°Æ¡ng lai.
        Cho phÃ©p báº¥t ká»³ ngÃ y nÃ o trong quÃ¡ khá»©.

    Táº§ng 1 â€” source_message_id (auto-scan / Discord forward):
        Cháº·n cÃ¹ng message Discord Ä‘Æ°á»£c scan 2 láº§n.

    Táº§ng 2 â€” (guild_id, user_id, started_at, ended_at) exact duplicate:
        Cháº·n cÃ¹ng ca trá»±c Ä‘Æ°á»£c submit láº¡i dÆ°á»›i dáº¡ng text/áº£nh khÃ¡c nhau.
        DB constraint uq_duty_log_entry lÃ  backup phÃ²ng race condition.

    Táº§ng 3 â€” Overlap check:
        Cháº·n ca trá»±c má»›i chá»“ng láº¥p thá»i gian vá»›i ca trá»±c Ä‘Ã£ tá»“n táº¡i cá»§a cÃ¹ng user.
        VÃ­ dá»¥: Ä‘Ã£ cÃ³ 08:00-12:00, khÃ´ng thá»ƒ thÃªm 10:00-14:00.
        Cho phÃ©p ca liÃªn tiáº¿p (káº¿t thÃºc = báº¯t Ä‘áº§u ca tiáº¿p).
    """
    now = utcnow()

    # â”€â”€ Táº§ng -1: Username lock â€” chá»‘ng impersonation triá»‡t Ä‘á»ƒ â”€â”€
    # Má»—i `username` (sau normalize) trong 1 guild chá»‰ Ä‘Æ°á»£c thuá»™c vá» 1 user_id duy nháº¥t.
    # User Ä‘áº§u tiÃªn submit log vá»›i tÃªn X â†’ tÃªn X locked vÃ o user_id Ä‘Ã³ forever.
    # User khÃ¡c cá»‘ gáº¯ng dÃ¹ng tÃªn X â†’ REJECT.
    #
    # ÄÃ¢y lÃ  phÃ²ng tuyáº¿n cuá»‘i: ngay cáº£ khi attacker bypass identity check
    # (Ä‘á»•i nick thÃ nh tÃªn victim), DB sáº½ cháº·n vÃ¬ username Ä‘Ã£ cÃ³ owner khÃ¡c.
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
                f"[username-lock] User {user_id} cá»‘ gáº¯ng dÃ¹ng tÃªn '{username}' "
                f"Ä‘Ã£ thuá»™c vá» user {first_owner_id} (lÆ°u trÆ°á»›c Ä‘Ã³)"
            )
            raise ValueError(
                f"TÃªn **{username}** Ä‘Ã£ Ä‘Æ°á»£c dÃ¹ng bá»Ÿi tÃ i khoáº£n khÃ¡c trÆ°á»›c Ä‘Ã¢y. "
                "Báº¡n khÃ´ng thá»ƒ cháº¥m cÃ´ng vá»›i tÃªn nÃ y.\n\n"
                "Náº¿u Ä‘Ã¢y lÃ  tÃªn tháº­t cá»§a báº¡n (cÃ³ user khÃ¡c Ä‘Ã£ chiáº¿m trÆ°á»›c), "
                "**vui lÃ²ng liÃªn há»‡ ban lÃ£nh Ä‘áº¡o** Ä‘á»ƒ xá»­ lÃ½."
            )

    # â”€â”€ Táº§ng 0: KhÃ´ng cho phÃ©p ca trá»±c á»Ÿ tÆ°Æ¡ng lai â”€â”€
    if started_at > now + timedelta(minutes=30):
        raise ValueError(
            f"KhÃ´ng thá»ƒ log ca trá»±c chÆ°a báº¯t Ä‘áº§u.\n"
            f"Giá» báº¯t Ä‘áº§u trong log: **{started_at.strftime('%H:%M %d/%m/%Y')} UTC**\n"
            f"Thá»i gian hiá»‡n táº¡i: **{now.strftime('%H:%M %d/%m/%Y')} UTC**\n"
            "â†’ Chá»‰ Ä‘Æ°á»£c log ca trá»±c Ä‘Ã£ hoáº·c Ä‘ang diá»…n ra."
        )
    if ended_at > now + timedelta(minutes=5):
        raise ValueError(
            f"KhÃ´ng thá»ƒ log ca trá»±c chÆ°a káº¿t thÃºc.\n"
            f"Giá» káº¿t thÃºc trong log: **{ended_at.strftime('%H:%M %d/%m/%Y')} UTC**\n"
            "â†’ Vui lÃ²ng chá» ca trá»±c káº¿t thÃºc rá»“i má»›i ná»™p log."
        )

    # â”€â”€ Táº§ng 1: source_message_id unique (auto-scan) â”€â”€
    if source_message_id:
        existing = await session.execute(
            select(DutyLog).where(DutyLog.source_message_id == source_message_id)
        )
        if existing.scalar_one_or_none():
            raise ValueError("Log nÃ y Ä‘Ã£ Ä‘Æ°á»£c lÆ°u trÆ°á»›c Ä‘Ã³ (duplicate message)")

    # â”€â”€ Táº§ng 2: Exact duplicate (guild, user, start, end) â”€â”€
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
            f"Ca trá»±c **{username}** tá»« "
            f"`{started_at.strftime('%H:%M %d/%m/%Y')}` Ä‘áº¿n "
            f"`{ended_at.strftime('%H:%M %d/%m/%Y')}` Ä‘Ã£ Ä‘Æ°á»£c lÆ°u rá»“i."
        )

    # â”€â”€ Táº§ng 3: Overlap check â€” chá»“ng láº¥p thá»i gian â”€â”€
    # A chá»“ng B khi: A.start < B.end AND A.end > B.start
    # Cho phÃ©p ca liÃªn tiáº¿p (A.end == B.start)
    overlap = await session.execute(
        select(DutyLog)
        .where(DutyLog.guild_id == guild_id)
        .where(DutyLog.user_id == user_id)
        .where(DutyLog.started_at < ended_at)    # ca cÅ© báº¯t Ä‘áº§u trÆ°á»›c khi ca má»›i káº¿t thÃºc
        .where(DutyLog.ended_at > started_at)    # ca cÅ© káº¿t thÃºc sau khi ca má»›i báº¯t Ä‘áº§u
        .limit(1)
    )
    conflicting = overlap.scalar_one_or_none()
    if conflicting:
        raise ValueError(
            f"Ca trá»±c nÃ y **chá»“ng láº¥p** vá»›i ca trá»±c Ä‘Ã£ tá»“n táº¡i cá»§a **{username}**:\n"
            f"â€¢ ÄÃ£ cÃ³: `{conflicting.started_at.strftime('%H:%M %d/%m/%Y')}` â†’ "
            f"`{conflicting.ended_at.strftime('%H:%M %d/%m/%Y')}` "
            f"({conflicting.duration_minutes} phÃºt)\n"
            f"â€¢ Muá»‘n thÃªm: `{started_at.strftime('%H:%M %d/%m/%Y')}` â†’ "
            f"`{ended_at.strftime('%H:%M %d/%m/%Y')}` "
            f"({duration_minutes} phÃºt)\n"
            "â†’ Hai ca trá»±c khÃ´ng Ä‘Æ°á»£c trÃ¹ng thá»i gian."
        )

    # â”€â”€ Auto-link vá»›i MemberSchedule (náº¿u cÃ³ lá»‹ch khá»›p) â”€â”€
    schedule_id: int | None = None
    try:
        from bot.utils.schedule_engine import find_matching_schedule
        from models.guild import GuildConfig
        # Láº¥y timezone cá»§a guild Ä‘á»ƒ engine tÃ­nh weekday Ä‘Ãºng
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
        # Auto-link lÃ  nice-to-have, khÃ´ng nÃªn fail save log
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
        created_at=utcnow(),
    )
    session.add(log)
    return log


def _normalize_name(s: str | None) -> str:
    """Lowercase + strip non-alphanumeric (cháº¥p nháº­n tiáº¿ng Viá»‡t) Ä‘á»ƒ so sÃ¡nh tÃªn fuzzy"""
    if not s:
        return ""
    import re
    return re.sub(
        r"[^a-z0-9Ã Ã¡áº£Ã£áº¡Äƒáº±áº¯áº³áºµáº·Ã¢áº§áº¥áº©áº«áº­Ã¨Ã©áº»áº½áº¹Ãªá»áº¿á»ƒá»…á»‡Ã¬Ã­á»‰Ä©á»‹Ã²Ã³á»Ãµá»Ã´á»“á»‘á»•á»—á»™Æ¡á»á»›á»Ÿá»¡á»£Ã¹Ãºá»§Å©á»¥Æ°á»«á»©á»­á»¯á»±á»³Ã½á»·á»¹á»µÄ‘]",
        "", s.lower()
    )


def _strip_role_tag(name: str | None) -> str:
    """
    Bá» cÃ¡c prefix kiá»ƒu role/squad tag Ä‘á»ƒ láº¥y tÃªn thuáº§n.
    Há»— trá»£:
      "[VT] Tom Nguyá»…n"   â†’ "Tom Nguyá»…n"
      "(EMS) Tom Nguyá»…n"  â†’ "Tom Nguyá»…n"
      "ã€VTã€‘Tom Nguyá»…n"   â†’ "Tom Nguyá»…n"
      "VT | Tom Nguyá»…n"   â†’ "Tom Nguyá»…n"
      "VT - Tom Nguyá»…n"   â†’ "Tom Nguyá»…n" (náº¿u VT ngáº¯n)

    Tráº£ vá» tÃªn Ä‘Ã£ strip. Náº¿u khÃ´ng cÃ³ pattern â†’ tráº£ vá» tÃªn gá»‘c.
    """
    import re
    if not name:
        return ""
    s = name.strip()
    # [ABC] / (ABC) / ã€ABCã€‘ / ã€ŒABCã€ prefix (tag dÃ i tá»‘i Ä‘a 15 kÃ½ tá»±)
    s = re.sub(r"^[\[\(\{ã€ã€Œ]([^\]\)\}ã€‘ã€]{1,15})[\]\)\}ã€‘ã€]\s*", "", s)
    # "ABC | " hoáº·c "ABCâ€¢ " prefix (tag dÃ i tá»‘i Ä‘a 15 kÃ½ tá»± trÆ°á»›c |)
    s = re.sub(r"^[^|â€¢]{1,15}[|â€¢]\s*", "", s)
    return s.strip()


def _identity_candidates(author: "discord.abc.User | discord.Member") -> list[str]:
    """
    Tráº£ vá» táº¥t cáº£ tÃªn Ä‘á»‹nh danh kháº£ dÄ© cá»§a 1 user â€” bao gá»“m cáº£ raw vÃ  sau khi
    strip role tag prefix. DÃ¹ng Ä‘á»ƒ so sÃ¡nh STRICT exact match.
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
    TÃ¬m táº¥t cáº£ member trong guild khá»›p vá»›i parsed_name (qua _username_matches_author).
    DÃ¹ng Ä‘á»ƒ chá»‘ng IMPERSONATION: user khÃ´ng thá»ƒ Ä‘á»•i nick thÃ nh tÃªn ngÆ°á»i khÃ¡c Ä‘á»ƒ cháº¥m cÃ´ng há»™.

    Returns:
        ("ok",        [member])    â€” chá»‰ DUY NHáº¤T 1 ngÆ°á»i khá»›p (an toÃ n)
        ("ambiguous", [members])   â€” nhiá»u ngÆ°á»i khá»›p (cáº§n Ä‘áº·t nick rÃµ rÃ ng hÆ¡n)
        ("none",      [])          â€” khÃ´ng ai trong server cÃ³ tÃªn nÃ y
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
    STRICT: parsed_name pháº£i KHá»šP CHÃNH XÃC (sau normalize) vá»›i má»™t trong cÃ¡c tÃªn
    Ä‘á»‹nh danh cá»§a Discord user â€” bao gá»“m cáº£ raw vÃ  sau khi strip role tag prefix.

    Strip 2 chiá»u: cáº£ parsed_name VÃ€ candidate Ä‘á»u thá»­ strip tag trÆ°á»›c khi compare.
    Tag máº«u há»— trá»£ (â‰¤15 kÃ½ tá»± trÆ°á»›c dáº¥u | hoáº·c trong [...] / (...) / ã€...ã€‘):
      - "TTS | TÃªn", "BS | TÃªn", "PK | TÃªn", "TK | TÃªn"
      - "QLBS | TÃªn", "TKBS | TÃªn", "VP | TÃªn", "VT | TÃªn"
      - "[EMS] TÃªn", "(VT) TÃªn", "ã€EMSã€‘TÃªn"

    KhÃ´ng match substring lá»ng (Ä‘Ã£ bá» á»Ÿ audit Ä‘á»ƒ chá»‘ng impersonation).
    """
    if not parsed_name:
        return False

    # Táº¡o set cÃ¡c biáº¿n thá»ƒ cá»§a parsed name: raw + stripped
    parsed_variants: set[str] = set()
    pn_raw = _normalize_name(parsed_name)
    if pn_raw:
        parsed_variants.add(pn_raw)
    pn_stripped = _normalize_name(_strip_role_tag(parsed_name))
    if pn_stripped:
        parsed_variants.add(pn_stripped)
    if not parsed_variants:
        return False

    # So sÃ¡nh vá»›i má»i biáº¿n thá»ƒ cá»§a candidate
    for candidate in _identity_candidates(author):
        cand_n = _normalize_name(candidate)
        if cand_n and cand_n in parsed_variants:
            return True
    return False


class LogDutyCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    log_group = app_commands.Group(name="log", description="Quáº£n lÃ½ log cháº¥m cÃ´ng")

    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # Auto-scan: tá»± Ä‘á»™ng parse má»i tin nháº¯n LOG DUTY trong channel Ä‘Ã£ setup
    # User chá»‰ cáº§n gá»­i/forward tin nháº¯n â†’ bot tá»± lÆ°u, khÃ´ng cáº§n slash command
    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # Bá» qua Má»ŒI tin nháº¯n cá»§a bot (ká»ƒ cáº£ bot khÃ¡c hay webhook)
        if message.author.bot:
            return
        if not message.guild:
            return

        # Láº¥y config guild â€” pháº£i Ä‘Ã£ setup
        async with AsyncSessionLocal() as session:
            config = await _get_guild_config(session, message.guild.id)

        if not config or not config.is_active:
            return

        # Chá»‰ scan trong channel Ä‘Ã£ set; náº¿u chÆ°a set log_channel_id thÃ¬ Bá»Ž QUA
        if not config.log_channel_id:
            return
        if message.channel.id != config.log_channel_id:
            return

        # TrÃ­ch xuáº¥t táº¥t cáº£ text candidates: content gá»‘c + forward snapshots + embeds
        candidates = self._extract_message_text(message)
        if not candidates:
            return

        logger.debug(
            f"[auto-scan] QuÃ©t msg {message.id} tá»« {message.author}: "
            f"{len(candidates)} candidate(s)"
        )

        # Thá»­ parse tá»«ng Ä‘oáº¡n; láº¥y match Ä‘áº§u tiÃªn há»£p lá»‡
        parsed = None
        for text in candidates:
            result = parse_duty_text(text)
            if result is None:
                continue
            errors = result.validate()
            if errors:
                logger.info(f"[auto-scan] Parse Ä‘Æ°á»£c nhÆ°ng validation lá»—i: {errors}")
                try:
                    await message.add_reaction("âš ï¸")
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

        # â”€â”€ Verify STRICT: tÃªn trong LOG DUTY pháº£i DUY NHáº¤T thuá»™c vá» ngÆ°á»i gá»­i â”€â”€
        # Iterate toÃ n bá»™ guild members â†’ tÃ¬m ai khá»›p vá»›i parsed.username.
        # Chá»‘ng IMPERSONATION: user khÃ´ng thá»ƒ Ä‘á»•i nick thÃ nh tÃªn ngÆ°á»i khÃ¡c Ä‘á»ƒ cháº¥m cÃ´ng há»™.
        status, matches = _resolve_name_owner(message.guild, parsed.username)
        if status == "none":
            logger.info(
                f"[auto-scan] TÃªn khÃ´ng thuá»™c ai: parsed='{parsed.username}' "
                f"author={message.author} (id={message.author.id})"
            )
            try:
                await message.add_reaction("ðŸš«")
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
                await message.add_reaction("âš ï¸")
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
        # status == "ok": cÃ³ duy nháº¥t 1 ngÆ°á»i khá»›p
        if matches[0].id != message.author.id:
            logger.warning(
                f"[auto-scan] IMPERSONATION: author={message.author.id} "
                f"({message.author.display_name}) cá»‘ gáº¯ng cháº¥m cÃ´ng cho "
                f"{matches[0].id} ({matches[0].display_name})"
            )
            try:
                await message.add_reaction("ðŸš«")
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

        # LÆ°u DB
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
                    f"[auto-scan] ÄÃ£ lÆ°u log: guild={message.guild.id} "
                    f"user={parsed.username} duration={parsed.duration_minutes}p"
                )
                # âœ… Embed Ä‘áº¹p xÃ¡c nháº­n Ä‘Ã£ lÆ°u â€” kÃ¨m thÃ´ng tin ca trá»±c Ä‘á»ƒ member kiá»ƒm tra
                try:
                    await message.add_reaction("âœ…")
                    config_tz = config.timezone if config else None
                    await message.reply(
                        embed=build_log_accepted_embed(parsed, message.author, config_tz),
                        mention_author=False,
                    )
                except discord.HTTPException:
                    pass

            except ValueError as e:
                err_str = str(e)
                # Duplicate â†’ react ðŸ” + embed nháº¹
                if "Ä‘Ã£ Ä‘Æ°á»£c lÆ°u" in err_str or "duplicate" in err_str.lower():
                    logger.debug(f"[auto-scan] Duplicate skip: {e}")
                    try:
                        await message.add_reaction("ðŸ”")
                        await message.reply(
                            embed=build_log_duplicate_embed(message.author),
                            mention_author=False,
                            delete_after=30,
                        )
                    except discord.HTTPException:
                        pass
                else:
                    # Overlap, tÆ°Æ¡ng lai, etc. â†’ reject embed Ä‘áº§y Ä‘á»§
                    logger.info(f"[auto-scan] Validation reject: {e}")
                    try:
                        await message.add_reaction("ðŸš«")
                        await message.reply(
                            embed=build_log_rejected_embed(parsed, err_str, message.author),
                            mention_author=False,
                            delete_after=60,
                        )
                    except discord.HTTPException:
                        pass

            except IntegrityError as e:
                # Race condition Layer 2 (DB UniqueConstraint) â€” coi nhÆ° duplicate
                await session.rollback()
                logger.info(f"[auto-scan] DB-level duplicate (race): {e.orig}")
                try:
                    await message.add_reaction("ðŸ”")
                    await message.reply(
                        embed=build_log_duplicate_embed(message.author),
                        mention_author=False,
                        delete_after=30,
                    )
                except discord.HTTPException:
                    pass

            except Exception as e:
                await session.rollback()
                logger.error(f"[auto-scan] Lá»—i lÆ°u log: {e}", exc_info=True)
                try:
                    await message.add_reaction("âŒ")
                    await message.reply(
                        embed=build_error_embed(
                            "ÄÃ£ xáº£y ra lá»—i há»‡ thá»‘ng khi lÆ°u log. "
                            "Vui lÃ²ng thá»­ láº¡i sau Ã­t phÃºt.\n\n"
                            "_Náº¿u cáº§n há»— trá»£ vui lÃ²ng liÃªn há»‡ ban lÃ£nh Ä‘áº¡o._",
                            title="âŒ Lá»—i há»‡ thá»‘ng",
                        ),
                        mention_author=False,
                        delete_after=30,
                    )
                except discord.HTTPException:
                    pass

    @staticmethod
    def _extract_message_text(message: discord.Message) -> list[str]:
        """
        Tráº£ vá» list cÃ¡c Ä‘oáº¡n text cÃ³ thá»ƒ chá»©a LOG DUTY:
        - Ná»™i dung trá»±c tiáº¿p cá»§a message
        - Forward snapshots (Discord forward feature, discord.py 2.4+)
        - MÃ´ táº£ + fields cá»§a cÃ¡c embed
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
        """GhÃ©p táº¥t cáº£ pháº§n text cá»§a embed thÃ nh 1 chuá»—i"""
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

    @log_group.command(name="upload", description="Upload áº£nh LOG DUTY cá»§a báº¡n â†’ OCR tá»± Ä‘á»™ng lÆ°u")
    @app_commands.describe(
        anh="áº¢nh chá»¥p mÃ n hÃ¬nh LOG DUTY (JPG/PNG/WEBP, tá»‘i Ä‘a 5MB)",
    )
    @app_commands.checks.cooldown(rate=5, per=60.0)
    async def log_upload(
        self,
        interaction: discord.Interaction,
        anh: discord.Attachment,
    ):
        """
        STRICT MODE: Má»—i user chá»‰ Ä‘Æ°á»£c upload log cá»§a CHÃNH MÃŒNH.
        Mod/Admin cÅ©ng KHÃ”NG Ä‘Æ°á»£c upload há»™ â€” Ä‘áº£m báº£o tÃ­nh chÃ­nh xÃ¡c vÃ  truy váº¿t.
        TÃªn trong LOG DUTY pháº£i khá»›p display_name/name/global_name/nick cá»§a ngÆ°á»i gá»­i.
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
                        f"Chá»‰ Ä‘Æ°á»£c dÃ¹ng lá»‡nh nÃ y trong <#{config.log_channel_id}>"
                    ),
                    ephemeral=True,
                )
                return

        # Validate áº£nh
        mime = anh.content_type or "image/unknown"
        if mime not in {"image/jpeg", "image/png", "image/webp"}:
            await interaction.followup.send(
                embed=build_error_embed("Chá»‰ cháº¥p nháº­n áº£nh JPG, PNG hoáº·c WEBP."),
                ephemeral=True,
            )
            return

        if anh.size > 5 * 1024 * 1024:
            await interaction.followup.send(
                embed=build_error_embed("áº¢nh quÃ¡ lá»›n. Tá»‘i Ä‘a 5MB."),
                ephemeral=True,
            )
            return

        image_bytes = await anh.read()

        # OCR â€” cháº¡y trong thread pool, khÃ´ng block event loop
        parsed = await extract_duty_from_image(image_bytes, mime)
        if parsed is None:
            await interaction.followup.send(
                embed=build_error_embed(
                    "KhÃ´ng tÃ¬m tháº¥y Ä‘á»‹nh dáº¡ng LOG DUTY trong áº£nh.\n"
                    "HÃ£y Ä‘áº£m báº£o áº£nh chá»©a Ä‘áº§y Ä‘á»§: **TÃªn**, **Thá»i gian lÃ m viá»‡c**, "
                    "**Thá»i gian báº¯t Ä‘áº§u**, **Thá»i gian káº¿t thÃºc**.\n"
                    "Náº¿u áº£nh má», hÃ£y thá»­ chá»¥p láº¡i rÃµ hÆ¡n hoáº·c dÃ¹ng `/log forward` Ä‘á»ƒ paste text."
                ),
                ephemeral=True,
            )
            return

        # Validate logic
        errors = parsed.validate()
        if errors:
            await interaction.followup.send(
                embed=build_error_embed("Dá»¯ liá»‡u khÃ´ng há»£p lá»‡:\nâ€¢ " + "\nâ€¢ ".join(errors)),
                ephemeral=True,
            )
            return

        # â”€â”€ STRICT: tÃªn DUY NHáº¤T thuá»™c vá» ngÆ°á»i gá»­i (chá»‘ng impersonation qua nick) â”€â”€
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
                f"({interaction.user.display_name}) cá»‘ gáº¯ng cháº¥m cÃ´ng cho "
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
        }

        async with AsyncSessionLocal() as session:
            config = await _get_guild_config(session, interaction.guild_id)
            tz = config.timezone if config else None

        embed = build_log_confirm_embed(parsed_data, tz, parsed.is_loose_match)
        view = ConfirmLogView(parsed_data, interaction.user.id, interaction.guild_id)
        msg = await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        view.set_message(msg)

    @log_group.command(name="forward", description="Paste text LOG DUTY cá»§a báº¡n Ä‘á»ƒ lÆ°u thá»§ cÃ´ng")
    @app_commands.describe(text="Ná»™i dung LOG DUTY (copy paste tá»« bot cháº¥m cÃ´ng)")
    @app_commands.checks.cooldown(rate=5, per=60.0)
    async def log_forward(
        self,
        interaction: discord.Interaction,
        text: str,
    ):
        """
        STRICT MODE: Má»—i user chá»‰ Ä‘Æ°á»£c forward log cá»§a CHÃNH MÃŒNH.
        Mod/Admin cÅ©ng KHÃ”NG Ä‘Æ°á»£c forward há»™ â€” Ä‘áº£m báº£o tÃ­nh chÃ­nh xÃ¡c vÃ  truy váº¿t.
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
                    "KhÃ´ng nháº­n diá»‡n Ä‘Æ°á»£c Ä‘á»‹nh dáº¡ng LOG DUTY.\n"
                    "Vui lÃ²ng copy Ä‘Ãºng Ä‘á»‹nh dáº¡ng:\n"
                    "```\nLOG DUTY\nTÃªn: ...\nThá»i gian lÃ m viá»‡c: X phÃºt\n"
                    "Thá»i gian báº¯t Ä‘áº§u: DD/MM/YYYY HH:MM:SS\n"
                    "Thá»i gian káº¿t thÃºc: DD/MM/YYYY HH:MM:SS\n```"
                ),
                ephemeral=True,
            )
            return

        errors = parsed.validate()
        if errors:
            await interaction.followup.send(
                embed=build_error_embed("Dá»¯ liá»‡u khÃ´ng há»£p lá»‡:\nâ€¢ " + "\nâ€¢ ".join(errors)),
                ephemeral=True,
            )
            return

        # â”€â”€ STRICT: tÃªn DUY NHáº¤T thuá»™c vá» ngÆ°á»i gá»­i (chá»‘ng impersonation qua nick) â”€â”€
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
                f"({interaction.user.display_name}) cá»‘ gáº¯ng cháº¥m cÃ´ng cho "
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
        }

        async with AsyncSessionLocal() as session:
            config = await _get_guild_config(session, interaction.guild_id)
            tz = config.timezone if config else None

        embed = build_log_confirm_embed(parsed_data, tz, parsed.is_loose_match)
        view = ConfirmLogView(parsed_data, interaction.user.id, interaction.guild_id)
        msg = await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        view.set_message(msg)

    @log_group.command(name="view", description="Xem lá»‹ch sá»­ cháº¥m cÃ´ng")
    @app_commands.describe(
        tat_ca="Xem Táº¤T Cáº¢ thÃ nh viÃªn dáº¡ng báº£ng (cáº§n MOD+)",
        thanh_vien="Xem log cá»§a thÃ nh viÃªn cá»¥ thá»ƒ (cáº§n MOD+). Bá» trá»‘ng = xem cá»§a mÃ¬nh",
        ten="Filter theo username trong log. Cáº§n MOD+",
        trang="Sá»‘ trang (máº·c Ä‘á»‹nh: 1)"
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
            name="ðŸ—‘ï¸ XÃ³a log",
            value="DÃ¹ng `/log delete id:<sá»‘>` Ä‘á»ƒ xÃ³a. **CHá»ˆ Admin** má»›i cÃ³ quyá»n xÃ³a log.",
            inline=False,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @log_group.command(
        name="scan",
        description="QuÃ©t lá»‹ch sá»­ kÃªnh cháº¥m cÃ´ng Ä‘á»ƒ báº¯t LOG DUTY bá»‹ bá» sÃ³t (Mod+)",
    )
    @app_commands.describe(
        limit="Sá»‘ tin nháº¯n quÃ©t gáº§n nháº¥t (máº·c Ä‘á»‹nh 200, tá»‘i Ä‘a 1000)",
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
                    "Server chÆ°a setup channel cháº¥m cÃ´ng. DÃ¹ng `/setup channel` trÆ°á»›c."
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
                "channel_not_found": "KhÃ´ng tÃ¬m tháº¥y channel cháº¥m cÃ´ng.",
                "no_permission_read_history": "Bot khÃ´ng cÃ³ quyá»n **Read Message History** trong channel cháº¥m cÃ´ng.",
            }
            msg = err_map.get(stats["error"], f"Lá»—i: {stats['error']}")
            await interaction.followup.send(embed=build_error_embed(msg), ephemeral=True)
            return

        channel_mention = f"<#{config.log_channel_id}>"
        embed = discord.Embed(
            title="ðŸ”  QuÃ©t backfill hoÃ n táº¥t",
            description=(
                f"ÄÃ£ quÃ©t **{stats['scanned']}** tin nháº¯n gáº§n nháº¥t trong {channel_mention}.\n\n"
                f"```diff\n"
                f"+ {stats['saved']} log Má»šI Ä‘Ã£ lÆ°u\n"
                f"  {stats['dup']} Ä‘Ã£ cÃ³ trong DB (skip)\n"
                f"  {stats['invalid']} parse Ä‘Æ°á»£c nhÆ°ng validate lá»—i\n"
                f"  {stats['no_match']} tÃªn khÃ´ng khá»›p author (skip)\n"
                f"```"
            ),
            color=0x10B981 if stats['saved'] > 0 else 0x64748B,
        )
        embed.set_footer(text="Job idempotent â€” cháº¡y láº¡i nhiá»u láº§n khÃ´ng sinh duplicate")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @log_group.command(name="delete", description="XÃ³a 1 ca trá»±c theo ID (CHá»ˆ Admin)")
    @app_commands.describe(id="ID cá»§a ca trá»±c (xem qua /log view)")
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
                    embed=build_error_embed(f"KhÃ´ng tÃ¬m tháº¥y log vá»›i ID `{id}` trong server nÃ y."),
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
                f"ÄÃ£ xÃ³a log **#{id}** cá»§a **{snapshot['for_username']}** "
                f"({snapshot['duration_minutes']} phÃºt)."
            ),
            ephemeral=True,
        )

    @log_upload.error
    @log_forward.error
    @log_view.error
    @log_delete.error
    @log_scan.error
    async def on_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.CommandOnCooldown):
            await interaction.response.send_message(
                embed=build_error_embed(
                    f"Báº¡n dÃ¹ng lá»‡nh quÃ¡ nhanh! Thá»­ láº¡i sau **{error.retry_after:.0f}s**."
                ),
                ephemeral=True,
            )
        else:
            logger.error(f"Lá»—i command log: {error}", exc_info=True)
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        embed=build_error_embed("ÄÃ£ xáº£y ra lá»—i khÃ´ng mong muá»‘n."), ephemeral=True
                    )
                else:
                    await interaction.followup.send(
                        embed=build_error_embed("ÄÃ£ xáº£y ra lá»—i khÃ´ng mong muá»‘n."), ephemeral=True
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
    # Pre-warm EasyOCR model khi bot start Ä‘á»ƒ trÃ¡nh lag á»Ÿ láº§n upload Ä‘áº§u tiÃªn
    import asyncio
    asyncio.create_task(warmup_ocr())
