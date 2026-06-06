"""
sync_commands.py — Manual force-sync slash commands.

Chạy:
    python scripts/sync_commands.py                    # sync vào DISCORD_DEV_GUILD_ID
    python scripts/sync_commands.py 123456789012345678 # sync vào guild ID cụ thể
    python scripts/sync_commands.py --global           # sync global (chậm, tới 1h)
    python scripts/sync_commands.py --clear            # XÓA hết commands trong dev guild

KHÔNG cần bot đang chạy — script tự login + sync rồi thoát.
"""
import asyncio
import logging
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Reduce noise
logging.getLogger("discord.client").setLevel(logging.WARNING)
logging.getLogger("discord.gateway").setLevel(logging.WARNING)
logging.getLogger("discord.http").setLevel(logging.WARNING)


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


class SyncBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents, help_command=None)

    async def setup_hook(self):
        # Load tất cả cogs để register commands vào tree
        for cog in COGS:
            try:
                await self.load_extension(cog)
                print(f"  [OK] Loaded {cog}")
            except Exception as e:
                print(f"  [ERR] {cog}: {type(e).__name__}: {e}")


async def main():
    token = os.getenv("DISCORD_BOT_TOKEN")
    if not token:
        print("[ERR] DISCORD_BOT_TOKEN khong co trong .env")
        return 1

    # Parse args
    args = sys.argv[1:]
    mode = "guild"
    target_guild_id = None
    clear = False

    if "--global" in args:
        mode = "global"
    elif "--clear" in args:
        clear = True
    elif args and args[0].isdigit():
        target_guild_id = int(args[0])
    else:
        dev = os.getenv("DISCORD_DEV_GUILD_ID")
        if dev and dev.isdigit():
            target_guild_id = int(dev)

    if mode == "guild" and not clear and not target_guild_id:
        print("[ERR] Khong co guild ID. Set DISCORD_DEV_GUILD_ID trong .env hoac truyen ID.")
        return 1

    print(f"\n{'='*60}")
    print(f"  SYNC SLASH COMMANDS")
    if clear:
        print(f"  Mode: CLEAR (xoa het commands trong guild {target_guild_id})")
    elif mode == "global":
        print(f"  Mode: GLOBAL (cham, toi 1 gio de Discord propagate)")
    else:
        print(f"  Mode: GUILD {target_guild_id} (instant)")
    print(f"{'='*60}\n")

    bot = SyncBot()

    print("[*] Loading cogs + login...")
    # bot.login() tu dong goi setup_hook -> load cogs
    try:
        await bot.login(token)
        print(f"[OK] Logged in as bot ID {bot.application_id}")
    except discord.LoginFailure as e:
        print(f"[ERR] Login that bai: {e}")
        return 1

    # Đếm commands trong tree
    all_cmds = bot.tree.get_commands()
    print(f"\n[*] Tree co {len(all_cmds)} top-level commands:")
    for c in sorted(all_cmds, key=lambda c: c.name):
        if hasattr(c, "commands"):  # Group
            subs = list(c.commands)
            print(f"  /{c.name}  (group, {len(subs)} subcommands)")
            for sub in sorted(subs, key=lambda s: s.name):
                print(f"      /{c.name} {sub.name}")
        else:
            print(f"  /{c.name}")

    # Sync
    print()
    try:
        if clear:
            if not target_guild_id:
                print("[ERR] Clear can co guild ID")
                return 1
            guild_obj = discord.Object(id=target_guild_id)
            bot.tree.clear_commands(guild=guild_obj)
            await bot.tree.sync(guild=guild_obj)
            print(f"[OK] Da CLEAR het slash commands trong guild {target_guild_id}")
        elif mode == "global":
            print("[*] Syncing GLOBAL...")
            synced = await bot.tree.sync()
            print(f"[OK] Synced {len(synced)} commands GLOBAL")
            print("    Luu y: Co the mat toi 1 gio de Discord propagate.")
        else:
            guild_obj = discord.Object(id=target_guild_id)
            print(f"[*] Copying global commands to guild {target_guild_id}...")
            bot.tree.copy_global_to(guild=guild_obj)
            print(f"[*] Syncing to guild {target_guild_id}... (DUNG bam Ctrl+C, doi ~5s)")
            synced = await bot.tree.sync(guild=guild_obj)
            print(f"\n[OK] Synced {len(synced)} commands to guild {target_guild_id} (instant)")
            print("    Commands sau khi sync:")
            for cmd in sorted(synced, key=lambda c: c.name):
                opt_types = []
                if hasattr(cmd, "options") and cmd.options:
                    opt_types = [o.name for o in cmd.options]
                if opt_types:
                    print(f"      /{cmd.name}  ({len(opt_types)} options/subs)")
                else:
                    print(f"      /{cmd.name}")

        print(f"\n{'='*60}")
        print("  HOAN TAT. Bay gio:")
        print("  1. Mo Discord")
        print("  2. Bam Ctrl+R de refresh client")
        print("  3. Go /nh -> phai thay /nhansu")
        print(f"{'='*60}")
    except Exception as e:
        print(f"\n[ERR] Sync that bai: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        await bot.close()

    return 0


if __name__ == "__main__":
    try:
        rc = asyncio.run(main())
        sys.exit(rc or 0)
    except KeyboardInterrupt:
        print("\n[!] Cancelled by user")
        sys.exit(130)
