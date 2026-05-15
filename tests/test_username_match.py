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

    # --- STRICT exact match (no substring) ---
    # Sau audit fix: substring match đã bị loại bỏ vì gây lỗ hổng impersonation
    # (kẻ tấn công đặt nick "VT | <victim>" sẽ match qua substring).
    # Giờ chỉ chấp nhận: exact match RAW hoặc exact match SAU KHI strip role tag prefix.

    def test_substring_no_longer_matches(self):
        """parsed_name là substring của display_name → KHÔNG còn match (strict mode)"""
        author = _make_author(display_name="Nguyễn Văn Anh Tú")
        # "Anh Tú" là substring của "Nguyễn Văn Anh Tú" nhưng không phải tên đầy đủ
        assert _username_matches_author("Anh Tú", author) is False

    def test_display_substring_of_parsed_no_longer_matches(self):
        """display_name là substring của parsed_name → cũng KHÔNG còn match"""
        author = _make_author(display_name="Nguyễn Văn Anh Tú")
        assert _username_matches_author("Nguyễn Văn Anh Tú Đẹp Trai", author) is False

    def test_substring_3chars_rejected(self):
        """3 ký tự chứa trong tên → False (như cũ)"""
        author = _make_author(name="abcdef", display_name="abcdef")
        assert _username_matches_author("abc", author) is False

    def test_substring_2chars_rejected(self):
        """2 ký tự chứa trong tên → False"""
        author = _make_author(name="abcdef", display_name="ABCDEF User")
        assert _username_matches_author("AB", author) is False

    def test_substring_1char_rejected(self):
        """1 ký tự không match"""
        author = _make_author(name="playerone", display_name="Admin Along")
        assert _username_matches_author("A", author) is False

    def test_4char_substring_no_longer_accepted(self):
        """parsed 'test' là substring của 'testuser' → KHÔNG còn match (strict mode)"""
        author = _make_author(display_name="testuser")
        assert _username_matches_author("test", author) is False

    # --- Strip role tag prefix (NEW) ---

    def test_strip_pipe_prefix(self):
        """Nick 'VT | Tom Nguyễn' → strip → 'Tom Nguyễn' → match parsed 'Tom Nguyễn'"""
        author = _make_author(display_name="VT | Tom Nguyễn")
        assert _username_matches_author("Tom Nguyễn", author) is True

    def test_strip_bracket_prefix(self):
        """Nick '[EMS] Lan Anh' → strip → 'Lan Anh' → match"""
        author = _make_author(display_name="[EMS] Lan Anh")
        assert _username_matches_author("Lan Anh", author) is True

    def test_strip_paren_prefix(self):
        """Nick '(VT) Hùng' → strip → 'Hùng' → match"""
        author = _make_author(display_name="(VT) Hùng")
        assert _username_matches_author("Hùng", author) is True

    def test_strip_unicode_bracket_prefix(self):
        """Nick '【VT】Hùng' → strip → 'Hùng' → match (Unicode brackets)"""
        author = _make_author(display_name="【VT】Hùng")
        assert _username_matches_author("Hùng", author) is True

    def test_no_strip_for_partial_substring(self):
        """Strip chỉ xử lý prefix tag, không strip tên thật → parsed 'Pháp Danh' không match nick 'VT | xPhápDanh'"""
        author = _make_author(display_name="VT | xPhápDanh")
        assert _username_matches_author("Pháp Danh", author) is False

    def test_homie_org_role_tags(self):
        """Tất cả tag role của tổ chức Homie (TTS, BS, PK, TK, QLBS, TKBS, VP, VT) đều được strip"""
        tags = ["TTS", "BS", "PK", "TK", "QLBS", "TKBS", "VP", "VT"]
        for tag in tags:
            author = _make_author(display_name=f"{tag} | Pháp Danh")
            assert _username_matches_author("Pháp Danh", author) is True, f"tag={tag} không strip được"

    def test_strip_works_both_sides(self):
        """Cả parsed_name VÀ Discord nick đều có thể có prefix tag — match qua strip 2 chiều"""
        # Case 1: parsed có prefix, nick không
        author = _make_author(display_name="Tom Nguyễn")
        assert _username_matches_author("VT | Tom Nguyễn", author) is True
        # Case 2: nick có prefix, parsed không
        author2 = _make_author(display_name="VT | Tom Nguyễn")
        assert _username_matches_author("Tom Nguyễn", author2) is True
        # Case 3: cả 2 đều có prefix khác
        author3 = _make_author(display_name="VT | Tom Nguyễn")
        assert _username_matches_author("BS | Tom Nguyễn", author3) is True

    def test_impersonation_via_long_substring_blocked(self):
        """🚫 ATTACK: kẻ tấn công đặt nick 'VT | Pháp Danh Thích Em' để match parsed 'Pháp Danh Thích Em'.
        Strip prefix 'VT | ' → 'Pháp Danh Thích Em' → ĐÚNG khớp.
        ⚠️ Trường hợp này VẪN match (không thể phân biệt user thật và kẻ giả mạo qua identity).
        Phòng thủ phải dựa vào: (a) iterate guild trong _resolve_name_owner, (b) DB lock username trong _save_duty_log.
        Test này document rằng identity check không đủ một mình.
        """
        author = _make_author(display_name="VT | Pháp Danh Thích Em")
        # match TRUE — vì strip prefix ra "Pháp Danh Thích Em" exact
        # Đây là expected behavior: identity check chỉ là 1 lớp
        assert _username_matches_author("Pháp Danh Thích Em", author) is True

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
