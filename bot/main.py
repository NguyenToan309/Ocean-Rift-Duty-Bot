"""
bot/main.py — Entrypoint Discord bot
Khởi động: python -m bot.main
"""
import asyncio
import logging
import os
import sys
import platform

import aiohttp
import discord
from discord.ext import commands

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot.config import settings
from models.base import create_all_tables

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logging.getLogger("discord.http").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

COGS = [
    "bot.cogs.log_duty",
    "bot.cogs.ranking",
    "bot.cogs.stats",
    "bot.cogs.export",
    "bot.cogs.setup",
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
        # Tạo bảng DB nếu chưa có (chỉ dùng khi dev, production dùng alembic)
        if settings.DEBUG:
            await create_all_tables()
            logger.info("Đã tạo/kiểm tra tables (DEBUG mode)")

        # Load tất cả cogs
        for cog in COGS:
            try:
                await self.load_extension(cog)
                logger.info(f"Loaded cog: {cog}")
            except Exception as e:
                logger.error(f"Lỗi load cog {cog}: {e}", exc_info=True)

        # Sync slash commands toàn cầu (discord.py 2.x)
        synced = await self.tree.sync()
        logger.info(f"Synced {len(synced)} slash commands")

    async def on_ready(self):
        logger.info(f"Bot đã online: {self.user} (ID: {self.user.id})")
        logger.info(f"Đang phục vụ {len(self.guilds)} guild(s)")
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="chấm công | /log upload"
            )
        )

    async def on_guild_join(self, guild: discord.Guild):
        """Ghi log khi bot được thêm vào guild mới"""
        logger.info(f"Bot được thêm vào guild: {guild.name} (ID: {guild.id})")

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


async def main():
    bot = DutyBot()
    async with bot:
        await bot.start(settings.DISCORD_BOT_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
