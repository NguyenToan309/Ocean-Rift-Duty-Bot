"""
ranking_utils.py — Helper gộp ranking theo discord_user_id.

Dùng chung giữa bot (cogs/ranking, cogs/control_panel) và
web (routers/dashboard, routers/export). Đảm bảo cùng 1 logic
ở mọi nơi: gộp các log cùng discord_user_id (kể cả username khác
nhau do đổi character/Steam name), tên hiển thị ưu tiên
DutyIdentityBinding.current_ingame_name, fallback username của log
gần nhất trong period.
"""
from dataclasses import dataclass
from datetime import datetime
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from models.duty_log import DutyLog
from models.duty_identity_binding import DutyIdentityBinding


@dataclass
class RankingRow:
    user_id: int
    display_name: str
    total_minutes: int
    sessions: int


async def aggregate_ranking(
    session: AsyncSession,
    *,
    guild_id: int,
    start: datetime,
    end: datetime,
    order: str = "desc",
    limit: int | None = None,
    offset: int = 0,
) -> list[RankingRow]:
    """Gộp duty_logs theo discord_user_id, trả RankingRow đã resolve display_name."""
    direction = (
        func.sum(DutyLog.duration_minutes).desc()
        if order == "desc"
        else func.sum(DutyLog.duration_minutes).asc()
    )
    q = (
        select(
            DutyLog.user_id,
            func.sum(DutyLog.duration_minutes).label("total_minutes"),
            func.count(DutyLog.id).label("sessions"),
        )
        .where(DutyLog.guild_id == guild_id)
        .where(DutyLog.user_id.isnot(None))
        .where(DutyLog.started_at >= start)
        .where(DutyLog.started_at <= end)
        .group_by(DutyLog.user_id)
        .order_by(direction)
        .offset(offset)
    )
    if limit is not None:
        q = q.limit(limit)

    result = await session.execute(q)
    rows = list(result.all())
    if not rows:
        return []

    user_ids = [r.user_id for r in rows]
    name_map = await resolve_display_names(
        session, guild_id=guild_id, user_ids=user_ids, start=start, end=end
    )
    return [
        RankingRow(
            user_id=r.user_id,
            display_name=name_map.get(r.user_id) or "—",
            total_minutes=int(r.total_minutes or 0),
            sessions=int(r.sessions or 0),
        )
        for r in rows
    ]


async def resolve_display_names(
    session: AsyncSession,
    *,
    guild_id: int,
    user_ids: list[int],
    start: datetime | None = None,
    end: datetime | None = None,
) -> dict[int, str]:
    """
    Ưu tiên DutyIdentityBinding.current_ingame_name, fallback username của
    log gần nhất trong [start, end]. Trả dict {user_id: display_name}.
    """
    if not user_ids:
        return {}

    b_rows = await session.execute(
        select(
            DutyIdentityBinding.discord_user_id,
            DutyIdentityBinding.current_ingame_name,
        )
        .where(DutyIdentityBinding.guild_id == guild_id)
        .where(DutyIdentityBinding.discord_user_id.in_(user_ids))
    )
    binding_map: dict[int, str] = {
        b.discord_user_id: b.current_ingame_name
        for b in b_rows.all()
        if b.current_ingame_name
    }

    latest_map: dict[int, str] = {}
    missing = [u for u in user_ids if u not in binding_map]
    if missing:
        q = (
            select(DutyLog.user_id, DutyLog.username)
            .where(DutyLog.guild_id == guild_id)
            .where(DutyLog.user_id.in_(missing))
        )
        if start is not None:
            q = q.where(DutyLog.started_at >= start)
        if end is not None:
            q = q.where(DutyLog.started_at <= end)
        q = q.order_by(DutyLog.user_id, DutyLog.started_at.desc())
        n_rows = await session.execute(q)
        for r in n_rows.all():
            if r.user_id not in latest_map:
                latest_map[r.user_id] = r.username

    out: dict[int, str] = {}
    for uid in user_ids:
        name = binding_map.get(uid) or latest_map.get(uid)
        if name:
            out[uid] = name
    return out


async def resolve_one_display_name(
    session: AsyncSession,
    *,
    guild_id: int,
    user_id: int,
) -> str:
    """Tiện ích single-user — dùng cho /stats."""
    names = await resolve_display_names(
        session, guild_id=guild_id, user_ids=[user_id]
    )
    return names.get(user_id) or "Unknown"
