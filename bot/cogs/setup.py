"""
setup.py — Cog /setup role, /setup channel, /setup timezone
Chỉ DUTY_ADMIN hoặc guild owner mới được dùng
"""
import logging
from discord.ext import commands
from discord import app_commands
import discord
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.base import AsyncSessionLocal
from models.guild import GuildConfig
from models.audit_log import AuditLog, AuditAction
from bot.utils.permissions import require_admin, send_no_permission, DutyRole
from bot.utils.embed_builder import build_success_embed, build_error_embed, build_info_embed
from bot.utils.time_utils import utcnow

logger = logging.getLogger(__name__)

VALID_TIMEZONES = [
    "Asia/Ho_Chi_Minh", "Asia/Bangkok", "Asia/Singapore",
    "Asia/Tokyo", "UTC", "America/New_York", "Europe/London",
]


class SetupCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    setup_group = app_commands.Group(
        name="setup",
        description="Cấu hình bot chấm công cho server (yêu cầu DUTY_ADMIN)"
    )

    @setup_group.command(name="init", description="Khởi tạo bot cho server lần đầu")
    async def setup_init(self, interaction: discord.Interaction):
        """Tạo GuildConfig nếu chưa có — chỉ guild owner mới được chạy lần đầu"""
        await interaction.response.defer(ephemeral=True)

        # Lần đầu setup: chỉ guild owner mới được
        if interaction.user.id != interaction.guild.owner_id:
            async with AsyncSessionLocal() as session:
                if not await require_admin(interaction, session):
                    await send_no_permission(interaction, DutyRole.ADMIN)
                    return

        async with AsyncSessionLocal() as session:
            existing = await session.execute(
                select(GuildConfig).where(GuildConfig.guild_id == interaction.guild_id)
            )
            if existing.scalar_one_or_none():
                await interaction.followup.send(
                    embed=build_info_embed(
                        "Server này đã được cấu hình rồi.\n"
                        "Dùng `/setup role`, `/setup channel` để thay đổi."
                    ),
                    ephemeral=True,
                )
                return

            config = GuildConfig(
                guild_id=interaction.guild_id,
                guild_name=interaction.guild.name,
                role_map={},
                timezone="Asia/Ho_Chi_Minh",
                is_active=True,
                created_at=utcnow(),
                updated_at=utcnow(),
            )
            session.add(config)

            session.add(AuditLog(
                guild_id=interaction.guild_id,
                user_id=interaction.user.id,
                username=str(interaction.user),
                action=AuditAction.SETUP_GUILD,
                detail={"guild_name": interaction.guild.name},
                created_at=utcnow(),
            ))
            await session.commit()

        embed = build_success_embed(
            "✅ Bot đã được khởi tạo cho server!\n\n"
            "**Bước tiếp theo:**\n"
            "1️⃣ `/setup role admin @role` — Gán role DUTY_ADMIN\n"
            "2️⃣ `/setup role mod @role` — Gán role DUTY_MOD\n"
            "3️⃣ `/setup role member @role` — Gán role DUTY_MEMBER\n"
            "4️⃣ `/setup channel #channel` — Chọn channel nhận log\n"
            "5️⃣ `/setup timezone` — Cấu hình timezone",
            title="🎉 Khởi tạo thành công"
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @setup_group.command(name="role", description="Gán Discord role vào quyền DUTY")
    @app_commands.describe(
        quyen="Loại quyền cần gán",
        role="Discord role tương ứng",
    )
    @app_commands.choices(quyen=[
        app_commands.Choice(name="👑 DUTY_ADMIN — Toàn quyền", value="DUTY_ADMIN"),
        app_commands.Choice(name="🛡️ DUTY_MOD — Xem và xuất báo cáo", value="DUTY_MOD"),
        app_commands.Choice(name="👤 DUTY_MEMBER — Chỉ xem log cá nhân", value="DUTY_MEMBER"),
    ])
    async def setup_role(
        self,
        interaction: discord.Interaction,
        quyen: str,
        role: discord.Role,
    ):
        await interaction.response.defer(ephemeral=True)

        async with AsyncSessionLocal() as session:
            if not await require_admin(interaction, session):
                await send_no_permission(interaction, DutyRole.ADMIN)
                return

            config = await _get_or_create_config(session, interaction)
            role_map = dict(config.role_map or {})
            # Lưu role_id dưới dạng string trong JSON: tránh mất chính xác snowflake 64-bit
            # Permissions check sẽ int(role_id) khi đọc — an toàn cho cả int/str
            role_map[quyen] = str(role.id)
            config.role_map = role_map
            config.updated_at = utcnow()

            session.add(AuditLog(
                guild_id=interaction.guild_id,
                user_id=interaction.user.id,
                username=str(interaction.user),
                action=AuditAction.CHANGE_ROLE_CONFIG,
                detail={"role_name": quyen, "role_id": role.id, "discord_role": role.name},
                created_at=utcnow(),
            ))
            await session.commit()

        await interaction.followup.send(
            embed=build_success_embed(f"Đã gán **{role.mention}** vào quyền **{quyen}**"),
            ephemeral=True,
        )

    @setup_group.command(name="channel", description="Chọn channel duy nhất nhận log chấm công")
    @app_commands.describe(channel="Channel nhận log (bỏ trống = cho phép tất cả channel)")
    async def setup_channel(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel | None = None,
    ):
        await interaction.response.defer(ephemeral=True)

        async with AsyncSessionLocal() as session:
            if not await require_admin(interaction, session):
                await send_no_permission(interaction, DutyRole.ADMIN)
                return

            config = await _get_or_create_config(session, interaction)
            config.log_channel_id = channel.id if channel else None
            config.updated_at = utcnow()

            session.add(AuditLog(
                guild_id=interaction.guild_id,
                user_id=interaction.user.id,
                username=str(interaction.user),
                action=AuditAction.CHANGE_CHANNEL_CONFIG,
                detail={"channel_id": channel.id if channel else None},
                created_at=utcnow(),
            ))
            await session.commit()

        msg = f"Đã cấu hình channel log: {channel.mention}" if channel else "Đã cho phép log ở tất cả channel"
        await interaction.followup.send(embed=build_success_embed(msg), ephemeral=True)

    @setup_group.command(name="timezone", description="Cấu hình timezone của server")
    @app_commands.describe(tz="Timezone (VD: Asia/Ho_Chi_Minh)")
    @app_commands.choices(tz=[
        app_commands.Choice(name="🇻🇳 Asia/Ho_Chi_Minh (GMT+7)", value="Asia/Ho_Chi_Minh"),
        app_commands.Choice(name="🇹🇭 Asia/Bangkok (GMT+7)", value="Asia/Bangkok"),
        app_commands.Choice(name="🇸🇬 Asia/Singapore (GMT+8)", value="Asia/Singapore"),
        app_commands.Choice(name="🇯🇵 Asia/Tokyo (GMT+9)", value="Asia/Tokyo"),
        app_commands.Choice(name="🌐 UTC", value="UTC"),
    ])
    async def setup_timezone(
        self,
        interaction: discord.Interaction,
        tz: str = "Asia/Ho_Chi_Minh",
    ):
        await interaction.response.defer(ephemeral=True)

        async with AsyncSessionLocal() as session:
            if not await require_admin(interaction, session):
                await send_no_permission(interaction, DutyRole.ADMIN)
                return

            config = await _get_or_create_config(session, interaction)
            config.timezone = tz
            config.updated_at = utcnow()
            await session.commit()

        await interaction.followup.send(
            embed=build_success_embed(f"Đã cập nhật timezone: **{tz}**"),
            ephemeral=True,
        )

    @setup_group.command(name="channel-dangky", description="Channel nơi /dangky được dùng")
    @app_commands.describe(channel="Channel cho phép dùng /dangky (bỏ trống = mọi channel)")
    async def setup_channel_dangky(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel | None = None,
    ):
        await self._setup_channel_field(interaction, "schedule_channel_id", channel, "đăng ký lịch")

    @setup_group.command(name="channel-nhactruc", description="Channel để bot tag nhắc trước ca trực")
    @app_commands.describe(channel="Channel sẽ tag user nhắc trước ca")
    async def setup_channel_nhactruc(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
    ):
        await self._setup_channel_field(interaction, "remind_channel_id", channel, "nhắc trực")

    @setup_group.command(name="channel-xinnghi", description="Channel post đơn xin nghỉ + xin out để staff vote")
    @app_commands.describe(channel="Channel staff sẽ react ✅/❌")
    async def setup_channel_xinnghi(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
    ):
        await self._setup_channel_field(interaction, "leave_channel_id", channel, "xin nghỉ")

    @setup_group.command(name="channel-staff", description="Channel staff nhận thông báo (sửa lịch, audit)")
    @app_commands.describe(channel="Channel cho admin/mod theo dõi")
    async def setup_channel_staff(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
    ):
        await self._setup_channel_field(interaction, "staff_channel_id", channel, "staff quản lý")

    @setup_group.command(name="role-medic", description="Role 'Medic' (để onboarding scan ai chưa đăng ký)")
    @app_commands.describe(role="Role nhân viên Medic")
    async def setup_role_medic(
        self,
        interaction: discord.Interaction,
        role: discord.Role,
    ):
        await interaction.response.defer(ephemeral=True)
        async with AsyncSessionLocal() as session:
            if not await require_admin(interaction, session):
                await send_no_permission(interaction, DutyRole.ADMIN)
                return
            config = await _get_or_create_config(session, interaction)
            config.medic_role_id = role.id
            config.updated_at = utcnow()
            session.add(AuditLog(
                guild_id=interaction.guild_id,
                user_id=interaction.user.id,
                username=str(interaction.user),
                action=AuditAction.CHANGE_ROLE_CONFIG,
                detail={"role_name": "MEDIC", "role_id": str(role.id), "discord_role": role.name},
                created_at=utcnow(),
            ))
            await session.commit()
        await interaction.followup.send(
            embed=build_success_embed(f"Đã set role **Medic** = {role.mention}"),
            ephemeral=True,
        )

    @setup_group.command(name="remind-default", description="Mốc nhắc trước ca mặc định (phút)")
    @app_commands.describe(moc="Các mốc cách nhau dấu phẩy, vd: 60,30,5")
    async def setup_remind_default(
        self,
        interaction: discord.Interaction,
        moc: str = "60,30,5",
    ):
        await interaction.response.defer(ephemeral=True)
        try:
            offsets = sorted({int(x.strip()) for x in moc.split(",") if x.strip()}, reverse=True)
            for n in offsets:
                if not (0 < n <= 240):
                    raise ValueError(f"Mốc {n} phải 1-240 phút")
        except ValueError as e:
            await interaction.followup.send(
                embed=build_error_embed(f"Sai định dạng: {e}. Ví dụ: `60,30,5`"),
                ephemeral=True,
            )
            return

        async with AsyncSessionLocal() as session:
            if not await require_admin(interaction, session):
                await send_no_permission(interaction, DutyRole.ADMIN)
                return
            config = await _get_or_create_config(session, interaction)
            config.default_remind_offsets = offsets
            config.updated_at = utcnow()
            await session.commit()

        await interaction.followup.send(
            embed=build_success_embed(
                f"Đã set mốc nhắc mặc định: **{', '.join(map(str, offsets))} phút trước ca**.\n"
                "Member nào không tự chỉnh `/lich nhac` sẽ dùng các mốc này."
            ),
            ephemeral=True,
        )

    async def _setup_channel_field(
        self,
        interaction: discord.Interaction,
        field: str,
        channel: discord.TextChannel | None,
        label: str,
    ):
        await interaction.response.defer(ephemeral=True)
        async with AsyncSessionLocal() as session:
            if not await require_admin(interaction, session):
                await send_no_permission(interaction, DutyRole.ADMIN)
                return
            config = await _get_or_create_config(session, interaction)
            setattr(config, field, channel.id if channel else None)
            config.updated_at = utcnow()
            session.add(AuditLog(
                guild_id=interaction.guild_id,
                user_id=interaction.user.id,
                username=str(interaction.user),
                action=AuditAction.CHANGE_CHANNEL_CONFIG,
                detail={"field": field, "channel_id": str(channel.id) if channel else None},
                created_at=utcnow(),
            ))
            await session.commit()

        if channel:
            msg = f"Đã set channel **{label}** = {channel.mention}"
        else:
            msg = f"Đã xoá channel **{label}** (về mặc định)"
        await interaction.followup.send(embed=build_success_embed(msg), ephemeral=True)

    @setup_group.command(name="cleanup-role-add", description="Thêm role vào cleanup list (tag tối đa 10 role 1 lần)")
    @app_commands.describe(
        role1="Role bắt buộc (tag @role)",
        role2="Optional — role thứ 2",
        role3="Optional — role thứ 3",
        role4="Optional — role thứ 4",
        role5="Optional — role thứ 5",
        role6="Optional — role thứ 6",
        role7="Optional — role thứ 7",
        role8="Optional — role thứ 8",
        role9="Optional — role thứ 9",
        role10="Optional — role thứ 10",
    )
    async def setup_cleanup_role_add(
        self,
        interaction: discord.Interaction,
        role1: discord.Role,
        role2: discord.Role | None = None,
        role3: discord.Role | None = None,
        role4: discord.Role | None = None,
        role5: discord.Role | None = None,
        role6: discord.Role | None = None,
        role7: discord.Role | None = None,
        role8: discord.Role | None = None,
        role9: discord.Role | None = None,
        role10: discord.Role | None = None,
    ):
        await interaction.response.defer(ephemeral=True)
        async with AsyncSessionLocal() as session:
            if not await require_admin(interaction, session):
                await send_no_permission(interaction, DutyRole.ADMIN)
                return

            # Gom tất cả role không-None, dedupe theo id
            input_roles = [r for r in (role1, role2, role3, role4, role5,
                                        role6, role7, role8, role9, role10) if r is not None]
            seen_ids = set()
            unique_roles: list[discord.Role] = []
            for r in input_roles:
                if r.id not in seen_ids:
                    seen_ids.add(r.id)
                    unique_roles.append(r)

            config = await _get_or_create_config(session, interaction)
            current_ids = list(config.cleanup_role_ids or [])

            added: list[discord.Role] = []
            already: list[discord.Role] = []
            for r in unique_roles:
                rid_str = str(r.id)
                if rid_str in current_ids:
                    already.append(r)
                else:
                    current_ids.append(rid_str)
                    added.append(r)

            if not added:
                await interaction.followup.send(
                    embed=build_info_embed(
                        "Tất cả role bạn nhập đều **đã có** trong cleanup list:\n" +
                        "\n".join(f"• {r.mention}" for r in already[:10])
                    ),
                    ephemeral=True,
                )
                return

            config.cleanup_role_ids = current_ids
            config.updated_at = utcnow()

            session.add(AuditLog(
                guild_id=interaction.guild_id,
                user_id=interaction.user.id,
                username=str(interaction.user),
                action=AuditAction.CHANGE_ROLE_CONFIG,
                detail={
                    "field": "cleanup_role_ids",
                    "added_ids": [str(r.id) for r in added],
                    "added_names": [r.name for r in added],
                    "skipped_already_in_list": [str(r.id) for r in already],
                },
                created_at=utcnow(),
            ))
            await session.commit()

        # Build embed
        embed = build_success_embed(
            f"Đã thêm **{len(added)}** role vào cleanup list:\n" +
            "\n".join(f"• {r.mention}" for r in added) +
            f"\n\n_Tổng cleanup list hiện có **{len(current_ids)}** role._"
        )
        if already:
            embed.add_field(
                name="ℹ️ Đã có sẵn (skip)",
                value="\n".join(f"• {r.mention}" for r in already[:10]),
                inline=False,
            )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @setup_group.command(name="cleanup-role-remove", description="Bỏ role khỏi cleanup list (tag tối đa 10 role 1 lần)")
    @app_commands.describe(
        role1="Role bắt buộc",
        role2="Optional — role thứ 2",
        role3="Optional — role thứ 3",
        role4="Optional — role thứ 4",
        role5="Optional — role thứ 5",
        role6="Optional — role thứ 6",
        role7="Optional — role thứ 7",
        role8="Optional — role thứ 8",
        role9="Optional — role thứ 9",
        role10="Optional — role thứ 10",
    )
    async def setup_cleanup_role_remove(
        self,
        interaction: discord.Interaction,
        role1: discord.Role,
        role2: discord.Role | None = None,
        role3: discord.Role | None = None,
        role4: discord.Role | None = None,
        role5: discord.Role | None = None,
        role6: discord.Role | None = None,
        role7: discord.Role | None = None,
        role8: discord.Role | None = None,
        role9: discord.Role | None = None,
        role10: discord.Role | None = None,
    ):
        await interaction.response.defer(ephemeral=True)
        async with AsyncSessionLocal() as session:
            if not await require_admin(interaction, session):
                await send_no_permission(interaction, DutyRole.ADMIN)
                return

            input_roles = [r for r in (role1, role2, role3, role4, role5,
                                        role6, role7, role8, role9, role10) if r is not None]
            seen_ids = set()
            unique_roles: list[discord.Role] = []
            for r in input_roles:
                if r.id not in seen_ids:
                    seen_ids.add(r.id)
                    unique_roles.append(r)

            config = await _get_or_create_config(session, interaction)
            current_ids = list(config.cleanup_role_ids or [])

            removed: list[discord.Role] = []
            not_in_list: list[discord.Role] = []
            for r in unique_roles:
                rid_str = str(r.id)
                if rid_str in current_ids:
                    current_ids = [x for x in current_ids if x != rid_str]
                    removed.append(r)
                else:
                    not_in_list.append(r)

            if not removed:
                await interaction.followup.send(
                    embed=build_info_embed(
                        "Không có role nào trong cleanup list để bỏ:\n" +
                        "\n".join(f"• {r.mention}" for r in not_in_list[:10])
                    ),
                    ephemeral=True,
                )
                return

            config.cleanup_role_ids = current_ids
            config.updated_at = utcnow()

            session.add(AuditLog(
                guild_id=interaction.guild_id,
                user_id=interaction.user.id,
                username=str(interaction.user),
                action=AuditAction.CHANGE_ROLE_CONFIG,
                detail={
                    "field": "cleanup_role_ids",
                    "removed_ids": [str(r.id) for r in removed],
                    "removed_names": [r.name for r in removed],
                },
                created_at=utcnow(),
            ))
            await session.commit()

        embed = build_success_embed(
            f"Đã bỏ **{len(removed)}** role khỏi cleanup list:\n" +
            "\n".join(f"• {r.mention}" for r in removed) +
            f"\n\n_Còn lại **{len(current_ids)}** role._"
        )
        if not_in_list:
            embed.add_field(
                name="ℹ️ Không có sẵn (skip)",
                value="\n".join(f"• {r.mention}" for r in not_in_list[:10]),
                inline=False,
            )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @setup_group.command(name="cleanup-role-list", description="Xem cleanup list hiện tại")
    async def setup_cleanup_role_list(
        self,
        interaction: discord.Interaction,
    ):
        await interaction.response.defer(ephemeral=True)
        async with AsyncSessionLocal() as session:
            if not await require_admin(interaction, session):
                await send_no_permission(interaction, DutyRole.ADMIN)
                return
            config = await _get_or_create_config(session, interaction)
            current_ids = list(config.cleanup_role_ids or [])

        if not current_ids:
            await interaction.followup.send(
                embed=build_info_embed(
                    "_Cleanup list đang trống._\n\n"
                    "Dùng `/setup cleanup-role-add role:@TênRole` để thêm role.",
                    title="🧹 Cleanup List",
                ),
                ephemeral=True,
            )
            return

        # Build danh sách + đánh dấu role nào không còn tồn tại
        lines = []
        missing_count = 0
        for rid in current_ids:
            try:
                role_obj = interaction.guild.get_role(int(rid))
            except (ValueError, TypeError):
                role_obj = None
            if role_obj:
                lines.append(f"✅ {role_obj.mention} `({rid})`")
            else:
                lines.append(f"⚠️ `<deleted role {rid}>`")
                missing_count += 1

        embed = build_info_embed(
            "\n".join(lines)[:4000],
            title=f"🧹 Cleanup List ({len(current_ids)} role)",
        )
        if missing_count:
            embed.set_footer(
                text=f"⚠️ {missing_count} role đã bị xoá khỏi server — "
                "dùng /setup cleanup-role-clear để dọn"
            )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @setup_group.command(name="cleanup-role-clear", description="Xoá toàn bộ cleanup list")
    async def setup_cleanup_role_clear(
        self,
        interaction: discord.Interaction,
    ):
        await interaction.response.defer(ephemeral=True)
        async with AsyncSessionLocal() as session:
            if not await require_admin(interaction, session):
                await send_no_permission(interaction, DutyRole.ADMIN)
                return

            config = await _get_or_create_config(session, interaction)
            old_count = len(config.cleanup_role_ids or [])
            config.cleanup_role_ids = []
            config.updated_at = utcnow()

            session.add(AuditLog(
                guild_id=interaction.guild_id,
                user_id=interaction.user.id,
                username=str(interaction.user),
                action=AuditAction.CHANGE_ROLE_CONFIG,
                detail={"field": "cleanup_role_ids", "action": "clear", "removed_count": old_count},
                created_at=utcnow(),
            ))
            await session.commit()

        await interaction.followup.send(
            embed=build_success_embed(
                f"Đã xoá **{old_count}** role khỏi cleanup list.\n\n"
                "_Sau khi clear, sa thải / out ngành sẽ không gỡ role nào (trừ medic role)._"
            ),
            ephemeral=True,
        )

    @setup_group.command(name="info", description="Xem cấu hình hiện tại của server")
    async def setup_info(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        async with AsyncSessionLocal() as session:
            if not await require_admin(interaction, session):
                await send_no_permission(interaction, DutyRole.ADMIN)
                return

            result = await session.execute(
                select(GuildConfig).where(GuildConfig.guild_id == interaction.guild_id)
            )
            config = result.scalar_one_or_none()

        if not config:
            await interaction.followup.send(
                embed=build_error_embed("Server chưa được setup. Dùng `/setup init` trước."),
                ephemeral=True,
            )
            return

        embed = build_info_embed("", title="⚙️ Cấu hình server")
        embed.add_field(name="🌏 Timezone", value=config.timezone, inline=True)

        # Channels
        def fmt_ch(cid):
            return f"<#{cid}>" if cid else "_(chưa set)_"

        embed.add_field(name="📢 Channel log chấm công", value=fmt_ch(config.log_channel_id), inline=True)
        embed.add_field(name="📅 Channel đăng ký lịch", value=fmt_ch(config.schedule_channel_id), inline=True)
        embed.add_field(name="🔔 Channel nhắc trực", value=fmt_ch(config.remind_channel_id), inline=True)
        embed.add_field(name="🏖 Channel xin nghỉ", value=fmt_ch(config.leave_channel_id), inline=True)
        embed.add_field(name="👮 Channel staff", value=fmt_ch(config.staff_channel_id), inline=True)

        medic = f"<@&{config.medic_role_id}>" if config.medic_role_id else "_(chưa set)_"
        embed.add_field(name="🩺 Role Medic", value=medic, inline=True)

        offsets = config.default_remind_offsets or []
        embed.add_field(
            name="🔔 Mốc nhắc default",
            value=f"`{', '.join(map(str, offsets))} phút`" if offsets else "_(chưa set)_",
            inline=True,
        )

        cleanup_ids = config.cleanup_role_ids or []
        if cleanup_ids:
            cleanup_str = ", ".join(f"<@&{rid}>" for rid in cleanup_ids[:5])
            if len(cleanup_ids) > 5:
                cleanup_str += f" +{len(cleanup_ids) - 5}"
            embed.add_field(name="🧹 Role tự gỡ khi sa thải", value=cleanup_str, inline=False)
        else:
            embed.add_field(name="🧹 Role tự gỡ khi sa thải", value="_(chưa set — `/setup cleanup-roles ids:...`)_", inline=False)

        role_map = config.role_map or {}
        roles_text = "\n".join([
            f"**{k}**: <@&{v}>" for k, v in role_map.items()
        ]) or "_Chưa cấu hình role_"
        embed.add_field(name="🎭 Phân quyền", value=roles_text, inline=False)

        await interaction.followup.send(embed=embed, ephemeral=True)


async def _get_or_create_config(session: AsyncSession, interaction: discord.Interaction) -> GuildConfig:
    """Lấy hoặc tạo mới GuildConfig"""
    result = await session.execute(
        select(GuildConfig).where(GuildConfig.guild_id == interaction.guild_id)
    )
    config = result.scalar_one_or_none()
    if config is None:
        config = GuildConfig(
            guild_id=interaction.guild_id,
            guild_name=interaction.guild.name,
            role_map={},
            timezone="Asia/Ho_Chi_Minh",
            is_active=True,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        session.add(config)
    return config


async def setup(bot: commands.Bot):
    await bot.add_cog(SetupCog(bot))
