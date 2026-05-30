"""
test_embed_extract.py — Test LogDutyCog._embed_to_text với các structure
embed thường gặp từ webhook LOG DUTY.

Lý do tồn tại: Discord embed có thể đặt label trong `field.name` và data
trong `field.value` (2 phần tách rời). Nếu code chỉ append 2 dòng riêng thì
parser sẽ mất dấu ":" giữa label và data → fail. Fix _embed_to_text phải
ghép thành "label: value" + strip markdown bold.

Chạy: pytest tests/test_embed_extract.py -v
"""
import discord

from bot.cogs.log_duty import LogDutyCog
from bot.utils.parser import parse_duty_text


# ─── Case 1: webhook gửi embed với fields (name+value tách) ────────────────

def test_embed_fields_separated_join_with_colon():
    """Embed có fields, label trong field.name không có dấu ':' → phải auto-thêm"""
    embed = discord.Embed(title="CAPY TOWN LOGS")
    embed.add_field(name="Tên", value="Báo Lê (CP890743)", inline=False)
    embed.add_field(name="Tên discord", value="@! VT | Null", inline=False)
    embed.add_field(name="Tổng thời gian", value="40 Phút", inline=False)
    embed.add_field(name="Bắt đầu", value="31/05/2026 00:58:50", inline=False)
    embed.add_field(name="Kết thúc", value="31/05/2026 01:39:05", inline=False)

    text = LogDutyCog._embed_to_text(embed)

    # Mỗi field phải có dạng "label: value" trên cùng dòng
    assert "Tên: Báo Lê (CP890743)" in text
    assert "Tổng thời gian: 40 Phút" in text
    assert "Bắt đầu: 31/05/2026 00:58:50" in text

    # Parser phải nhận
    parsed = parse_duty_text(text)
    assert parsed is not None
    assert parsed.username == "Báo Lê (CP890743)"
    assert parsed.duration_minutes == 40
    assert parsed.discord_handle == "@! VT | Null"


def test_embed_field_name_already_has_colon():
    """Nếu field.name đã có dấu ':' → KHÔNG thêm lần nữa"""
    embed = discord.Embed(title="CAPY TOWN LOGS")
    embed.add_field(name="Tên:", value="Báo Lê", inline=False)
    embed.add_field(name="Tổng thời gian:", value="40 Phút", inline=False)
    embed.add_field(name="Bắt đầu:", value="31/05/2026 00:58:50", inline=False)
    embed.add_field(name="Kết thúc:", value="31/05/2026 01:39:05", inline=False)

    text = LogDutyCog._embed_to_text(embed)

    # Không có "Tên:: Báo Lê" (double colon)
    assert "Tên:: " not in text
    assert "Tên: Báo Lê" in text

    parsed = parse_duty_text(text)
    assert parsed is not None
    assert parsed.username == "Báo Lê"


def test_embed_description_with_markdown_bold():
    """Webhook đặt log trong description với **Tên:** bold → phải strip bold"""
    desc = (
        "**Tên:** Báo Lê (CP890743)\n"
        "**Tên discord:** @! VT | Null\n"
        "**Tổng thời gian:** 40 Phút\n"
        "**Bắt đầu:** 31/05/2026 00:58:50\n"
        "**Kết thúc:** 31/05/2026 01:39:05"
    )
    embed = discord.Embed(title="CAPY TOWN LOGS", description=desc)

    text = LogDutyCog._embed_to_text(embed)

    # Không còn ký tự **
    assert "**" not in text
    # Vẫn giữ dấu ':' và content
    assert "Tên: Báo Lê (CP890743)" in text

    parsed = parse_duty_text(text)
    assert parsed is not None
    assert parsed.duration_minutes == 40


def test_embed_with_only_value_no_label():
    """Field chỉ có value (name rỗng) → append value, không crash"""
    embed = discord.Embed(title="HEADER")
    embed.add_field(name="​", value="Some content", inline=False)
    text = LogDutyCog._embed_to_text(embed)
    assert "Some content" in text


def test_embed_empty():
    """Embed rỗng → trả empty string"""
    embed = discord.Embed()
    text = LogDutyCog._embed_to_text(embed)
    assert text == ""
