"""
embed_builder.py — Tạo Discord embed đẹp cho TOP, stats, log view, lỗi
"""
from datetime import datetime
import discord
from bot.utils.time_utils import minutes_to_hhmm, format_datetime_vn, utcnow

# Màu sắc
COLOR_SUCCESS = 0x57F287   # Xanh lá
COLOR_ERROR = 0xED4245     # Đỏ
COLOR_INFO = 0x5865F2      # Discord blurple
COLOR_WARNING = 0xFEE75C   # Vàng
COLOR_TOP = 0xFFD700       # Vàng gold (TOP)
COLOR_BOTTOM = 0x99AAB5    # Xám (BOTTOM)

MEDALS = ["🥇", "🥈", "🥉"]
PERIOD_LABELS = {
    "day": "Hôm nay",
    "week": "Tuần này",
    "month": "Tháng này",
    "quarter": "Quý này",
    "custom": "Khoảng thời gian tùy chọn",
}


def build_top_embed(
    rankings: list[dict],
    period: str,
    mode: str = "top",
    guild_name: str = "",
    date_range: tuple[str, str] | None = None,
) -> discord.Embed:
    """
    Tạo embed bảng xếp hạng TOP/BOTTOM.
    rankings: [{"username": str, "total_minutes": int, "session_count": int}]
    mode: "top" | "bottom"
    """
    period_label = PERIOD_LABELS.get(period, period)
    if date_range:
        period_label = f"{date_range[0]} → {date_range[1]}"

    if mode == "top":
        title = f"🏆 TOP TRỰC — {period_label}"
        color = COLOR_TOP
    else:
        title = f"📉 BOTTOM TRỰC — {period_label}"
        color = COLOR_BOTTOM

    embed = discord.Embed(title=title, color=color)
    if guild_name:
        embed.set_author(name=guild_name)

    if not rankings:
        embed.description = "_Chưa có dữ liệu trong khoảng thời gian này_"
        return embed

    lines = []
    for i, row in enumerate(rankings[:10]):
        medal = MEDALS[i] if i < 3 else f"`{i + 1}.`"
        name = discord.utils.escape_markdown(row["username"])
        duration = minutes_to_hhmm(row["total_minutes"])
        sessions = row["session_count"]
        lines.append(f"{medal} **{name}** — ⏱ {duration} | 📋 {sessions} ca")

    embed.description = "\n".join(lines)
    embed.set_footer(
        text=f"Cập nhật lúc {utcnow().strftime('%H:%M %d/%m/%Y')} UTC • Tổng {len(rankings)} người"
    )
    return embed


def build_stats_embed(
    username: str,
    stats: dict,
    period: str,
    guild_name: str = "",
) -> discord.Embed:
    """
    Tạo embed thống kê cá nhân.
    stats keys: total_minutes, session_count, avg_minutes, rank, date_range
    """
    embed = discord.Embed(
        title=f"📊 Thống kê — {discord.utils.escape_markdown(username)}",
        color=COLOR_INFO,
    )
    if guild_name:
        embed.set_author(name=guild_name)

    period_label = PERIOD_LABELS.get(period, period)
    embed.add_field(name="⏳ Kỳ thống kê", value=period_label, inline=False)
    embed.add_field(name="⏱ Tổng thời gian", value=minutes_to_hhmm(stats.get("total_minutes", 0)), inline=True)
    embed.add_field(name="📋 Số ca trực", value=str(stats.get("session_count", 0)), inline=True)
    avg = stats.get("avg_minutes", 0)
    embed.add_field(name="📈 Trung bình/ca", value=minutes_to_hhmm(int(avg)), inline=True)

    if stats.get("rank"):
        embed.add_field(name="🏅 Xếp hạng", value=f"#{stats['rank']}", inline=True)

    embed.set_footer(text=f"Cập nhật lúc {utcnow().strftime('%H:%M %d/%m/%Y')} UTC")
    return embed


def build_log_view_embed(
    username: str,
    logs: list[dict],
    page: int = 1,
    total_pages: int = 1,
    guild_tz: str | None = None,
    total_count: int = 0,
    grand_total_minutes: int = 0,
) -> discord.Embed:
    """
    Tạo embed lịch sử chấm công, GROUP THEO NGÀY.
    logs: [{"id", "started_at", "ended_at", "duration_minutes", "source"}]
    Mỗi ngày = 1 field hiển thị tổng + danh sách ca trong ngày.
    """
    import pytz
    from bot.utils.time_utils import to_local
    from collections import defaultdict

    embed = discord.Embed(
        title=f"📋 Lịch sử trực — {discord.utils.escape_markdown(username)}",
        color=COLOR_INFO,
    )

    if not logs:
        embed.description = "_Chưa có dữ liệu chấm công_"
        return embed

    # Group logs theo ngày local
    weekdays = ["Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7", "Chủ nhật"]
    by_date: dict[str, list[dict]] = defaultdict(list)
    date_meta: dict[str, tuple[int, str]] = {}  # date_key → (sort_key, weekday_label)

    for log in logs:
        local_start = to_local(log["started_at"], guild_tz)
        date_key = local_start.strftime("%d/%m/%Y")
        wd = weekdays[local_start.weekday()]
        by_date[date_key].append((local_start, log))
        date_meta[date_key] = (int(local_start.strftime("%Y%m%d")), wd)

    # Sắp xếp ngày: mới nhất trước
    sorted_dates = sorted(by_date.keys(), key=lambda d: date_meta[d][0], reverse=True)

    SOURCE_ICON = {"ocr": "📸", "forward": "💬", "message": "📨", "manual": "✍️"}

    # Hiển thị tối đa 10 ngày để tránh embed quá dài
    DISPLAY_DAYS = 10
    for date_key in sorted_dates[:DISPLAY_DAYS]:
        entries = sorted(by_date[date_key], key=lambda e: e[0])  # sắp giờ tăng dần
        day_total = sum(log["duration_minutes"] for _, log in entries)
        wd = date_meta[date_key][1]

        lines = []
        for local_start, log in entries:
            local_end = to_local(log["ended_at"], guild_tz)
            t_start = local_start.strftime("%H:%M")
            t_end = local_end.strftime("%H:%M")
            icon = SOURCE_ICON.get(log.get("source", ""), "•")
            log_id = log.get("id")
            id_str = f"`#{log_id}`" if log_id else ""
            lines.append(f"  {id_str} {icon} `{t_start}` → `{t_end}` ({log['duration_minutes']} phút)")

        field_value = "\n".join(lines)
        field_name = f"📅 {wd}, {date_key} — Tổng **{day_total} phút** ({minutes_to_hhmm(day_total)})"
        embed.add_field(name=field_name, value=field_value, inline=False)

    if len(sorted_dates) > DISPLAY_DAYS:
        embed.add_field(
            name="…",
            value=f"_+{len(sorted_dates) - DISPLAY_DAYS} ngày khác (dùng `trang:` để xem tiếp)_",
            inline=False,
        )

    # Footer: tổng kết
    total_str = minutes_to_hhmm(grand_total_minutes) if grand_total_minutes else f"{sum(l['duration_minutes'] for l in logs)} phút"
    footer_total = total_count if total_count else len(logs)
    embed.set_footer(
        text=f"Trang {page}/{total_pages} • {footer_total} ca • Tổng {total_str}"
    )
    return embed


def build_all_logs_table_embed(
    logs: list[dict],
    page: int,
    total_pages: int,
    total_count: int,
    grand_total_minutes: int,
    unique_users: int,
    guild_name: str,
    guild_tz: str | None = None,
) -> discord.Embed:
    """
    Bảng tất cả log của guild (cho MOD+) — render dạng table monospace.
    Columns: ID | Tên | Ngày | Vào | Ra | Phút | Nguồn
    """
    from bot.utils.time_utils import to_local

    embed = discord.Embed(
        title=f"📋 Lịch sử chấm công — {discord.utils.escape_markdown(guild_name)}",
        color=COLOR_INFO,
    )

    if not logs:
        embed.description = "_Chưa có dữ liệu chấm công trong khoảng thời gian này_"
        embed.set_footer(text=f"Trang {page}/{total_pages}")
        return embed

    SOURCE_LABEL = {"ocr": "📸", "forward": "💬", "message": "📨", "manual": "✍️"}

    def trunc(s: str, n: int) -> str:
        s = str(s or "")
        return s if len(s) <= n else s[:n - 1] + "…"

    # Header
    header = f"{'ID':<5} {'Tên':<14} {'Ngày':<10} {'Vào':<5} {'Ra':<5} {'Phút':>5} {'NG'}"
    separator = "─" * 56

    rows = [header, separator]
    for log in logs:
        local_start = to_local(log["started_at"], guild_tz)
        local_end = to_local(log["ended_at"], guild_tz)
        src = SOURCE_LABEL.get(log.get("source", ""), "•")
        rows.append(
            f"#{str(log['id']):<4} "
            f"{trunc(log['username'], 14):<14} "
            f"{local_start.strftime('%d/%m/%Y'):<10} "
            f"{local_start.strftime('%H:%M'):<5} "
            f"{local_end.strftime('%H:%M'):<5} "
            f"{log['duration_minutes']:>5} "
            f"{src}"
        )

    table = "```\n" + "\n".join(rows) + "\n```"

    # Discord giới hạn description 4096 chars; nếu quá, cắt bớt rows
    if len(table) > 4000:
        # Cắt còn vừa
        while len(table) > 4000 and len(rows) > 3:
            rows.pop()
        rows.append("…(còn nữa, dùng trang: kế tiếp)")
        table = "```\n" + "\n".join(rows) + "\n```"

    embed.description = table

    embed.set_footer(
        text=(
            f"Trang {page}/{total_pages} • {total_count} ca • "
            f"{unique_users} người • Tổng {minutes_to_hhmm(grand_total_minutes)}"
        )
    )
    return embed


def build_log_confirm_embed(
    parsed_data: dict,
    guild_tz: str | None = None,
    is_loose_match: bool = False,
) -> discord.Embed:
    """
    Tạo embed xác nhận trước khi lưu log (sau OCR hoặc parse forward).
    Hiển thị dữ liệu đã trích xuất để user xác nhận.
    """
    color = COLOR_WARNING if is_loose_match else COLOR_SUCCESS
    title = "⚠️ Xác nhận lưu LOG DUTY (nhận dạng không chắc)" if is_loose_match else "✅ Xác nhận lưu LOG DUTY"

    embed = discord.Embed(title=title, color=color)
    # Escape markdown trong username để chặn user chèn [link](url), **bold**, @mention
    safe_username = discord.utils.escape_markdown(str(parsed_data["username"]))
    embed.add_field(name="👤 Tên", value=safe_username, inline=True)
    embed.add_field(name="⏱ Thời gian", value=minutes_to_hhmm(parsed_data["duration_minutes"]), inline=True)
    embed.add_field(name="🕐 Bắt đầu", value=format_datetime_vn(parsed_data["started_at"], guild_tz), inline=False)
    embed.add_field(name="🕑 Kết thúc", value=format_datetime_vn(parsed_data["ended_at"], guild_tz), inline=False)

    if is_loose_match:
        embed.set_footer(text="⚠️ Dữ liệu được nhận dạng qua OCR mờ — vui lòng kiểm tra kỹ trước khi xác nhận")
    return embed


def build_error_embed(message: str, title: str = "❌ Có lỗi xảy ra") -> discord.Embed:
    return discord.Embed(title=title, description=message, color=COLOR_ERROR)


def build_success_embed(message: str, title: str = "✅ Thành công") -> discord.Embed:
    return discord.Embed(title=title, description=message, color=COLOR_SUCCESS)


def build_info_embed(message: str, title: str = "ℹ️ Thông báo") -> discord.Embed:
    return discord.Embed(title=title, description=message, color=COLOR_INFO)


# ─── Auto-scan embeds ────────────────────────────────────────────────────────

SUPPORT_FOOTER = "Nếu cần hỗ trợ vui lòng liên hệ ban lãnh đạo"


def build_log_accepted_embed(
    parsed,
    author: discord.abc.User,
    guild_tz: str | None = None,
) -> discord.Embed:
    """
    Embed xác nhận đã lưu thành công khi auto-scan log trong channel chấm công.
    Hiển thị đầy đủ thông tin ca trực để member kiểm tra lại.
    """
    embed = discord.Embed(
        title="✅ Đã ghi nhận ca trực",
        description=f"Cảm ơn **{discord.utils.escape_markdown(author.display_name)}** đã chấm công đúng giờ!",
        color=COLOR_SUCCESS,
    )

    safe_username = discord.utils.escape_markdown(parsed.username)
    embed.add_field(name="👤 Tên", value=safe_username, inline=True)
    embed.add_field(
        name="⏱ Thời gian",
        value=f"**{minutes_to_hhmm(parsed.duration_minutes)}**",
        inline=True,
    )
    embed.add_field(name="​", value="​", inline=True)  # spacer
    embed.add_field(
        name="🕐 Bắt đầu",
        value=format_datetime_vn(parsed.started_at, guild_tz),
        inline=True,
    )
    embed.add_field(
        name="🕑 Kết thúc",
        value=format_datetime_vn(parsed.ended_at, guild_tz),
        inline=True,
    )
    embed.add_field(name="​", value="​", inline=True)

    # Avatar người gửi
    if hasattr(author, "display_avatar") and author.display_avatar:
        embed.set_thumbnail(url=author.display_avatar.url)

    embed.set_footer(text=f"{SUPPORT_FOOTER} • {utcnow().strftime('%H:%M %d/%m/%Y')} UTC")
    return embed


def build_log_rejected_embed(
    parsed,
    reason: str,
    author: discord.abc.User,
) -> discord.Embed:
    """
    Embed từ chối log với lý do rõ ràng.
    Dùng khi auto-scan parse được nhưng vi phạm rule (overlap, tương lai, etc.)
    """
    embed = discord.Embed(
        title="🚫 Log chấm công bị từ chối",
        description=(
            f"**{discord.utils.escape_markdown(author.display_name)}**, "
            "log của bạn không thể được lưu vì lý do bên dưới:"
        ),
        color=COLOR_ERROR,
    )

    embed.add_field(name="📋 Lý do", value=reason, inline=False)

    if parsed is not None:
        safe_username = discord.utils.escape_markdown(parsed.username)
        info_lines = [
            f"**Tên:** {safe_username}",
            f"**Thời gian:** {minutes_to_hhmm(parsed.duration_minutes)}",
            f"**Bắt đầu:** `{parsed.started_at.strftime('%d/%m/%Y %H:%M')}`",
            f"**Kết thúc:** `{parsed.ended_at.strftime('%d/%m/%Y %H:%M')}`",
        ]
        embed.add_field(name="📄 Thông tin log", value="\n".join(info_lines), inline=False)

    embed.add_field(
        name="💡 Gợi ý",
        value=(
            "• Kiểm tra lại thời gian, tên trong log có khớp tài khoản Discord của bạn không.\n"
            "• Đảm bảo ca trực không trùng/chồng lên ca đã chấm trước đó.\n"
            "• Không log ca trực ở **tương lai** — phải đợi đến khi ca thực sự kết thúc."
        ),
        inline=False,
    )

    embed.set_footer(text=SUPPORT_FOOTER)
    return embed


def build_log_invalid_embed(
    errors: list[str],
    author: discord.abc.User,
) -> discord.Embed:
    """
    Embed báo lỗi validation khi parse được LOG DUTY nhưng dữ liệu sai logic
    (duration không khớp, start ≥ end, duration > 24h, etc.)
    """
    embed = discord.Embed(
        title="⚠️ Dữ liệu LOG DUTY không hợp lệ",
        description=(
            f"**{discord.utils.escape_markdown(author.display_name)}**, "
            "bot đã đọc được log của bạn nhưng dữ liệu chưa đúng:"
        ),
        color=COLOR_WARNING,
    )
    embed.add_field(
        name="❌ Vấn đề",
        value="\n".join(f"• {e}" for e in errors),
        inline=False,
    )
    embed.add_field(
        name="💡 Cách xử lý",
        value=(
            "• Kiểm tra lại định dạng ngày giờ: `DD/MM/YYYY HH:MM:SS`.\n"
            "• Đảm bảo **Thời gian làm việc** khớp với khoảng cách giữa Bắt đầu và Kết thúc.\n"
            "• Mỗi ca trực không được dài quá 24 giờ."
        ),
        inline=False,
    )
    embed.set_footer(text=SUPPORT_FOOTER)
    return embed


def build_log_name_mismatch_embed(
    parsed_name: str,
    author: discord.abc.User,
) -> discord.Embed:
    """
    Embed khi tên trong LOG DUTY không khớp với người gửi.
    Mỗi user CHỈ được tự gửi log của chính mình.
    """
    embed = discord.Embed(
        title="🚫 Tên không khớp",
        description=(
            f"Tên trong LOG DUTY là **{discord.utils.escape_markdown(parsed_name)}** "
            f"nhưng bạn đang đăng nhập bằng **{discord.utils.escape_markdown(author.display_name)}**."
        ),
        color=COLOR_ERROR,
    )
    embed.add_field(
        name="📌 Quy tắc",
        value=(
            "Mỗi người chỉ được gửi log chấm công của **chính mình**. "
            "Mod/Admin **KHÔNG** được gửi hộ — đảm bảo tính chính xác và truy vết."
        ),
        inline=False,
    )
    embed.add_field(
        name="💡 Gợi ý",
        value=(
            "• Kiểm tra lại tên trong LOG DUTY phải khớp **display name / nickname** Discord của bạn.\n"
            "• Nếu chưa đổi tên Discord cho khớp, vui lòng đổi rồi gửi lại."
        ),
        inline=False,
    )
    embed.set_footer(text=SUPPORT_FOOTER)
    return embed


def build_log_duplicate_embed(author: discord.abc.User) -> discord.Embed:
    """Embed nhẹ thông báo log đã được lưu trước đó (duplicate)."""
    embed = discord.Embed(
        title="🔁 Log đã được ghi nhận trước đó",
        description=(
            f"**{discord.utils.escape_markdown(author.display_name)}**, "
            "ca trực này đã có trong hệ thống. Không cần gửi lại."
        ),
        color=COLOR_INFO,
    )
    embed.set_footer(text=SUPPORT_FOOTER)
    return embed
