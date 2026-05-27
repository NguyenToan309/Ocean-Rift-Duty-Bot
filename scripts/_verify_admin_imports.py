"""
Smoke test cho feature Admin Overview — verify import + cấu trúc app.
Goi tu scripts/verify_admin_feature.ps1.
"""
import os
import sys

# Them project root vao sys.path de import duoc bot/, web/, models/
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def main() -> int:
    from web.main import app
    from web.routers.admin import router as admin_router  # noqa: F401
    from web.middleware.auth_guard import require_bot_owner, is_bot_owner  # noqa: F401
    from web.utils.discord_resolver import (
        fetch_bot_guilds_with_counts,
        fetch_guild_detail,
        fetch_guild_bot_member,
        fetch_guild_audit_inviter,
        invalidate_admin_cache,
    )  # noqa: F401
    from bot.config import settings, _parse_bot_owner_ids
    from models.audit_log import AuditAction

    assert hasattr(AuditAction, "ADMIN_OVERVIEW_VIEWED"), "Missing AuditAction.ADMIN_OVERVIEW_VIEWED"
    assert hasattr(AuditAction, "ADMIN_OVERVIEW_REFRESHED"), "Missing AuditAction.ADMIN_OVERVIEW_REFRESHED"

    parsed = _parse_bot_owner_ids("1, 2, abc, 3,")
    assert parsed == {1, 2, 3}, f"Parse fail: {parsed}"
    assert _parse_bot_owner_ids("") == set()

    admin_paths = sorted(str(r.path) for r in app.routes if "/admin" in str(r.path))
    assert "/api/admin/overview" in admin_paths, f"Missing /api/admin/overview: {admin_paths}"
    assert "/api/admin/overview/refresh" in admin_paths, f"Missing /refresh: {admin_paths}"

    print(f"  Routes: {len(app.routes)}")
    print(f"  Admin endpoints: {admin_paths}")
    print(f"  BOT_OWNER_IDS: {settings.BOT_OWNER_IDS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
