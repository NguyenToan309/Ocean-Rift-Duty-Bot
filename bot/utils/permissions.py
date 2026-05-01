"""
permissions.py — Kiểm tra phân quyền DUTY_ADMIN / DUTY_MOD / DUTY_MEMBER
Mọi slash command phải gọi check_permission() trước khi thực thi
"""
import logging
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import discord
from models.guild import GuildConfig

logger = logging.getLogger(__name__)


class DutyRole:
    ADMIN = "DUTY_ADMIN"
    MOD = "DUTY_MOD"
    MEMBER = "DUTY_MEMBER"

    # Thứ tự quyền từ cao xuống thấp
    HIERARCHY = [ADMIN, MOD, MEMBER]


async def get_guild_config(
    guild_id: int, session: AsyncSession
) -> GuildConfig | None:
    """Lấy config của guild từ DB"""
    result = await session.execute(
        select(GuildConfig).where(GuildConfig.guild_id == guild_id)
    )
    return result.scalar_one_or_none()


async def check_permission(
    interaction: discord.Interaction,
    required_role: str,
    session: AsyncSession,
) -> bool:
    """
    Kiểm tra user có role tối thiểu required_role không.
    Phân quyền theo thứ bậc: ADMIN ≥ MOD ≥ MEMBER.
    Guild owner luôn có quyền ADMIN.
    """
    if interaction.guild is None:
        return False

    # Guild owner luôn có toàn quyền
    if interaction.user.id == interaction.guild.owner_id:
        return True

    config = await get_guild_config(interaction.guild_id, session)
    if not config or not config.is_active:
        logger.warning(f"Guild {interaction.guild_id} chưa setup hoặc không active")
        return False

    # Xác định required_role ở vị trí nào trong hierarchy
    try:
        required_level = DutyRole.HIERARCHY.index(required_role)
    except ValueError:
        logger.error(f"Required role không hợp lệ: {required_role}")
        return False

    # Kiểm tra user có bất kỳ role nào từ level required trở lên
    for role_name in DutyRole.HIERARCHY[:required_level + 1]:
        role_id = config.role_map.get(role_name)
        if not role_id:
            continue
        guild_role = interaction.guild.get_role(int(role_id))
        if guild_role and guild_role in interaction.user.roles:
            return True

    return False


async def require_admin(
    interaction: discord.Interaction, session: AsyncSession
) -> bool:
    return await check_permission(interaction, DutyRole.ADMIN, session)


async def require_mod(
    interaction: discord.Interaction, session: AsyncSession
) -> bool:
    return await check_permission(interaction, DutyRole.MOD, session)


async def require_member(
    interaction: discord.Interaction, session: AsyncSession
) -> bool:
    return await check_permission(interaction, DutyRole.MEMBER, session)


async def send_no_permission(interaction: discord.Interaction, required: str) -> None:
    """Gửi thông báo không đủ quyền"""
    from bot.utils.embed_builder import build_error_embed
    embed = build_error_embed(
        f"Bạn cần role **{required}** hoặc cao hơn để dùng lệnh này.\n"
        "Liên hệ admin server để được cấp quyền."
    )
    if interaction.response.is_done():
        await interaction.followup.send(embed=embed, ephemeral=True)
    else:
        await interaction.response.send_message(embed=embed, ephemeral=True)
