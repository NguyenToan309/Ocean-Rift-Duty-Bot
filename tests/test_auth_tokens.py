"""
test_auth_tokens.py — Unit test cho JWT token management và OAuth2 state
trong web/routers/auth.py

Kiểm tra:
- create_access_token / create_refresh_token: tạo JWT đúng cấu trúc
- decode_token: validate chữ ký, loại token, kiểm tra blacklist
- _store_oauth_state / _consume_oauth_state: one-time use, TTL 5 phút

Chạy: pytest tests/test_auth_tokens.py -v
"""
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

from jose import jwt

from bot.config import settings
from web.routers.auth import (
    create_access_token,
    create_refresh_token,
    decode_token,
    _store_oauth_state,
    _consume_oauth_state,
    ALGORITHM,
)
from conftest import make_session

# ─── Hằng số test ─────────────────────────────────────────────────────────────

TEST_USER_ID = 123456789012345678
TEST_USERNAME = "testuser"


# ─── create_access_token ──────────────────────────────────────────────────────

class TestCreateAccessToken:
    def test_returns_string(self):
        token = create_access_token(TEST_USER_ID, TEST_USERNAME)
        assert isinstance(token, str)
        assert len(token) > 10

    def test_payload_sub_is_user_id(self):
        token = create_access_token(TEST_USER_ID, TEST_USERNAME)
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        assert payload["sub"] == str(TEST_USER_ID)

    def test_payload_type_is_access(self):
        token = create_access_token(TEST_USER_ID, TEST_USERNAME)
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        assert payload["type"] == "access"

    def test_payload_username_present(self):
        token = create_access_token(TEST_USER_ID, TEST_USERNAME)
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        assert payload["username"] == TEST_USERNAME

    def test_has_jti_field(self):
        """Mỗi token phải có jti (JWT ID) để hỗ trợ blacklist"""
        token = create_access_token(TEST_USER_ID, TEST_USERNAME)
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        assert "jti" in payload
        assert len(payload["jti"]) > 0

    def test_has_exp_field(self):
        token = create_access_token(TEST_USER_ID, TEST_USERNAME)
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        assert "exp" in payload

    def test_two_tokens_have_different_jti(self):
        """Mỗi lần tạo token phải có jti khác nhau"""
        t1 = create_access_token(TEST_USER_ID, TEST_USERNAME)
        t2 = create_access_token(TEST_USER_ID, TEST_USERNAME)
        p1 = jwt.decode(t1, settings.SECRET_KEY, algorithms=[ALGORITHM])
        p2 = jwt.decode(t2, settings.SECRET_KEY, algorithms=[ALGORITHM])
        assert p1["jti"] != p2["jti"]


# ─── create_refresh_token ─────────────────────────────────────────────────────

class TestCreateRefreshToken:
    def test_returns_string(self):
        token = create_refresh_token(TEST_USER_ID)
        assert isinstance(token, str)

    def test_payload_type_is_refresh(self):
        token = create_refresh_token(TEST_USER_ID)
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        assert payload["type"] == "refresh"

    def test_payload_sub_is_user_id(self):
        token = create_refresh_token(TEST_USER_ID)
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        assert payload["sub"] == str(TEST_USER_ID)

    def test_access_and_refresh_different(self):
        """Access token và refresh token không được giống nhau"""
        at = create_access_token(TEST_USER_ID, TEST_USERNAME)
        rt = create_refresh_token(TEST_USER_ID)
        assert at != rt


# ─── decode_token ─────────────────────────────────────────────────────────────

class TestDecodeToken:
    """decode_token() là async — dùng pytest-asyncio"""

    async def test_valid_access_token(self):
        """Token hợp lệ → trả về payload đúng"""
        token = create_access_token(TEST_USER_ID, TEST_USERNAME)
        session = make_session(None)   # blacklist check → None = không bị blacklist
        payload = await decode_token(token, session, expected_type="access")
        assert payload["sub"] == str(TEST_USER_ID)
        assert payload["type"] == "access"

    async def test_valid_refresh_token(self):
        token = create_refresh_token(TEST_USER_ID)
        session = make_session(None)
        payload = await decode_token(token, session, expected_type="refresh")
        assert payload["type"] == "refresh"

    async def test_wrong_type_raises_401(self):
        """Dùng refresh token ở nơi cần access token → 401"""
        from fastapi import HTTPException
        refresh_token = create_refresh_token(TEST_USER_ID)
        session = make_session(None)
        with pytest.raises(HTTPException) as exc_info:
            await decode_token(refresh_token, session, expected_type="access")
        assert exc_info.value.status_code == 401

    async def test_access_token_as_refresh_raises_401(self):
        """Dùng access token ở nơi cần refresh token → 401"""
        from fastapi import HTTPException
        access_token = create_access_token(TEST_USER_ID, TEST_USERNAME)
        session = make_session(None)
        with pytest.raises(HTTPException) as exc_info:
            await decode_token(access_token, session, expected_type="refresh")
        assert exc_info.value.status_code == 401

    async def test_invalid_token_raises_401(self):
        """Chuỗi rác → JWTError → HTTPException 401"""
        from fastapi import HTTPException
        session = make_session(None)
        with pytest.raises(HTTPException) as exc_info:
            await decode_token("this.is.garbage", session, expected_type="access")
        assert exc_info.value.status_code == 401

    async def test_tampered_signature_raises_401(self):
        """Token bị sửa signature → 401"""
        from fastapi import HTTPException
        token = create_access_token(TEST_USER_ID, TEST_USERNAME)
        # Sửa chữ ký: thay phần cuối
        parts = token.split(".")
        tampered = parts[0] + "." + parts[1] + ".invalidsignature"
        session = make_session(None)
        with pytest.raises(HTTPException) as exc_info:
            await decode_token(tampered, session, expected_type="access")
        assert exc_info.value.status_code == 401

    async def test_blacklisted_token_raises_401(self):
        """jti đã bị blacklist → 401"""
        from fastapi import HTTPException
        from unittest.mock import MagicMock
        token = create_access_token(TEST_USER_ID, TEST_USERNAME)
        blacklisted_entry = MagicMock()   # giả lập một bản ghi BlacklistedToken
        session = make_session(blacklisted_entry)   # session trả lại entry → bị blacklist
        with pytest.raises(HTTPException) as exc_info:
            await decode_token(token, session, expected_type="access")
        assert exc_info.value.status_code == 401
        assert "thu hồi" in exc_info.value.detail

    async def test_expired_token_raises_401(self):
        """Token đã hết hạn → JWTError → 401"""
        from fastapi import HTTPException
        # Tạo token đã hết hạn thủ công
        import secrets
        now = datetime.now(timezone.utc)
        payload = {
            "sub": str(TEST_USER_ID),
            "type": "access",
            "username": TEST_USERNAME,
            "exp": now - timedelta(seconds=1),   # hết hạn 1 giây trước
            "jti": secrets.token_hex(16),
        }
        expired_token = jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)
        session = make_session(None)
        with pytest.raises(HTTPException) as exc_info:
            await decode_token(expired_token, session, expected_type="access")
        assert exc_info.value.status_code == 401


# ─── OAuth2 State management ──────────────────────────────────────────────────

class TestOAuthState:
    """OAuth2 state chống CSRF: one-time use, TTL 5 phút"""

    def setup_method(self):
        """Xóa sạch oauth states trước mỗi test để tránh interference"""
        from web.routers.auth import _oauth_states
        _oauth_states.clear()

    def test_store_and_consume_valid(self):
        """Store state → consume → True"""
        _store_oauth_state("test_state_001")
        assert _consume_oauth_state("test_state_001") is True

    def test_consume_once_only(self):
        """State là one-time use — consume lần 2 → False"""
        _store_oauth_state("test_state_002")
        _consume_oauth_state("test_state_002")    # lần 1 → True (ignore result)
        assert _consume_oauth_state("test_state_002") is False  # lần 2

    def test_consume_unknown_state(self):
        """State không tồn tại → False"""
        assert _consume_oauth_state("nonexistent_state") is False

    def test_expired_state_rejected(self):
        """State cũ hơn 5 phút → False"""
        from web.routers.auth import _oauth_states
        from bot.utils.time_utils import utcnow
        old_time = utcnow() - timedelta(seconds=301)  # 5 phút 1 giây trước
        _oauth_states["old_state"] = old_time
        assert _consume_oauth_state("old_state") is False

    def test_fresh_state_within_ttl(self):
        """State 4 phút tuổi → vẫn còn hạn → True"""
        from web.routers.auth import _oauth_states
        from bot.utils.time_utils import utcnow
        fresh_time = utcnow() - timedelta(seconds=240)  # 4 phút trước
        _oauth_states["fresh_state"] = fresh_time
        assert _consume_oauth_state("fresh_state") is True

    def test_store_cleans_expired(self):
        """store() phải dọn sạch các state hết hạn để tránh memory leak"""
        from web.routers.auth import _oauth_states
        from bot.utils.time_utils import utcnow
        # Thêm state hết hạn thủ công
        _oauth_states["expired_1"] = utcnow() - timedelta(seconds=400)
        _oauth_states["expired_2"] = utcnow() - timedelta(seconds=500)
        initial_count = len(_oauth_states)

        # store mới → sẽ trigger cleanup
        _store_oauth_state("new_state_cleanup_test")

        # Sau cleanup, state hết hạn phải bị xóa
        assert "expired_1" not in _oauth_states
        assert "expired_2" not in _oauth_states
        assert "new_state_cleanup_test" in _oauth_states

    def test_multiple_states_independent(self):
        """Nhiều states hoạt động độc lập"""
        _store_oauth_state("state_A")
        _store_oauth_state("state_B")
        _store_oauth_state("state_C")

        assert _consume_oauth_state("state_B") is True
        # state_A và state_C vẫn còn
        assert _consume_oauth_state("state_A") is True
        assert _consume_oauth_state("state_C") is True
        # Consume lần 2 → False
        assert _consume_oauth_state("state_B") is False
