"""
test_autoscan_embeds.py — Unit test cho 5 embed builder mới của auto-scan:
- build_log_accepted_embed
- build_log_rejected_embed
- build_log_invalid_embed
- build_log_name_mismatch_embed
- build_log_duplicate_embed

Mỗi embed PHẢI có footer "Nếu cần hỗ trợ vui lòng liên hệ ban lãnh đạo"
(theo yêu cầu nghiệp vụ).

Chạy: pytest tests/test_autoscan_embeds.py -v
"""
import pytest
from datetime import datetime
from unittest.mock import MagicMock

from bot.utils.embed_builder import (
    build_log_accepted_embed, build_log_rejected_embed,
    build_log_invalid_embed, build_log_name_mismatch_embed,
    build_log_duplicate_embed, SUPPORT_FOOTER,
)
from bot.utils.parser import ParsedDutyLog


def _make_author(display_name: str = "Test User") -> MagicMock:
    """Tạo mock author với display_avatar"""
    a = MagicMock()
    a.display_name = display_name
    a.display_avatar = MagicMock()
    a.display_avatar.url = "https://cdn.discord.com/avatar.png"
    return a


def _make_parsed(username: str = "Nguyễn Văn A", duration: int = 120) -> ParsedDutyLog:
    return ParsedDutyLog(
        username=username,
        duration_minutes=duration,
        started_at=datetime(2026, 5, 1, 8, 0, 0),
        ended_at=datetime(2026, 5, 1, 10, 0, 0),
        raw_text="LOG DUTY ...",
    )


# ─── Footer support ─────────────────────────────────────────────────────────

class TestSupportFooter:
    def test_constant_correct(self):
        assert SUPPORT_FOOTER == "Nếu cần hỗ trợ vui lòng liên hệ ban lãnh đạo"


# ─── build_log_accepted_embed ────────────────────────────────────────────────

class TestAcceptedEmbed:
    def test_basic_structure(self):
        author = _make_author("Test User")
        parsed = _make_parsed()
        embed = build_log_accepted_embed(parsed, author)
        assert "Đã ghi nhận" in embed.title
        assert "Test User" in embed.description

    def test_has_support_footer(self):
        embed = build_log_accepted_embed(_make_parsed(), _make_author())
        assert SUPPORT_FOOTER in (embed.footer.text or "")

    def test_includes_username(self):
        embed = build_log_accepted_embed(_make_parsed("Trần Thị B"), _make_author())
        # Username phải xuất hiện trong fields
        field_values = [f.value for f in embed.fields]
        assert any("Trần Thị B" in v for v in field_values)

    def test_includes_duration(self):
        embed = build_log_accepted_embed(_make_parsed(duration=120), _make_author())
        field_values = [f.value for f in embed.fields]
        assert any("2 giờ" in v or "120" in v for v in field_values)

    def test_thumbnail_set(self):
        """Avatar người gửi được set làm thumbnail"""
        embed = build_log_accepted_embed(_make_parsed(), _make_author())
        assert embed.thumbnail is not None
        assert embed.thumbnail.url == "https://cdn.discord.com/avatar.png"

    def test_username_markdown_escaped(self):
        """Username chứa markdown bold ** phải được escape (discord.utils.escape_markdown escape *,_,~,>,`,\\)"""
        author = _make_author()
        parsed = _make_parsed("**bold_user**")
        embed = build_log_accepted_embed(parsed, author)
        field_values = " ".join(f.value for f in embed.fields)
        # Sau escape, ** phải có backslash trước nó
        assert "\\*\\*bold" in field_values or "**bold_user**" not in field_values


# ─── build_log_rejected_embed ────────────────────────────────────────────────

class TestRejectedEmbed:
    def test_basic_structure(self):
        embed = build_log_rejected_embed(_make_parsed(), "Ca trực bị overlap", _make_author())
        assert "từ chối" in embed.title.lower() or "Từ chối" in embed.title

    def test_has_support_footer(self):
        embed = build_log_rejected_embed(_make_parsed(), "lý do", _make_author())
        assert embed.footer.text == SUPPORT_FOOTER

    def test_reason_in_field(self):
        reason = "Ca trực này chồng lấp với ca trước"
        embed = build_log_rejected_embed(_make_parsed(), reason, _make_author())
        field_values = " ".join(f.value for f in embed.fields)
        assert reason in field_values

    def test_includes_log_info(self):
        embed = build_log_rejected_embed(_make_parsed("Tên A"), "lý do", _make_author())
        field_values = " ".join(f.value for f in embed.fields)
        assert "Tên A" in field_values

    def test_works_with_none_parsed(self):
        """Cho phép parsed=None khi không parse được gì"""
        embed = build_log_rejected_embed(None, "Không parse được", _make_author())
        # Vẫn phải có title + reason + suggestion
        assert embed.title
        field_values = " ".join(f.value for f in embed.fields)
        assert "Không parse được" in field_values

    def test_has_suggestion_field(self):
        embed = build_log_rejected_embed(_make_parsed(), "lý do", _make_author())
        field_names = [f.name for f in embed.fields]
        assert any("gợi ý" in n.lower() or "💡" in n for n in field_names)


# ─── build_log_invalid_embed ────────────────────────────────────────────────

class TestInvalidEmbed:
    def test_basic_structure(self):
        errors = ["Thời gian không khớp"]
        embed = build_log_invalid_embed(errors, _make_author())
        assert "không hợp lệ" in embed.title.lower()

    def test_has_support_footer(self):
        embed = build_log_invalid_embed(["err"], _make_author())
        assert embed.footer.text == SUPPORT_FOOTER

    def test_lists_all_errors(self):
        errors = ["Lỗi 1", "Lỗi 2", "Lỗi 3"]
        embed = build_log_invalid_embed(errors, _make_author())
        field_values = " ".join(f.value for f in embed.fields)
        for err in errors:
            assert err in field_values


# ─── build_log_name_mismatch_embed ──────────────────────────────────────────

class TestNameMismatchEmbed:
    def test_basic_structure(self):
        embed = build_log_name_mismatch_embed("Other Person", _make_author("Real User"))
        assert "Tên không khớp" in embed.title

    def test_has_support_footer(self):
        embed = build_log_name_mismatch_embed("X", _make_author())
        assert embed.footer.text == SUPPORT_FOOTER

    def test_mentions_both_names(self):
        embed = build_log_name_mismatch_embed("Người Khác", _make_author("Tôi"))
        full = embed.description + " ".join(f.value for f in embed.fields)
        assert "Người Khác" in full
        assert "Tôi" in full

    def test_has_strict_rule_field(self):
        embed = build_log_name_mismatch_embed("X", _make_author())
        field_values = " ".join(f.value for f in embed.fields)
        assert "chính mình" in field_values


# ─── build_log_duplicate_embed ──────────────────────────────────────────────

class TestDuplicateEmbed:
    def test_basic_structure(self):
        embed = build_log_duplicate_embed(_make_author("User"))
        assert "đã được ghi nhận" in embed.title.lower() or "🔁" in embed.title

    def test_has_support_footer(self):
        embed = build_log_duplicate_embed(_make_author())
        assert embed.footer.text == SUPPORT_FOOTER

    def test_includes_username(self):
        embed = build_log_duplicate_embed(_make_author("Tên Người"))
        assert "Tên Người" in embed.description
