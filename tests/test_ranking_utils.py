"""Test cho utils/ranking_utils.py — mock-based.

Mock pattern: session.execute trả lần lượt các mock Result đã định nghĩa.
Mỗi Result có .all() trả list rows. Mỗi row là MagicMock với các attribute
khớp với SELECT columns (user_id, total_minutes, sessions, ...).
"""
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, AsyncMock

from utils.ranking_utils import (
    aggregate_ranking,
    resolve_display_names,
    resolve_one_display_name,
    RankingRow,
)


def _mock_result(rows):
    res = MagicMock()
    res.all.return_value = rows
    return res


def _make_session_returning(*results):
    """Mock session.execute trả lần lượt các result."""
    session = AsyncMock()
    iterator = iter(results)

    async def execute(*a, **kw):
        return next(iterator)

    session.execute = execute
    return session


START = datetime(2026, 1, 1, tzinfo=timezone.utc)
END = datetime(2026, 12, 31, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_aggregate_ranking_empty():
    session = _make_session_returning(_mock_result([]))
    out = await aggregate_ranking(session, guild_id=1, start=START, end=END)
    assert out == []


@pytest.mark.asyncio
async def test_aggregate_ranking_with_binding():
    agg = MagicMock(user_id=100, total_minutes=300, sessions=5)
    bind = MagicMock(discord_user_id=100, current_ingame_name="Alice")
    session = _make_session_returning(
        _mock_result([agg]),
        _mock_result([bind]),
    )
    out = await aggregate_ranking(session, guild_id=1, start=START, end=END)
    assert len(out) == 1
    assert out[0] == RankingRow(
        user_id=100, display_name="Alice", total_minutes=300, sessions=5
    )


@pytest.mark.asyncio
async def test_aggregate_ranking_fallback_latest_username():
    agg = MagicMock(user_id=200, total_minutes=120, sessions=2)
    name = MagicMock(user_id=200, username="Bob")
    session = _make_session_returning(
        _mock_result([agg]),
        _mock_result([]),  # binding empty
        _mock_result([name]),
    )
    out = await aggregate_ranking(session, guild_id=1, start=START, end=END)
    assert len(out) == 1
    assert out[0].display_name == "Bob"
    assert out[0].total_minutes == 120
    assert out[0].sessions == 2


@pytest.mark.asyncio
async def test_aggregate_ranking_mixed_binding_and_fallback():
    a1 = MagicMock(user_id=10, total_minutes=500, sessions=8)
    a2 = MagicMock(user_id=20, total_minutes=300, sessions=4)
    bind = MagicMock(discord_user_id=10, current_ingame_name="Bound")
    name = MagicMock(user_id=20, username="Latest")
    session = _make_session_returning(
        _mock_result([a1, a2]),
        _mock_result([bind]),  # chỉ user 10
        _mock_result([name]),  # user 20 fallback
    )
    out = await aggregate_ranking(session, guild_id=1, start=START, end=END)
    assert [r.display_name for r in out] == ["Bound", "Latest"]


@pytest.mark.asyncio
async def test_aggregate_ranking_no_display_name_fallback_dash():
    agg = MagicMock(user_id=999, total_minutes=10, sessions=1)
    session = _make_session_returning(
        _mock_result([agg]),
        _mock_result([]),  # no binding
        _mock_result([]),  # no log username
    )
    out = await aggregate_ranking(session, guild_id=1, start=START, end=END)
    assert len(out) == 1
    assert out[0].display_name == "—"


@pytest.mark.asyncio
async def test_resolve_display_names_empty():
    session = AsyncMock()
    out = await resolve_display_names(session, guild_id=1, user_ids=[])
    assert out == {}


@pytest.mark.asyncio
async def test_resolve_display_names_only_binding():
    bind = MagicMock(discord_user_id=42, current_ingame_name="X")
    session = _make_session_returning(_mock_result([bind]))
    out = await resolve_display_names(session, guild_id=1, user_ids=[42])
    assert out == {42: "X"}


@pytest.mark.asyncio
async def test_resolve_display_names_empty_binding_skipped():
    """Binding có current_ingame_name='' → bỏ qua, fallback latest."""
    bind = MagicMock(discord_user_id=42, current_ingame_name="")
    name = MagicMock(user_id=42, username="LatestName")
    session = _make_session_returning(
        _mock_result([bind]),
        _mock_result([name]),
    )
    out = await resolve_display_names(session, guild_id=1, user_ids=[42])
    assert out == {42: "LatestName"}


@pytest.mark.asyncio
async def test_resolve_one_display_name_missing():
    session = _make_session_returning(_mock_result([]), _mock_result([]))
    out = await resolve_one_display_name(session, guild_id=1, user_id=999)
    assert out == "Unknown"


@pytest.mark.asyncio
async def test_resolve_one_display_name_with_binding():
    bind = MagicMock(discord_user_id=777, current_ingame_name="Hero")
    session = _make_session_returning(_mock_result([bind]))
    out = await resolve_one_display_name(session, guild_id=1, user_id=777)
    assert out == "Hero"


@pytest.mark.asyncio
async def test_resolve_display_names_ignores_period_for_stable_identity():
    """Regression: cùng Discord ID không có binding phải trả CÙNG display_name
    khi gọi với period khác nhau — tránh hiện tượng 'Diệp Phong (Gánh Cả Lũ)'
    ở tab Tháng nhưng 'Diệp Phong (CP159864)' ở tab Tất cả.
    """
    from datetime import datetime as _dt, timezone as _tz

    # Call 1 (period Tháng): binding empty, latest username trong period = "X"
    # Call 2 (period Tất cả): binding empty, latest username trong period = "Y"
    # Vì giờ ta KHÔNG filter theo period nữa, cả 2 call phải hỏi cùng 1 query
    # và trả cùng tên. Mock cùng 1 row "Stable" cho cả 2 fallback query.
    session = _make_session_returning(
        _mock_result([]),  # binding empty (call 1)
        _mock_result([MagicMock(user_id=42, username="Stable")]),
        _mock_result([]),  # binding empty (call 2)
        _mock_result([MagicMock(user_id=42, username="Stable")]),
    )
    period1 = (_dt(2026, 6, 1, tzinfo=_tz.utc), _dt(2026, 6, 30, tzinfo=_tz.utc))
    period2 = (_dt(2024, 1, 1, tzinfo=_tz.utc), _dt(2026, 12, 31, tzinfo=_tz.utc))
    out1 = await resolve_display_names(
        session, guild_id=1, user_ids=[42], start=period1[0], end=period1[1],
    )
    out2 = await resolve_display_names(
        session, guild_id=1, user_ids=[42], start=period2[0], end=period2[1],
    )
    assert out1 == {42: "Stable"}
    assert out2 == {42: "Stable"}
    assert out1[42] == out2[42], "Display name phải ổn định cross-period"
