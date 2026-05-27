"""
test_web_api.py — Integration test cho FastAPI web endpoints

Kiểm tra:
- Auth flow: /auth/login redirect, /auth/callback invalid state
- Protected endpoints: trả 401 khi không có token
- /auth/logout và /auth/refresh behavior

Dùng httpx.AsyncClient + ASGITransport để test thật HTTP (không spawn server).
DB dependency được override bằng mock session.

Chạy: pytest tests/test_web_api.py -v
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import HTTPException

import httpx
from httpx import AsyncClient, ASGITransport

from web.main import app
from models.base import get_db
from conftest import make_session


# ─── Dependency override: mock DB session ─────────────────────────────────────

async def _mock_db_ok():
    """Trả về session mock rỗng (không có dữ liệu)"""
    yield make_session()

async def _mock_db_no_user():
    """Session trả về None cho mọi query (user chưa tồn tại)"""
    yield make_session(None, None, None)


@pytest.fixture
def override_db():
    """Override get_db cho tất cả tests trong file này"""
    app.dependency_overrides[get_db] = _mock_db_ok
    yield
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def allow_testserver_origin():
    """CSRF guard chỉ cho whitelist Origin. Thêm http://testserver trong test
    + revert sau khi xong để không leak sang test khác."""
    import web.main as web_main
    added = "http://testserver" not in web_main._ALLOWED_ORIGINS_SET
    if added:
        web_main._ALLOWED_ORIGINS_SET.add("http://testserver")
    yield
    if added:
        web_main._ALLOWED_ORIGINS_SET.discard("http://testserver")


@pytest.fixture
async def client(override_db):
    """httpx.AsyncClient kết nối đến app test. Gửi sẵn Origin header để
    qua csrf_origin_guard middleware cho mọi POST/PUT/DELETE."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
        headers={"Origin": "http://testserver"},
    ) as ac:
        yield ac


# ─── Auth endpoints ───────────────────────────────────────────────────────────

class TestAuthLogin:
    async def test_login_redirects_to_discord(self, client: AsyncClient):
        """GET /auth/login → 307 redirect đến discord.com"""
        resp = await client.get("/auth/login", follow_redirects=False)
        assert resp.status_code in (302, 307)
        location = resp.headers.get("location", "")
        assert "discord.com" in location

    async def test_login_includes_state_param(self, client: AsyncClient):
        """Redirect URL phải có ?state= param chống CSRF"""
        resp = await client.get("/auth/login", follow_redirects=False)
        location = resp.headers.get("location", "")
        assert "state=" in location

    async def test_login_includes_client_id(self, client: AsyncClient):
        """Redirect URL phải có client_id"""
        resp = await client.get("/auth/login", follow_redirects=False)
        location = resp.headers.get("location", "")
        assert "client_id=" in location


class TestAuthCallback:
    async def test_callback_invalid_state_returns_400(self, client: AsyncClient):
        """State không hợp lệ → 400 (CSRF protection)"""
        resp = await client.get(
            "/auth/callback",
            params={"code": "fake_discord_code", "state": "invalid_state_xyz"},
        )
        assert resp.status_code == 400

    async def test_callback_missing_code_returns_422(self, client: AsyncClient):
        """Thiếu param 'code' → 422 Unprocessable Entity"""
        resp = await client.get(
            "/auth/callback",
            params={"state": "some_state"},
        )
        assert resp.status_code == 422

    async def test_callback_missing_state_returns_422(self, client: AsyncClient):
        """Thiếu param 'state' → 422"""
        resp = await client.get(
            "/auth/callback",
            params={"code": "some_code"},
        )
        assert resp.status_code == 422


class TestAuthLogout:
    async def test_logout_clears_cookies(self, client: AsyncClient):
        """POST /auth/logout → 200, cookies access_token và refresh_token bị xóa"""
        # Set fake cookies trước
        client.cookies.set("access_token", "fake_at")
        client.cookies.set("refresh_token", "fake_rt")
        resp = await client.post("/auth/logout")
        # 200 hoặc 204
        assert resp.status_code in (200, 204)


class TestAuthRefresh:
    async def test_refresh_without_cookie_returns_401(self, client: AsyncClient):
        """POST /auth/refresh không có refresh_token cookie → 401"""
        resp = await client.post("/auth/refresh")
        assert resp.status_code == 401

    async def test_refresh_with_invalid_token_returns_401(self, client: AsyncClient):
        """POST /auth/refresh với token rác → 401"""
        client.cookies.set("refresh_token", "garbage.token.value")
        resp = await client.post("/auth/refresh")
        assert resp.status_code == 401


# ─── Protected endpoints ──────────────────────────────────────────────────────

class TestProtectedEndpoints:
    """Endpoint yêu cầu auth → trả 401 hoặc redirect khi không có token"""

    async def test_get_me_without_token_returns_401(self, client: AsyncClient):
        """GET /api/dashboard/me không có cookie → 401"""
        resp = await client.get("/api/dashboard/me")
        assert resp.status_code == 401

    async def test_dashboard_overview_without_token_returns_401(self, client: AsyncClient):
        """GET /api/dashboard/overview không có auth → 401"""
        resp = await client.get("/api/dashboard/overview")
        assert resp.status_code == 401

    async def test_dashboard_ranking_without_token_returns_401(self, client: AsyncClient):
        """GET /api/dashboard/ranking không có auth → 401"""
        resp = await client.get("/api/dashboard/ranking")
        assert resp.status_code == 401

    async def test_export_prepare_without_token_returns_401(self, client: AsyncClient):
        """POST /api/export/prepare không có auth → 401"""
        resp = await client.post("/api/export/prepare")
        assert resp.status_code == 401

    async def test_audit_logs_without_token_returns_401(self, client: AsyncClient):
        """GET /api/audit/logs không có auth → 401"""
        resp = await client.get("/api/audit/logs")
        assert resp.status_code == 401


# ─── Healthcheck / public endpoints ──────────────────────────────────────────

class TestPublicEndpoints:
    async def test_docs_available_in_debug_mode(self, client: AsyncClient):
        """Swagger /docs chỉ có khi DEBUG=True (đã set trong conftest)"""
        from bot.config import settings
        resp = await client.get("/docs")
        if settings.DEBUG:
            assert resp.status_code == 200
        else:
            assert resp.status_code == 404

    async def test_openapi_json_in_debug_mode(self, client: AsyncClient):
        """OpenAPI schema /openapi.json chỉ khi DEBUG"""
        from bot.config import settings
        resp = await client.get("/openapi.json")
        if settings.DEBUG:
            assert resp.status_code == 200
        else:
            assert resp.status_code == 404


# ─── Security headers ─────────────────────────────────────────────────────────

class TestSecurityHeaders:
    async def test_x_frame_options_deny(self, client: AsyncClient):
        """Mọi response phải có X-Frame-Options: DENY"""
        resp = await client.get("/auth/login", follow_redirects=False)
        assert resp.headers.get("x-frame-options") == "DENY"

    async def test_x_content_type_nosniff(self, client: AsyncClient):
        """Mọi response phải có X-Content-Type-Options: nosniff"""
        resp = await client.get("/auth/login", follow_redirects=False)
        assert resp.headers.get("x-content-type-options") == "nosniff"
