"""
discord_resolver.py — Resolve Discord channel_id / role_id / user_id sang tên
qua Discord REST API (dùng bot token). In-memory cache với TTL.

Audit log thường lưu raw ID (số 18 chữ số). Frontend cần tên người để dễ đọc.
"""
from __future__ import annotations
import time
import logging
import asyncio
from typing import Optional

import aiohttp

from bot.config import settings
from models.base import AsyncSessionLocal
from models.duty_log import DutyLog
from models.guild import GuildConfig
from sqlalchemy import select, distinct

logger = logging.getLogger(__name__)

# Cache TTL: 10 phút (channel/role name hiếm khi đổi)
TTL_SEC = 600

# {(type, id): (name, expires_at_ts)}
_cache: dict[tuple[str, int], tuple[Optional[str], float]] = {}
_lock = asyncio.Lock()


async def _discord_get(path: str) -> Optional[dict]:
    """GET https://discord.com/api/v10/<path> với bot token. Trả None khi fail."""
    token = settings.DISCORD_BOT_TOKEN
    if not token:
        return None
    url = f"https://discord.com/api/v10/{path.lstrip('/')}"
    try:
        async with aiohttp.ClientSession() as sess:
            async with sess.get(
                url,
                headers={"Authorization": f"Bot {token}"},
                timeout=aiohttp.ClientTimeout(total=3),
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
                logger.debug(f"Discord API {resp.status} for {path}")
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        logger.debug(f"Discord API error for {path}: {e}")
    return None


async def resolve_channel_name(channel_id: int) -> Optional[str]:
    """Lookup channel name. Trả `#channel-name` hoặc None."""
    key = ("channel", channel_id)
    now = time.time()
    async with _lock:
        cached = _cache.get(key)
        if cached and cached[1] > now:
            return cached[0]
    data = await _discord_get(f"channels/{channel_id}")
    name = f"#{data['name']}" if data and data.get("name") else None
    async with _lock:
        _cache[key] = (name, now + TTL_SEC)
    return name


async def resolve_role_name(guild_id: int, role_id: int) -> Optional[str]:
    """Lookup role name. Trả `@role-name` hoặc None."""
    key = ("role", role_id)
    now = time.time()
    async with _lock:
        cached = _cache.get(key)
        if cached and cached[1] > now:
            return cached[0]
    # Discord API: GET /guilds/{guild_id}/roles — trả mảng, cache nguyên server roles
    data = await _discord_get(f"guilds/{guild_id}/roles")
    found: Optional[str] = None
    if isinstance(data, list):
        async with _lock:
            for r in data:
                rid = int(r.get("id", 0))
                rname = f"@{r['name']}" if r.get("name") else None
                _cache[("role", rid)] = (rname, now + TTL_SEC)
                if rid == role_id:
                    found = rname
    async with _lock:
        if key not in _cache:
            _cache[key] = (None, now + TTL_SEC)
        if found is None:
            found = _cache[key][0]
    return found


async def batch_resolve_usernames(user_ids: set[int]) -> dict[int, str]:
    """Lookup username từ duty_logs (lấy log gần nhất). Trả {uid: username}."""
    if not user_ids:
        return {}
    async with AsyncSessionLocal() as session:
        # Lấy username gần nhất cho mỗi user_id
        rows = await session.execute(
            select(DutyLog.user_id, DutyLog.username)
            .where(DutyLog.user_id.in_(user_ids))
            .order_by(DutyLog.user_id, DutyLog.id.desc())
        )
        cache: dict[int, str] = {}
        for uid, name in rows.all():
            if uid not in cache:    # giữ row đầu tiên (newest do order desc)
                cache[uid] = name
    return cache


async def resolve_user_info(user_id: int) -> Optional[dict]:
    """
    Fetch global user info từ Discord API: {username, avatar_url, global_name}.

    Cache TTL = 10 phút. Trả None nếu lỗi.
    URL avatar: https://cdn.discordapp.com/avatars/{user_id}/{hash}.png (size 128)
    Nếu user chưa có avatar custom, fallback default embed avatar.
    """
    key = ("user_info", user_id)
    now = time.time()
    async with _lock:
        cached = _cache.get(key)
        if cached and cached[1] > now:
            return cached[0]   # type: ignore

    data = await _discord_get(f"users/{user_id}")
    result: Optional[dict] = None
    if data:
        username = data.get("username") or ""
        global_name = data.get("global_name") or username
        avatar_hash = data.get("avatar")
        if avatar_hash:
            ext = "gif" if avatar_hash.startswith("a_") else "png"
            avatar_url = f"https://cdn.discordapp.com/avatars/{user_id}/{avatar_hash}.{ext}?size=128"
        else:
            # Default avatar (5 hoặc 6 trong index)
            try:
                idx = (user_id >> 22) % 6
            except Exception:
                idx = 0
            avatar_url = f"https://cdn.discordapp.com/embed/avatars/{idx}.png"
        result = {
            "user_id": str(user_id),
            "username": username,
            "global_name": global_name,
            "avatar_url": avatar_url,
        }

    async with _lock:
        _cache[key] = (result, now + TTL_SEC)
    return result


async def batch_resolve_user_info(user_ids: set[int]) -> dict[int, dict]:
    """Batch resolve user info qua asyncio.gather. Trả {uid: {username, avatar_url, ...}}."""
    if not user_ids:
        return {}
    coros = [resolve_user_info(uid) for uid in user_ids]
    results = await asyncio.gather(*coros, return_exceptions=True)
    out: dict[int, dict] = {}
    for uid, r in zip(user_ids, results):
        if isinstance(r, dict):
            out[uid] = r
    return out


# ─── Admin overview helpers ──────────────────────────────────────────────────
# Mỗi helper có cache riêng (key prefix theo type) để partial refresh hiệu quả.
# TTL 300s (5 phút) — match cache global của /api/admin/overview.

_ADMIN_TTL = 300.0


async def fetch_bot_guilds_with_counts() -> list[dict]:
    """GET /users/@me/guilds?with_counts=true.

    Trả list[{id, name, icon, owner, permissions, approximate_member_count,
    approximate_presence_count}]. Discord cap 200 guild/call (đủ cho hầu hết bot
    nhỏ-vừa). Cache 5 phút.

    Trả [] nếu Discord 401/429/timeout — caller xử lý.
    """
    key = ("admin_bot_guilds", 0)
    now = time.time()
    async with _lock:
        cached = _cache.get(key)
        if cached and cached[1] > now:
            return cached[0] or []   # type: ignore
    data = await _discord_get("users/@me/guilds?with_counts=true")
    result = data if isinstance(data, list) else []
    async with _lock:
        _cache[key] = (result, now + _ADMIN_TTL)
    return result


async def fetch_guild_detail(guild_id: int) -> Optional[dict]:
    """GET /guilds/{id} — chi tiết guild: features, banner, boost_level, locale.

    Cache 5 phút. Trả None nếu fail (bot không in guild, 403, timeout).
    """
    key = ("admin_guild_detail", guild_id)
    now = time.time()
    async with _lock:
        cached = _cache.get(key)
        if cached and cached[1] > now:
            return cached[0]   # type: ignore
    data = await _discord_get(f"guilds/{guild_id}")
    async with _lock:
        _cache[key] = (data, now + _ADMIN_TTL)
    return data


async def fetch_guild_bot_member(guild_id: int, bot_user_id: int) -> Optional[dict]:
    """GET /guilds/{guild_id}/members/{bot_user_id} → {joined_at, roles, nick}.

    Cache 5 phút. Trả None nếu bot thiếu perm hoặc API fail.
    """
    key = ("admin_bot_member", guild_id)
    now = time.time()
    async with _lock:
        cached = _cache.get(key)
        if cached and cached[1] > now:
            return cached[0]   # type: ignore
    data = await _discord_get(f"guilds/{guild_id}/members/{bot_user_id}")
    async with _lock:
        _cache[key] = (data, now + _ADMIN_TTL)
    return data


async def fetch_guild_audit_inviter(guild_id: int, bot_user_id: int) -> Optional[int]:
    """Tìm user đã add bot vào guild qua audit log.

    Strategy: GET /guilds/{id}/audit-logs?action_type=28&limit=10
    (action_type 28 = BOT_ADD). Filter target_id == bot_user_id.

    Trả discord_id của inviter (int), hoặc None nếu:
    - Bot thiếu VIEW_AUDIT_LOG (Discord 403)
    - Audit log entry expire (>90 ngày)
    - Bot được add trước khi entry log được Discord ghi
    """
    key = ("admin_audit_inviter", guild_id)
    now = time.time()
    async with _lock:
        cached = _cache.get(key)
        if cached and cached[1] > now:
            return cached[0]   # type: ignore
    data = await _discord_get(f"guilds/{guild_id}/audit-logs?action_type=28&limit=10")
    inviter_id: Optional[int] = None
    if isinstance(data, dict):
        entries = data.get("audit_log_entries") or []
        for entry in entries:
            target = entry.get("target_id")
            if str(target) == str(bot_user_id):
                try:
                    inviter_id = int(entry.get("user_id"))
                    break
                except (TypeError, ValueError):
                    continue
    async with _lock:
        _cache[key] = (inviter_id, now + _ADMIN_TTL)
    return inviter_id


def invalidate_admin_cache() -> None:
    """Xoá toàn bộ cache admin overview để force refresh từ Discord.

    Áp dụng cho key prefix: admin_bot_guilds, admin_guild_detail,
    admin_bot_member, admin_audit_inviter.
    """
    prefixes = {"admin_bot_guilds", "admin_guild_detail", "admin_bot_member", "admin_audit_inviter"}
    for k in list(_cache.keys()):
        if k[0] in prefixes:
            _cache.pop(k, None)


async def enrich_audit_details(
    guild_id: int,
    items: list[dict],
) -> dict[str, dict]:
    """
    Scan items[*].detail JSON cho mọi 15-19 digit ID → resolve tên.
    Trả về map `{id_str: {"type": "user"|"channel"|"role", "name": str}}`.

    Nguyên tắc nhận diện:
      - Field name kết thúc `_user`, `user_id`, `target_user`, `by_user`, `for_user` → user_id
      - Field name kết thúc `channel_id`, hoặc `field` value là `*channel_id*` → channel
      - Field name kết thúc `role_id`, hoặc `field` value là `*role_id*` → role
    """
    user_ids: set[int] = set()
    channel_ids: set[int] = set()
    role_ids: set[int] = set()

    user_keys = {"user_id", "for_user", "by_user", "target_user"}
    channel_keys = {"channel_id"}
    role_keys = {"role_id"}

    for it in items:
        detail = it.get("detail") or {}
        if not isinstance(detail, dict):
            continue

        # 1. Actor user_id (top-level)
        if "user_id" not in detail and it.get("user_id"):
            try:
                user_ids.add(int(it["user_id"]))
            except (TypeError, ValueError):
                pass

        # 2. Detail fields — nhận diện theo key name
        for k, v in detail.items():
            try:
                if isinstance(v, (str, int)) and str(v).isdigit() and 15 <= len(str(v)) <= 20:
                    n = int(v)
                    if k in user_keys:
                        user_ids.add(n)
                    elif k in channel_keys:
                        channel_ids.add(n)
                    elif k in role_keys:
                        role_ids.add(n)
                    elif k == "field":
                        # Trường hợp CHANGE_CHANNEL_CONFIG: detail={"field": "leave_channel_id", "channel_id": ...}
                        pass  # đã handled ở channel_keys
                # field value như "leave_channel_id" gợi ý là channel
                if k == "field" and isinstance(v, str):
                    if "channel" in v:
                        # bonus: nếu cùng row có channel_id, add
                        c = detail.get("channel_id")
                        if isinstance(c, (str, int)) and str(c).isdigit():
                            channel_ids.add(int(c))
                    if "role" in v:
                        r = detail.get("role_id") or detail.get("value")
                        if isinstance(r, (str, int)) and str(r).isdigit():
                            role_ids.add(int(r))
            except (ValueError, TypeError):
                continue

    # Cũng lookup actor IDs (item.user_id) — show tên người thực hiện thay vì raw
    for it in items:
        try:
            if it.get("user_id"):
                user_ids.add(int(it["user_id"]))
        except (TypeError, ValueError):
            pass

    # Batch resolve usernames từ DB
    usernames = await batch_resolve_usernames(user_ids)

    # Resolve channel/role names song song qua Discord API
    resolved: dict[str, dict] = {}

    for uid, name in usernames.items():
        resolved[str(uid)] = {"type": "user", "name": name}

    # Concurrent channel/role lookups (max ~10 cùng lúc)
    sem = asyncio.Semaphore(8)

    async def _ch(cid: int):
        async with sem:
            name = await resolve_channel_name(cid)
            if name:
                resolved[str(cid)] = {"type": "channel", "name": name}

    async def _r(rid: int):
        async with sem:
            name = await resolve_role_name(guild_id, rid)
            if name:
                resolved[str(rid)] = {"type": "role", "name": name}

    tasks = [_ch(c) for c in channel_ids if str(c) not in resolved]
    tasks += [_r(r) for r in role_ids if str(r) not in resolved]
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)

    return resolved
