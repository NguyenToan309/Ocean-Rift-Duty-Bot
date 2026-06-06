"""
admin.py — Endpoint dành cho bot owner: xem danh sách installations + authorizations.

GET  /api/admin/overview         — lấy data đầy đủ (cache 5 phút)
POST /api/admin/overview/refresh — invalidate cache

Cả 2 endpoint require:
- JWT access token hợp lệ
- User.discord_id ∈ settings.BOT_OWNER_IDS

Mọi access ghi AuditLog (ADMIN_OVERVIEW_VIEWED / ADMIN_OVERVIEW_REFRESHED).
"""
from __future__ import annotations
import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select, func, distinct
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings
from bot.utils.time_utils import utcnow
from models.base import get_db
from models.audit_log import AuditLog, AuditAction
from models.duty_log import DutyLog
from models.guild import GuildConfig
from models.user import User
from models.system_setting import (
    SystemSetting,
    DEFAULTS as SYS_DEFAULTS,
    ALLOWED_KEYS as SYS_ALLOWED,
    MAX_VALUE_LENGTH as SYS_MAX_LEN,
)
from web.middleware.auth_guard import require_bot_owner
from web.middleware.rate_limit import limiter
from web.utils.discord_resolver import (
    fetch_bot_guilds_with_counts,
    fetch_guild_detail,
    fetch_guild_bot_member,
    fetch_guild_audit_inviter,
    batch_resolve_user_info,
    invalidate_admin_cache,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin", tags=["admin"])


# ─── Cache global cho response /overview ─────────────────────────────────────
# In-memory dict: {"data": dict, "ts": float}. Single-worker scope.
_OVERVIEW_CACHE: dict[str, Any] = {"data": None, "ts": 0.0}
_OVERVIEW_TTL = 300.0   # 5 phút
_OVERVIEW_LOCK = asyncio.Lock()


def _mask_ip(ip: str | None) -> str | None:
    """Privacy: hiển thị first 3 octet, last octet ẩn → '10.0.0.xxx'.

    Áp dụng cho IPv4. IPv6 thì giữ first 4 group, ẩn còn lại.
    """
    if not ip:
        return None
    if "." in ip and ":" not in ip:
        parts = ip.split(".")
        if len(parts) == 4:
            return f"{parts[0]}.{parts[1]}.{parts[2]}.xxx"
    if ":" in ip:
        parts = ip.split(":")
        head = ":".join(parts[:4])
        return f"{head}:xxxx" if head else ip
    return ip


def _icon_url(guild_id: int, icon_hash: str | None) -> str | None:
    if not icon_hash:
        return None
    ext = "gif" if icon_hash.startswith("a_") else "png"
    return f"https://cdn.discordapp.com/icons/{guild_id}/{icon_hash}.{ext}?size=128"


def _banner_url(guild_id: int, banner_hash: str | None) -> str | None:
    if not banner_hash:
        return None
    ext = "gif" if banner_hash.startswith("a_") else "png"
    return f"https://cdn.discordapp.com/banners/{guild_id}/{banner_hash}.{ext}?size=480"


async def _build_overview(session: AsyncSession) -> dict:
    """Thu thập toàn bộ data: gọi Discord parallel + query DB aggregate."""
    bot_user_id = settings.DISCORD_CLIENT_ID

    # ─── Bước 1: lấy list guild bot đang ở ──
    guilds_raw = await fetch_bot_guilds_with_counts()
    if not guilds_raw:
        # Discord có thể trả [] khi token revoke, 401, 429 — chưa biết. Để callsite xử lý.
        logger.warning("fetch_bot_guilds_with_counts trả empty — token có thể đã revoke?")

    guild_ids = [int(g["id"]) for g in guilds_raw if g.get("id")]

    # ─── Bước 2: parallel ──
    # a. Discord per-guild detail (semaphore 5 để tránh rate limit)
    sem = asyncio.Semaphore(5)

    async def _fetch_one(gid: int) -> dict:
        async with sem:
            detail_task = fetch_guild_detail(gid)
            member_task = fetch_guild_bot_member(gid, bot_user_id)
            inviter_task = fetch_guild_audit_inviter(gid, bot_user_id)
            detail, member, inviter_id = await asyncio.gather(
                detail_task, member_task, inviter_task,
                return_exceptions=True,
            )
            return {
                "guild_id": gid,
                "detail": detail if isinstance(detail, dict) else None,
                "member": member if isinstance(member, dict) else None,
                "inviter_id": inviter_id if isinstance(inviter_id, int) else None,
            }

    # b. DB queries
    async def _db_configs() -> dict[int, GuildConfig]:
        rows = await session.execute(select(GuildConfig))
        return {int(c.guild_id): c for c in rows.scalars().all()}

    async def _db_users() -> list[User]:
        rows = await session.execute(
            select(User).order_by(User.last_login_at.desc().nulls_last())
        )
        return list(rows.scalars().all())

    async def _db_duty_aggregate() -> dict[int, dict]:
        rows = await session.execute(
            select(
                DutyLog.guild_id,
                func.count(DutyLog.id).label("cnt"),
                func.max(DutyLog.created_at).label("last_at"),
                func.count(distinct(DutyLog.user_id)).label("unique_users"),
            ).group_by(DutyLog.guild_id)
        )
        return {
            int(r.guild_id): {
                "cnt": r.cnt or 0,
                "last_at": r.last_at,
                "unique_users": r.unique_users or 0,
            }
            for r in rows.all()
        }

    async def _db_login_aggregate() -> dict[int, dict]:
        rows = await session.execute(
            select(
                AuditLog.user_id,
                func.count(AuditLog.id).label("cnt"),
                func.max(AuditLog.created_at).label("last_at"),
            )
            .where(AuditLog.action == AuditAction.LOGIN_SUCCESS)
            .group_by(AuditLog.user_id)
        )
        return {
            int(r.user_id): {"cnt": r.cnt or 0, "last_at": r.last_at}
            for r in rows.all()
        }

    async def _db_unique_users_global() -> int:
        row = await session.execute(
            select(func.count(distinct(DutyLog.user_id)))
        )
        return int(row.scalar() or 0)

    per_guild, configs, users, duty_agg, login_agg, unique_global = await asyncio.gather(
        asyncio.gather(*[_fetch_one(gid) for gid in guild_ids]) if guild_ids else _empty_list(),
        _db_configs(),
        _db_users(),
        _db_duty_aggregate(),
        _db_login_aggregate(),
        _db_unique_users_global(),
    )

    # ─── Bước 3: Resolve username cho owner + inviter ──
    user_ids_to_resolve: set[int] = set()
    for g in guilds_raw:
        try:
            owner_id = int((g.get("permissions") and g.get("owner")) and 0)  # placeholder
        except Exception:
            pass
    # Lấy owner_id từ detail
    for entry in per_guild:
        detail = entry.get("detail") or {}
        if detail.get("owner_id"):
            try:
                user_ids_to_resolve.add(int(detail["owner_id"]))
            except (TypeError, ValueError):
                pass
        if entry.get("inviter_id"):
            user_ids_to_resolve.add(entry["inviter_id"])
    user_info_map = await batch_resolve_user_info(user_ids_to_resolve)

    # ─── Bước 4: build installations array ──
    installations = []
    per_guild_map = {e["guild_id"]: e for e in per_guild}

    for g in guilds_raw:
        gid = int(g["id"])
        entry = per_guild_map.get(gid, {})
        detail = entry.get("detail") or {}
        member = entry.get("member") or {}
        inviter_id = entry.get("inviter_id")

        owner_id = detail.get("owner_id")
        owner = None
        if owner_id:
            try:
                info = user_info_map.get(int(owner_id))
                owner = {
                    "id": str(owner_id),
                    "username": info.get("global_name") or info.get("username") or "Unknown",
                    "avatar_url": info.get("avatar_url"),
                } if info else {"id": str(owner_id), "username": "Unknown", "avatar_url": None}
            except (TypeError, ValueError):
                pass

        inviter = None
        if inviter_id:
            info = user_info_map.get(inviter_id)
            inviter = {
                "id": str(inviter_id),
                "username": info.get("global_name") or info.get("username") or "Unknown",
            } if info else {"id": str(inviter_id), "username": "Unknown"}

        cfg = configs.get(gid)
        duty_row = duty_agg.get(gid, {"cnt": 0, "last_at": None, "unique_users": 0})

        installations.append({
            "guild_id": str(gid),
            "guild_name": g.get("name") or detail.get("name") or "Unknown",
            "icon_url": _icon_url(gid, g.get("icon") or detail.get("icon")),
            "banner_url": _banner_url(gid, detail.get("banner")),
            "member_count": g.get("approximate_member_count"),
            "presence_count": g.get("approximate_presence_count"),
            "boost_level": detail.get("premium_tier"),
            "boost_count": detail.get("premium_subscription_count"),
            "features": detail.get("features") or [],
            "preferred_locale": detail.get("preferred_locale"),
            "owner": owner,
            "inviter": inviter,
            "bot_joined_at": member.get("joined_at"),
            "bot_permissions": g.get("permissions"),
            "setup_status": "configured" if (cfg and cfg.is_active) else "pending",
            "setup_at": cfg.created_at.isoformat() if cfg and cfg.created_at else None,
            "log_channel_id": str(cfg.log_channel_id) if cfg and cfg.log_channel_id else None,
            "timezone": cfg.timezone if cfg else None,
            "is_active": cfg.is_active if cfg else None,
            "role_map_count": len(cfg.role_map) if cfg and isinstance(cfg.role_map, dict) else 0,
            "duty_log_count": duty_row["cnt"],
            "last_duty_log_at": duty_row["last_at"].isoformat() if duty_row["last_at"] else None,
            "unique_users_logged": duty_row["unique_users"],
        })

    # ─── Bước 5: build authorizations array ──
    authorizations = []
    for u in users:
        login_row = login_agg.get(int(u.discord_id), {"cnt": 0, "last_at": None})
        authorizations.append({
            "discord_id": str(u.discord_id),
            "username": u.username,
            "discriminator": u.discriminator,
            "avatar_url": u.avatar_url,
            "first_login_at": u.created_at.isoformat() if u.created_at else None,
            "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
            "last_login_ip": _mask_ip(u.last_login_ip),
            "is_2fa_enabled": u.is_2fa_enabled,
            "failed_login_attempts": u.failed_login_attempts,
            "locked_until": u.locked_until.isoformat() if u.locked_until else None,
            "total_logins": login_row["cnt"],
            "last_action_at": login_row["last_at"].isoformat() if login_row["last_at"] else None,
        })

    # ─── Bước 6: totals ──
    now_utc = utcnow()
    seven_days_ago = now_utc - timedelta(days=7)
    configured_count = sum(1 for i in installations if i["setup_status"] == "configured")
    with_2fa = sum(1 for a in authorizations if a["is_2fa_enabled"])
    active_7d = sum(
        1 for a in authorizations
        if a["last_login_at"] and datetime.fromisoformat(a["last_login_at"]) >= seven_days_ago
    )
    total_duty = sum(i["duty_log_count"] for i in installations)

    return {
        "installations": installations,
        "authorizations": authorizations,
        "totals": {
            "total_installs": len(installations),
            "configured": configured_count,
            "pending": len(installations) - configured_count,
            "total_authorizations": len(authorizations),
            "with_2fa": with_2fa,
            "active_last_7d": active_7d,
            "total_duty_logs": total_duty,
            "unique_users_global": unique_global,
        },
        "fetched_at": now_utc.isoformat(),
        "cache_hit": False,
    }


async def _empty_list():
    """Trả [] async để asyncio.gather không crash khi không guild nào."""
    return []


@router.get("/overview")
@limiter.limit("10/minute")
async def get_overview(
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_bot_owner),
):
    """Lấy installations + authorizations + totals.

    Cache 5 phút. Header `X-Cache-Stale: true` nếu Discord rate limit và phải
    dùng cached data quá hạn.
    """
    user_id = int(current_user["sub"])
    username = current_user.get("username", f"user_{user_id}")
    ip = request.client.host if request.client else None
    now = time.time()

    # Cache check
    async with _OVERVIEW_LOCK:
        cached_data = _OVERVIEW_CACHE.get("data")
        cached_ts = _OVERVIEW_CACHE.get("ts", 0.0)
        if cached_data and (now - cached_ts) < _OVERVIEW_TTL:
            # Audit ghi mỗi lần xem (dù hit cache vẫn ghi)
            session.add(AuditLog(
                guild_id=None,
                user_id=user_id,
                username=username,
                action=AuditAction.ADMIN_OVERVIEW_VIEWED,
                detail={"cache_hit": True},
                ip_address=ip,
                created_at=utcnow(),
            ))
            await session.commit()
            return {**cached_data, "cache_hit": True}

    # Cache miss: rebuild
    try:
        data = await _build_overview(session)
    except Exception as e:
        logger.error(f"Build overview failed: {type(e).__name__}: {e}", exc_info=True)
        if _OVERVIEW_CACHE.get("data"):
            # Fallback: trả cached cũ + header stale
            response.headers["X-Cache-Stale"] = "true"
            return {**_OVERVIEW_CACHE["data"], "cache_hit": True}
        raise HTTPException(status_code=503, detail="Không thể lấy dữ liệu từ Discord lúc này. Thử lại sau.")

    # Cache mới
    async with _OVERVIEW_LOCK:
        _OVERVIEW_CACHE["data"] = data
        _OVERVIEW_CACHE["ts"] = now

    session.add(AuditLog(
        guild_id=None,
        user_id=user_id,
        username=username,
        action=AuditAction.ADMIN_OVERVIEW_VIEWED,
        detail={"cache_hit": False, "installs": data["totals"]["total_installs"]},
        ip_address=ip,
        created_at=utcnow(),
    ))
    await session.commit()
    return data


@router.get("/system-settings")
@limiter.limit("30/minute")
async def get_system_settings(
    request: Request,
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_bot_owner),
):
    """Trả tất cả setting trong bảng system_settings.

    Key không có trong DB → dùng SYS_DEFAULTS (vd: bảng vừa migrate xong).
    Response shape: {settings: {key: {value, updated_at, updated_by}}}.
    """
    rows = await session.execute(select(SystemSetting))
    db_map = {s.key: s for s in rows.scalars().all()}
    result: dict[str, dict] = {}
    for key in SYS_ALLOWED:
        s = db_map.get(key)
        if s:
            result[key] = {
                "value": s.value,
                "updated_at": s.updated_at.isoformat() if s.updated_at else None,
                "updated_by": str(s.updated_by) if s.updated_by else None,
                "max_length": SYS_MAX_LEN.get(key),
            }
        else:
            result[key] = {
                "value": SYS_DEFAULTS[key],
                "updated_at": None,
                "updated_by": None,
                "max_length": SYS_MAX_LEN.get(key),
            }
    return {"settings": result}


@router.put("/system-settings")
@limiter.limit("10/minute")
async def update_system_settings(
    request: Request,
    payload: dict,
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_bot_owner),
):
    """Cập nhật 1 hoặc nhiều setting. Body: {updates: {key: value}, note: str}.

    Chỉ key thuộc ALLOWED_KEYS mới được lưu (chặn inject). Value length
    được validate theo SYS_MAX_LEN.
    """
    updates_raw = payload.get("updates") or {}
    note = (payload.get("note") or "").strip()
    if not isinstance(updates_raw, dict) or not updates_raw:
        raise HTTPException(status_code=400, detail="Thiếu trường 'updates' (dict).")
    if len(note) < 3:
        raise HTTPException(status_code=400, detail="Phải ghi lý do tối thiểu 3 ký tự.")

    user_id = int(current_user["sub"])
    username = current_user.get("username", f"user_{user_id}")
    ip = request.client.host if request.client else None

    changes: dict[str, dict] = {}
    for key, value in updates_raw.items():
        if key not in SYS_ALLOWED:
            raise HTTPException(status_code=400, detail=f"Key không được phép sửa: {key}")
        if not isinstance(value, str):
            raise HTTPException(status_code=400, detail=f"Value cho {key} phải là string.")
        value = value.strip()
        max_len = SYS_MAX_LEN.get(key, 1000)
        if len(value) == 0:
            raise HTTPException(status_code=400, detail=f"Value {key} không được rỗng.")
        if len(value) > max_len:
            raise HTTPException(
                status_code=400,
                detail=f"Value {key} dài quá {max_len} ký tự.",
            )

        # Upsert
        existing = await session.execute(
            select(SystemSetting).where(SystemSetting.key == key)
        )
        row = existing.scalar_one_or_none()
        if row:
            before = row.value
            row.value = value
            row.updated_by = user_id
            row.updated_at = utcnow()
        else:
            before = None
            row = SystemSetting(
                key=key, value=value, updated_by=user_id, updated_at=utcnow()
            )
            session.add(row)
        changes[key] = {"before": before, "after": value}

    # Audit
    session.add(AuditLog(
        guild_id=None,
        user_id=user_id,
        username=username,
        action=AuditAction.SYSTEM_SETTINGS_UPDATED,
        detail={"changes": changes, "note": note},
        ip_address=ip,
        created_at=utcnow(),
    ))
    await session.commit()

    return {"updated": list(changes.keys()), "changes": changes}


@router.post("/wipe-logs")
@limiter.limit("2/hour")
async def wipe_guild_logs(
    request: Request,
    payload: dict,
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_bot_owner),
):
    """Xoá toàn bộ duty_logs của 1 guild + reset binding.log_count.

    Body: {guild_id: int, confirm_phrase: str}
    confirm_phrase phải khớp "XOA-{guild_id}" (giống bot slash command).

    Quyền: chỉ BOT_OWNER. DUTY_ADMIN của guild KHÔNG dùng được endpoint này.
    """
    from sqlalchemy import delete as sql_delete, update as sql_update
    from models.duty_identity_binding import DutyIdentityBinding

    try:
        guild_id = int(payload.get("guild_id") or 0)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="guild_id phải là số")
    if guild_id <= 0:
        raise HTTPException(status_code=400, detail="guild_id không hợp lệ")

    confirm = (payload.get("confirm_phrase") or "").strip() if isinstance(payload.get("confirm_phrase"), str) else ""
    expected = f"XOA-{guild_id}"
    if confirm != expected:
        raise HTTPException(
            status_code=400,
            detail=f"Phrase xác nhận sai. Phải gõ chính xác: {expected}",
        )

    user_id = int(current_user["sub"])
    username = current_user.get("username", f"user_{user_id}")
    ip = request.client.host if request.client else None

    # Đếm trước khi xoá
    count_row = await session.execute(
        select(func.count(DutyLog.id)).where(DutyLog.guild_id == guild_id)
    )
    log_count = count_row.scalar() or 0
    binding_count_row = await session.execute(
        select(func.count(DutyIdentityBinding.discord_user_id))
        .where(DutyIdentityBinding.guild_id == guild_id)
    )
    binding_count = binding_count_row.scalar() or 0

    # Mass delete
    await session.execute(sql_delete(DutyLog).where(DutyLog.guild_id == guild_id))
    await session.execute(
        sql_update(DutyIdentityBinding)
        .where(DutyIdentityBinding.guild_id == guild_id)
        .values(log_count=0)
    )

    session.add(AuditLog(
        guild_id=guild_id,
        user_id=user_id,
        username=username,
        action=AuditAction.LOG_WIPED,
        detail={
            "deleted_logs": log_count,
            "reset_bindings": binding_count,
            "confirm_phrase": expected,
            "via": "web",
        },
        ip_address=ip,
        created_at=utcnow(),
    ))
    await session.commit()

    return {
        "success": True,
        "deleted_logs": log_count,
        "reset_bindings": binding_count,
        "guild_id": str(guild_id),
    }


@router.post("/overview/refresh")
@limiter.limit("3/minute")
async def refresh_overview(
    request: Request,
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_bot_owner),
):
    """Invalidate cache để force next GET refetch từ Discord."""
    user_id = int(current_user["sub"])
    username = current_user.get("username", f"user_{user_id}")
    ip = request.client.host if request.client else None

    async with _OVERVIEW_LOCK:
        _OVERVIEW_CACHE["data"] = None
        _OVERVIEW_CACHE["ts"] = 0.0
    invalidate_admin_cache()   # xoá cả per-helper cache trong discord_resolver

    session.add(AuditLog(
        guild_id=None,
        user_id=user_id,
        username=username,
        action=AuditAction.ADMIN_OVERVIEW_REFRESHED,
        detail={},
        ip_address=ip,
        created_at=utcnow(),
    ))
    await session.commit()

    return {"refreshed": True, "ts": utcnow().isoformat()}
