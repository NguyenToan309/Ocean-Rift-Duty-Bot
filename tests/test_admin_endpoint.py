"""
test_admin_endpoint.py — Test cho web/routers/admin.py (bot owner overview).

Coverage: 15 test case theo spec docs/superpowers/specs/2026-05-28-admin-overview-design.md

Chạy: pytest tests/test_admin_endpoint.py -v
"""
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import AsyncClient, ASGITransport
from jose import jwt

from web.main import app
from models.base import get_db
from bot.config import settings
from conftest import make_session


ALGORITHM = "HS256"
OWNER_ID = 111111111111111111
NON_OWNER_ID = 222222222222222222


def _make_access_token(user_id: int) -> str:
    """Tạo JWT access token hợp lệ cho test."""
    payload = {
        "sub": str(user_id),
        "username": f"user_{user_id}",
        "type": "access",
        "jti": f"test_jti_{user_id}",
        "exp": datetime.now(timezone.utc) + timedelta(minutes=15),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


async def _mock_db():
    """DB session trả về None cho mọi query (không có user/log)."""
    yield make_session()


@pytest.fixture
def override_db():
    app.dependency_overrides[get_db] = _mock_db
    yield
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def allow_testserver_origin():
    """CSRF guard cần Origin whitelist — autouse cho mọi test file."""
    import web.main as web_main
    added = "http://testserver" not in web_main._ALLOWED_ORIGINS_SET
    if added:
        web_main._ALLOWED_ORIGINS_SET.add("http://testserver")
    yield
    if added:
        web_main._ALLOWED_ORIGINS_SET.discard("http://testserver")


@pytest.fixture(autouse=True)
def reset_overview_cache():
    """Xoá cache giữa các test để không leak state."""
    from web.routers import admin
    admin._OVERVIEW_CACHE["data"] = None
    admin._OVERVIEW_CACHE["ts"] = 0.0
    yield
    admin._OVERVIEW_CACHE["data"] = None
    admin._OVERVIEW_CACHE["ts"] = 0.0


@pytest.fixture
async def client(override_db):
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
        headers={"Origin": "http://testserver"},
    ) as ac:
        yield ac


@pytest.fixture
def owner_in_settings(monkeypatch):
    """Set BOT_OWNER_IDS = {OWNER_ID} cho test."""
    monkeypatch.setattr(settings, "BOT_OWNER_IDS", {OWNER_ID})


@pytest.fixture
def no_owner_in_settings(monkeypatch):
    """BOT_OWNER_IDS rỗng — test config error path."""
    monkeypatch.setattr(settings, "BOT_OWNER_IDS", set())


# ─── 1. Parse BOT_OWNER_IDS edge cases ──────────────────────────────────────

class TestParseBotOwnerIds:
    def test_empty_string(self):
        from bot.config import _parse_bot_owner_ids
        assert _parse_bot_owner_ids("") == set()

    def test_none_safe(self):
        from bot.config import _parse_bot_owner_ids
        assert _parse_bot_owner_ids("   ") == set()

    def test_single_value(self):
        from bot.config import _parse_bot_owner_ids
        assert _parse_bot_owner_ids("123") == {123}

    def test_multi_values_with_spaces(self):
        from bot.config import _parse_bot_owner_ids
        assert _parse_bot_owner_ids(" 1 , 2 , 3 ") == {1, 2, 3}

    def test_skip_empty_between_commas(self):
        from bot.config import _parse_bot_owner_ids
        # "1,,2" → bỏ giữa
        assert _parse_bot_owner_ids("1,,2") == {1, 2}

    def test_skip_non_int(self):
        from bot.config import _parse_bot_owner_ids
        # "abc,123" → skip abc, warning
        assert _parse_bot_owner_ids("abc,123") == {123}

    def test_trailing_comma(self):
        from bot.config import _parse_bot_owner_ids
        assert _parse_bot_owner_ids("1,2,") == {1, 2}


# ─── 2. require_bot_owner dependency ────────────────────────────────────────

class TestRequireBotOwner:
    async def test_no_config_returns_500(self, client, no_owner_in_settings):
        """BOT_OWNER_IDS empty → 500 config error"""
        token = _make_access_token(OWNER_ID)
        client.cookies.set("access_token", token)
        resp = await client.get("/api/admin/overview")
        assert resp.status_code == 500

    async def test_not_in_list_returns_403(self, client, owner_in_settings):
        """User khác bot owner → 403"""
        token = _make_access_token(NON_OWNER_ID)
        client.cookies.set("access_token", token)
        resp = await client.get("/api/admin/overview")
        assert resp.status_code == 403
        assert "bot owner" in resp.json()["detail"].lower()

    async def test_no_token_returns_401(self, client, owner_in_settings):
        """Không có cookie → 401"""
        resp = await client.get("/api/admin/overview")
        assert resp.status_code == 401


# ─── 3. /api/auth/me trả is_bot_owner ───────────────────────────────────────

class TestIsBotOwnerInMe:
    async def test_owner_returns_true(self, client, owner_in_settings):
        token = _make_access_token(OWNER_ID)
        client.cookies.set("access_token", token)
        resp = await client.get("/api/dashboard/me")
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_bot_owner"] is True
        assert data["user_id"] == str(OWNER_ID)

    async def test_non_owner_returns_false(self, client, owner_in_settings):
        token = _make_access_token(NON_OWNER_ID)
        client.cookies.set("access_token", token)
        resp = await client.get("/api/dashboard/me")
        assert resp.status_code == 200
        assert resp.json()["is_bot_owner"] is False


# ─── 4. Overview happy path + error paths ───────────────────────────────────

@pytest.fixture
def mock_discord_helpers(monkeypatch):
    """Mock tất cả Discord API call → trả data giả."""
    async def fake_guilds(*a, **kw):
        return [{
            "id": "1001", "name": "Test Guild", "icon": None,
            "owner": False, "permissions": "8",
            "approximate_member_count": 100,
            "approximate_presence_count": 10,
        }]

    async def fake_detail(gid, *a, **kw):
        return {
            "id": str(gid), "name": "Test Guild",
            "owner_id": "999", "features": ["COMMUNITY"],
            "premium_tier": 0, "premium_subscription_count": 0,
            "preferred_locale": "vi", "banner": None, "icon": None,
        }

    async def fake_member(gid, bid, *a, **kw):
        return {"joined_at": "2026-04-01T10:00:00Z"}

    async def fake_inviter(gid, bid, *a, **kw):
        return 999

    async def fake_resolve(uids, *a, **kw):
        return {uid: {
            "user_id": str(uid), "username": f"u{uid}",
            "global_name": f"User {uid}", "avatar_url": None,
        } for uid in uids}

    import web.routers.admin as admin_mod
    monkeypatch.setattr(admin_mod, "fetch_bot_guilds_with_counts", fake_guilds)
    monkeypatch.setattr(admin_mod, "fetch_guild_detail", fake_detail)
    monkeypatch.setattr(admin_mod, "fetch_guild_bot_member", fake_member)
    monkeypatch.setattr(admin_mod, "fetch_guild_audit_inviter", fake_inviter)
    monkeypatch.setattr(admin_mod, "batch_resolve_user_info", fake_resolve)


class TestOverview:
    async def test_happy_path(self, client, owner_in_settings, mock_discord_helpers):
        token = _make_access_token(OWNER_ID)
        client.cookies.set("access_token", token)
        resp = await client.get("/api/admin/overview")
        assert resp.status_code == 200
        data = resp.json()
        assert "installations" in data
        assert "authorizations" in data
        assert "totals" in data
        assert data["totals"]["total_installs"] == 1
        assert data["installations"][0]["guild_name"] == "Test Guild"
        assert data["installations"][0]["owner"]["id"] == "999"
        assert data["cache_hit"] is False

    async def test_cache_hit_second_call(self, client, owner_in_settings, mock_discord_helpers):
        token = _make_access_token(OWNER_ID)
        client.cookies.set("access_token", token)
        r1 = await client.get("/api/admin/overview")
        assert r1.status_code == 200
        assert r1.json()["cache_hit"] is False
        r2 = await client.get("/api/admin/overview")
        assert r2.status_code == 200
        assert r2.json()["cache_hit"] is True

    async def test_audit_inviter_null_fallback(
        self, client, owner_in_settings, monkeypatch, mock_discord_helpers
    ):
        """Discord 403 audit log → inviter=null nhưng overview vẫn 200."""
        async def fake_inviter_403(gid, bid, *a, **kw):
            return None
        import web.routers.admin as admin_mod
        monkeypatch.setattr(admin_mod, "fetch_guild_audit_inviter", fake_inviter_403)
        token = _make_access_token(OWNER_ID)
        client.cookies.set("access_token", token)
        resp = await client.get("/api/admin/overview")
        assert resp.status_code == 200
        assert resp.json()["installations"][0]["inviter"] is None

    async def test_empty_guilds(self, client, owner_in_settings, monkeypatch):
        """Bot chưa add vào guild nào hoặc Discord token revoke → installations=[]."""
        async def empty(*a, **kw):
            return []
        async def empty_resolve(uids, *a, **kw):
            return {}
        import web.routers.admin as admin_mod
        monkeypatch.setattr(admin_mod, "fetch_bot_guilds_with_counts", empty)
        monkeypatch.setattr(admin_mod, "batch_resolve_user_info", empty_resolve)
        token = _make_access_token(OWNER_ID)
        client.cookies.set("access_token", token)
        resp = await client.get("/api/admin/overview")
        assert resp.status_code == 200
        data = resp.json()
        assert data["installations"] == []
        assert data["totals"]["total_installs"] == 0


# ─── 5. Refresh endpoint ────────────────────────────────────────────────────

class TestRefresh:
    async def test_refresh_invalidates(self, client, owner_in_settings, mock_discord_helpers):
        """POST refresh → next GET miss cache."""
        token = _make_access_token(OWNER_ID)
        client.cookies.set("access_token", token)
        # GET lần đầu → fill cache
        r1 = await client.get("/api/admin/overview")
        assert r1.json()["cache_hit"] is False
        # GET lần 2 → cache hit
        r2 = await client.get("/api/admin/overview")
        assert r2.json()["cache_hit"] is True
        # POST refresh
        r3 = await client.post("/api/admin/overview/refresh")
        assert r3.status_code == 200
        assert r3.json()["refreshed"] is True
        # GET lần 3 → cache miss lại
        r4 = await client.get("/api/admin/overview")
        assert r4.json()["cache_hit"] is False

    async def test_refresh_non_owner_403(self, client, owner_in_settings):
        """Non-owner gọi /refresh → 403."""
        token = _make_access_token(NON_OWNER_ID)
        client.cookies.set("access_token", token)
        resp = await client.post("/api/admin/overview/refresh")
        assert resp.status_code == 403
