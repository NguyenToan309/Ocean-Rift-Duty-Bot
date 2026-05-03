"""
test_username_match.py — Unit test cho _username_matches_author() và _normalize_name()
trong bot/cogs/log_duty.py

Kiểm tra:
- So sánh tên LOG DUTY vs tên Discord (name, global_name, display_name, nick)
- Quy tắc substring ≥ 4 ký tự (tránh false positive)
- Hỗ trợ tiếng Việt có dấu

Chạy: pytest tests/test_username_match.py -v
"""
import pytest
from unittest.mock import MagicMock

from bot.cogs.log_duty import _username_matches_author, _normalize_name


# ─── Helper: tạo mock author ─────────────────────────────────────────────────

def _make_author(
    name: str = "",
    global_name: str | None = None,
    display_name: str = "",
    nick: str | None = None,
) -> MagicMock:
    """Tạo mock discord.Member/User với các trường tên"""
    author = MagicMock()
    author.name = name
    author.global_name = global_name
    author.display_name = display_name
    author.nick = nick
    return author


# ─── _normalize_name ─────────────────────────────────────────────────────────

class TestNormalizeName:
    """Kiểm tra _normalize_name(): lowercase + bỏ ký tự không phải chữ/số tiếng Việt"""

    def test_none_returns_empty(self):
        assert _normalize_name(None) == ""

    def test_empty_returns_empty(self):
        assert _normalize_name("") == ""

    def test_lowercase(self):
        assert _normalize_name("ABC") == "abc"

    def test_removes_spaces(self):
        assert _normalize_name("Nguyen Van A") == "nguyenvana"

    def test_keeps_vietnamese_chars(self):
        result = _normalize_name("Nguyễn Văn A")
        assert "nguyễn" in result
        assert "văn" in result
        assert "a" in result

    def test_removes_punctuation(self):
        assert _normalize_name("Test-User_123!") == "testuser123"

    def test_keeps_digits(self):
        assert _normalize_name("Player123") == "player123"

    def test_strips_extra_whitespace(self):
        result = _normalize_name("  Tên  User  ")
        # spaces removed
        assert " " not in result
        assert len(result) > 0


# ─── _username_matches_author ─────────────────────────────────────────────────

class TestUsernameMatchesAuthor:
    """Kiểm tra logic so sánh tên trong LOG DUTY vs các trường Discord"""

    # --- Exact match ---

    def test_exact_match_name(self):
        author = _make_author(name="nguyenvana", display_name="Nguyễn Văn A")
        assert _username_matches_author("nguyenvana", author) is True

    def test_exact_match_display_name(self):
        author = _make_author(name="user123", display_name="Nguyễn Văn A")
        assert _username_matches_author("Nguyễn Văn A", author) is True

    def test_exact_match_global_name(self):
        author = _make_author(
            name="user123",
            global_name="Trần Thị B",
            display_name="user123",
        )
        assert _username_matches_author("Trần Thị B", author) is True

    def test_exact_match_nick(self):
        author = _make_author(
            name="user123",
            display_name="user123",
            nick="Anh Tú",
        )
        assert _username_matches_author("Anh Tú", author) is True

    def test_case_insensitive(self):
        """So sánh không phân biệt chữ hoa/thường sau normalize"""
        author = _make_author(display_name="NGUYENVANA")
        assert _username_matches_author("nguyenvana", author) is True

    def test_case_insensitive_vietnamese(self):
        author = _make_author(display_name="Nguyễn Văn A")
        assert _username_matches_author("nguyễn văn a", author) is True

    # --- Substring match (≥ 4 ký tự) ---

    def test_parsed_contains_display_4chars(self):
        """parsed_name chứa ≥ 4 ký tự của display_name → True"""
        # "nguyenvananhtu" chứa "anhtú" (sau normalize)
        author = _make_author(display_name="Nguyễn Văn Anh Tú")
        # parsed là một phần của display_name
        assert _username_matches_author("Anh Tú", author) is True

    def test_display_contains_parsed_4chars(self):
        """display_name chứa ≥ 4 ký tự của parsed_name → True"""
        author = _make_author(display_name="Nguyễn Văn Anh Tú")
        assert _username_matches_author("Nguyễn Văn Anh Tú Đẹp Trai", author) is True

    def test_substring_3chars_rejected(self):
        """Đoạn khớp chỉ 3 ký tự → False (ngăn false positive)"""
        # "abc" in "abcdef" → nhưng len("abc") = 3 < 4 → không match
        author = _make_author(name="abcdef", display_name="abcdef")
        assert _username_matches_author("abc", author) is False

    def test_substring_2chars_rejected(self):
        """'AB' (2 ký tự) không substring-match 'ABCDEF' dù có chứa"""
        # parsed_n = "ab", c_n = "abcdef" → len("ab")=2 < 4 → không dùng substring rule
        # len("abcdef")=6 ≥ 4 nhưng "abcdef" in "ab" → False (chuỗi dài hơn không thể in chuỗi ngắn)
        author = _make_author(name="abcdef", display_name="ABCDEF User")
        assert _username_matches_author("AB", author) is False

    def test_substring_1char_rejected(self):
        """'A' (1 ký tự) không match dù có trong display name"""
        # parsed_n = "a" → không phải exact match với bất kỳ trường nào
        # len("a") < 4 → không dùng substring rule
        author = _make_author(name="playerone", display_name="Admin Along")
        assert _username_matches_author("A", author) is False

    def test_substring_exactly_4chars_accepted(self):
        """Đúng 4 ký tự → True"""
        # parsed = "test", display = "testuser" → "test" in "testuser" AND len("test")=4 → True
        author = _make_author(display_name="testuser")
        assert _username_matches_author("test", author) is True

    # --- No match ---

    def test_completely_different_names(self):
        author = _make_author(
            name="player001",
            global_name="XYZ Player",
            display_name="Dragon Slayer",
            nick=None,
        )
        assert _username_matches_author("Nguyễn Văn A", author) is False

    def test_empty_parsed_name(self):
        author = _make_author(name="testuser", display_name="Test User")
        assert _username_matches_author("", author) is False

    def test_empty_all_discord_names(self):
        """Tất cả trường Discord đều rỗng → False"""
        author = _make_author(name="", global_name=None, display_name="", nick=None)
        assert _username_matches_author("Nguyễn Văn A", author) is False

    def test_none_global_name_ignored(self):
        """global_name=None không gây lỗi"""
        author = _make_author(name="testuser", global_name=None, display_name="Test User")
        assert _username_matches_author("testuser", author) is True

    def test_none_nick_ignored(self):
        """nick=None không gây lỗi"""
        author = _make_author(name="testuser", display_name="Test User", nick=None)
        assert _username_matches_author("testuser", author) is True

    # --- Các trường hợp thực tế ---

    def test_vietnamese_full_name_in_display(self):
        """Tên đầy đủ tiếng Việt trong display_name"""
        author = _make_author(display_name="Nguyễn Thị Lan Anh")
        assert _username_matches_author("Nguyễn Thị Lan Anh", author) is True

    def test_short_name_in_longer_display(self):
        """Tên ngắn "An" nằm trong display_name dài — KHÔNG match vì < 4 ký tự"""
        author = _make_author(display_name="Nguyễn Thanh An")
        # "an" (2 ký tự sau normalize) trong "nguyễnthanhan" → len < 4 → False
        assert _username_matches_author("An", author) is False

    def test_match_via_any_field(self):
        """Chỉ cần khớp MỘT trong 4 trường (name, global, display, nick) là True"""
        author = _make_author(
            name="rawuser",
            global_name="Global Name",
            display_name="Display Name",
            nick="NickName EMS",
        )
        # Chỉ nick khớp
        assert _username_matches_author("NickName EMS", author) is True
