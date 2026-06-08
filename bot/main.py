"""
bot/main.py — Entrypoint Discord bot Homie Medic
Khởi động: python -m bot.main
"""
import asyncio
import logging
from logging.handlers import RotatingFileHandler
import os
import sys
import platform

import aiohttp
import discord
from discord.ext import commands

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot.config import settings
from models.base import create_all_tables

# ─── Logging setup ───────────────────────────────────────────────────────────
# Local long-run: INFO mặc định (DEBUG quá verbose). File rotate 10MB × 5
# để logs/ không phình vô tận. discord.http giảm xuống WARNING vì rate-limit
# debug rất noisy.
_log_format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_log_level = logging.DEBUG if settings.DEBUG else logging.INFO

_handlers: list[logging.Handler] = [logging.StreamHandler()]
try:
    os.makedirs("logs", exist_ok=True)
    file_handler = RotatingFileHandler(
        "logs/bot.log",
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,              # giữ tối đa 5 file backup (~50 MB)
        encoding="utf-8",
    )
    file_handler.setFormatter(logging.Formatter(_log_format))
    _handlers.append(file_handler)
except OSError:
    # Không tạo được logs/ (vd permission) → chỉ log ra stderr
    pass

logging.basicConfig(level=_log_level, format=_log_format, handlers=_handlers)
logging.getLogger("discord.http").setLevel(logging.WARNING)
logging.getLogger("discord.gateway").setLevel(logging.WARNING)
# SQLAlchemy noise — chỉ hiện nếu DB_DEBUG=True (settings.DB_DEBUG)
if not settings.DB_DEBUG:
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.pool").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

COGS = [
    "bot.cogs.log_duty",
    "bot.cogs.ranking",
    "bot.cogs.stats",
    "bot.cogs.export",
    "bot.cogs.setup",
    "bot.cogs.schedule",
    "bot.cogs.leave",
    "bot.cogs.discipline",
    "bot.cogs.control_panel",
    "bot.cogs.staff",
]


class DutyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True            # Cần để tìm member theo tên
        intents.message_content = True    # Cần để auto-scan LOG DUTY trong channel chấm công
        # ⚠️ message_content là PRIVILEGED INTENT — phải enable trong Discord Developer Portal:
        # https://discord.com/developers/applications → Bot → Privileged Gateway Intents → MESSAGE CONTENT INTENT

        # Windows: aiodns không hoạt động ổn với một số cấu hình mạng
        # ThreadedResolver dùng DNS của hệ điều hành thay vì aiodns
        connector = None
        if platform.system() == "Windows":
            connector = aiohttp.TCPConnector(resolver=aiohttp.ThreadedResolver())

        super().__init__(
            command_prefix="!",    # Prefix fallback, không dùng prefix commands
            intents=intents,
            help_command=None,
            connector=connector,
        )

    async def setup_hook(self):
        """Chạy trước khi bot kết nối — load cogs và sync slash commands"""
        # Tạo bảng DB chỉ khi env CREATE_TABLES_ON_START=true (mặc định production dùng alembic)
        # Tránh xung đột schema giữa create_all() và alembic migrations.
        if os.getenv("CREATE_TABLES_ON_START", "").lower() == "true":
            await create_all_tables()
            logger.warning(
                "Đã chạy create_all_tables() — flag CREATE_TABLES_ON_START=true. "
                "Production nên dùng `alembic upgrade head` thay vì cờ này."
            )

        # Load tất cả cogs
        for cog in COGS:
            try:
                await self.load_extension(cog)
                logger.info(f"Loaded cog: {cog}")
            except Exception as e:
                logger.error(f"Lỗi load cog {cog}: {e}", exc_info=True)

        # Sync slash commands.
        # Discord global sync mất tới 1h propagate → chậm khi dev.
        # Nếu env DISCORD_DEV_GUILD_ID hoặc DISCORD_TEST_GUILD_ID set →
        # copy global commands sang guild đó + sync ngay (instant, hiện liền).
        # Production: bỏ env này, dùng global sync.
        dev_guild_id = os.getenv("DISCORD_DEV_GUILD_ID") or os.getenv("DISCORD_TEST_GUILD_ID")
        if dev_guild_id and dev_guild_id.isdigit():
            guild_obj = discord.Object(id=int(dev_guild_id))
            self.tree.copy_global_to(guild=guild_obj)
            try:
                synced = await self.tree.sync(guild=guild_obj)
                logger.info(
                    f"[dev-mode] Synced {len(synced)} slash commands "
                    f"to guild {dev_guild_id} (instant)."
                )
            except Exception as e:
                logger.error(f"Sync per-guild failed: {e}", exc_info=True)
        else:
            try:
                synced = await self.tree.sync()
                logger.info(
                    f"Synced {len(synced)} slash commands globally. "
                    "Lưu ý: global sync có thể mất tới 1 giờ để Discord propagate."
                )
            except Exception as e:
                logger.error(f"Global sync failed: {e}", exc_info=True)

        # Khởi động background tasks (nhắc trực, EOD check, onboarding scan)
        from bot.tasks.schedule_tasks import start_background_tasks
        start_background_tasks(self)

    async def on_ready(self):
        logger.info(f"Bot đã online: {self.user} (ID: {self.user.id})")
        logger.info(f"Đang phục vụ {len(self.guilds)} guild(s)")
        # Set presence ngay từ DB (fallback default nếu chưa migrate hoặc DB lỗi)
        await self._refresh_presence_from_db()
        # Khởi động loop poll mỗi 60s để áp dụng thay đổi từ web admin
        if not getattr(self, "_presence_task_started", False):
            self._presence_task_started = True
            self.loop.create_task(self._presence_poll_loop())

    async def _refresh_presence_from_db(self) -> None:
        """Đọc system_settings.bot_activity_text từ DB → change_presence.

        Fallback DEFAULTS nếu DB lỗi (vd: chưa migrate) — không để bot crash
        vì lý do branding.
        """
        from sqlalchemy import select
        from models.base import AsyncSessionLocal
        from models.system_setting import SystemSetting, DEFAULTS as SYS_DEFAULTS
        text = SYS_DEFAULTS["bot_activity_text"]
        try:
            async with AsyncSessionLocal() as session:
                row = await session.execute(
                    select(SystemSetting).where(SystemSetting.key == "bot_activity_text")
                )
                s = row.scalar_one_or_none()
                if s and s.value:
                    text = s.value
        except Exception as e:
            logger.warning(f"Không đọc được bot_activity_text từ DB ({e!r}), dùng default.")
        # Lưu cache để loop biết khi nào cần update
        if getattr(self, "_current_activity_text", None) == text:
            return
        self._current_activity_text = text
        await self.change_presence(
            activity=discord.Activity(type=discord.ActivityType.watching, name=text)
        )

    async def _presence_poll_loop(self) -> None:
        """Poll system_settings mỗi 5 phút, áp dụng khi bot_activity_text đổi.

        Loop chạy vĩnh viễn đến khi bot disconnect. Try/except mỗi iteration
        để 1 lỗi mạng không kill loop. Interval 300s (thay vì 60s) — text
        này hiếm khi đổi, không cần poll high-freq.
        """
        import asyncio
        while not self.is_closed():
            await asyncio.sleep(300)
            try:
                await self._refresh_presence_from_db()
            except Exception as e:
                logger.debug(f"Presence poll iteration lỗi: {e!r}")

    async def on_guild_join(self, guild: discord.Guild):
        """Ghi log khi bot được thêm vào guild mới"""
        logger.info(f"Bot được thêm vào guild: {guild.name} (ID: {guild.id})")

    async def on_member_update(self, before: discord.Member, after: discord.Member):
        """Real-time onboarding: khi member nhận role Medic mới → DM ngay"""
        try:
            from bot.tasks.schedule_tasks import on_member_role_update
            await on_member_role_update(before, after, self)
        except Exception as e:
            logger.error(f"on_member_update handler lỗi: {e}", exc_info=True)

    async def on_app_command_error(
        self, interaction: discord.Interaction, error: Exception
    ):
        """Global error handler cho tất cả slash commands"""
        from bot.utils.embed_builder import build_error_embed

        logger.error(
            f"Lỗi command /{interaction.command.name if interaction.command else 'unknown'}: {error}",
            exc_info=True
        )

        msg = "Đã xảy ra lỗi không mong muốn. Vui lòng thử lại sau."
        embed = build_error_embed(msg)

        try:
            if interaction.response.is_done():
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception:
            pass  # Bỏ qua nếu không thể gửi message lỗi


def _tune_gc_for_long_run() -> None:
    """Tune Python GC cho long-running bot.

    Default Python GC threshold (700, 10, 10) trigger collect rất thường xuyên
    với app có nhiều object ngắn hạn (mọi message → parse → dict → discard).
    Bot async + nhiều task → GC pause gây lag spike. Tăng threshold giảm tần
    suất collect, đánh đổi RAM cao hơn chút (~10-20MB).

    Tham khảo: Instagram, Bloomberg dùng threshold lớn hơn cho long-running
    Python services.
    """
    import gc
    gc.set_threshold(50000, 50, 50)


async def main():
    _tune_gc_for_long_run()
    bot = DutyBot()
    async with bot:
        await bot.start(settings.DISCORD_BOT_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
