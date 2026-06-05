# Ranking Merge Completion — Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans (inline) to implement task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hoàn thiện việc gộp ranking theo `discord_user_id` ở MỌI nơi (web `/attendance` + export, bot `/top`+`/bottom`+5 panel) và đưa custom date range lên Topbar.

**Architecture:** Tạo helper `utils/ranking_utils.py` chứa 2 hàm — `aggregate_ranking()` (merge by user_id, fallback binding > latest username) và `resolve_display_names()` (batch lookup). Refactor 7 caller sang dùng helper. Frontend thêm chip "Tùy chỉnh" vào Topbar, propagate qua outlet context.

**Tech Stack:** SQLAlchemy 2.0 async, py-cord 2.6, FastAPI, React + TypeScript.

**Spec:** `docs/superpowers/specs/2026-06-06-ranking-merge-and-custom-date-design.md`

---

## File Structure

**Tạo mới:**
- `utils/ranking_utils.py` — helper shared bot+web
- `tests/test_ranking_utils.py` — unit tests cho helper

**Sửa:**
- `web/routers/dashboard.py:143-184` (`/overview` top5) — dùng helper
- `web/routers/dashboard.py:271` (`/attendance`) — merge by user_id, dùng helper resolve_display_names
- `web/routers/dashboard.py:681-758` (`/ranking`) — dùng helper
- `web/routers/export.py:158` — dùng helper aggregate_ranking
- `bot/cogs/ranking.py:47` (`/top`, `/bottom`) — dùng helper
- `bot/cogs/control_panel.py:131,272,343,503` — 4 panel embeds dùng helper
- `homie-medic-dashboard/src/components/layout/Topbar.tsx` — chip "Tùy chỉnh" + popover
- `homie-medic-dashboard/src/components/layout/RootLayout.tsx` — propagate customRange qua outlet
- `homie-medic-dashboard/src/pages/RankingsPage.tsx` — bỏ date input local, dùng outlet customRange
- `homie-medic-dashboard/src/hooks/useApi.ts` — hooks nhận customRange

---

## Task 1 — Helper `utils/ranking_utils.py`

**Files:**
- Create: `utils/ranking_utils.py`
- Test: `tests/test_ranking_utils.py`

- [ ] **Step 1.1: Tạo file helper**

```python
# utils/ranking_utils.py
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
    order: str = "desc",   # "desc" | "asc"
    limit: int | None = None,
    offset: int = 0,
) -> list[RankingRow]:
    """
    Gộp duty_logs theo discord_user_id trong khoảng [start, end].
    Trả về list RankingRow đã có display_name resolved.
    """
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
    Resolve tên hiển thị cho danh sách user_id.

    Ưu tiên: DutyIdentityBinding.current_ingame_name → username của
    log gần nhất trong [start, end] (nếu start/end None thì all-time)
    → None.

    Return dict {user_id: display_name}. Missing user_id không có key.
    """
    if not user_ids:
        return {}

    # Binding (chính thức)
    b_rows = await session.execute(
        select(
            DutyIdentityBinding.discord_user_id,
            DutyIdentityBinding.current_ingame_name,
        )
        .where(DutyIdentityBinding.guild_id == guild_id)
        .where(DutyIdentityBinding.discord_user_id.in_(user_ids))
    )
    binding_map: dict[int, str] = {
        b.discord_user_id: b.current_ingame_name for b in b_rows.all()
    }

    # Fallback: latest log username
    latest_map: dict[int, str] = {}
    missing = [u for u in user_ids if u not in binding_map or not binding_map[u]]
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
```

- [ ] **Step 1.2: Viết test**

Tests dùng mock pattern theo `tests/conftest.py:make_session()` — đảm bảo các SQL được execute đúng số lần và kết quả transform đúng. Không test trực tiếp SQL semantics (cần Postgres thật).

```python
# tests/test_ranking_utils.py
"""Test cho utils/ranking_utils.py — mock-based."""
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, AsyncMock
from utils.ranking_utils import (
    aggregate_ranking, resolve_display_names, resolve_one_display_name, RankingRow,
)


def _mock_result(rows):
    """Tạo mock execute result trả về .all() = rows."""
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


@pytest.mark.asyncio
async def test_aggregate_ranking_empty():
    session = _make_session_returning(_mock_result([]))
    out = await aggregate_ranking(
        session, guild_id=1, start=datetime(2026, 1, 1, tzinfo=timezone.utc),
        end=datetime(2026, 12, 31, tzinfo=timezone.utc),
    )
    assert out == []


@pytest.mark.asyncio
async def test_aggregate_ranking_with_binding():
    # Q1 aggregate → 1 row
    agg_row = MagicMock(user_id=100, total_minutes=300, sessions=5)
    # Q2 binding lookup → 1 binding
    bind_row = MagicMock(discord_user_id=100, current_ingame_name="Alice")
    session = _make_session_returning(
        _mock_result([agg_row]),
        _mock_result([bind_row]),
    )
    out = await aggregate_ranking(
        session, guild_id=1, start=datetime(2026, 1, 1, tzinfo=timezone.utc),
        end=datetime(2026, 12, 31, tzinfo=timezone.utc),
    )
    assert len(out) == 1
    assert out[0] == RankingRow(user_id=100, display_name="Alice", total_minutes=300, sessions=5)


@pytest.mark.asyncio
async def test_aggregate_ranking_fallback_latest_username():
    # User không có binding → fallback latest username
    agg_row = MagicMock(user_id=200, total_minutes=120, sessions=2)
    # Q2 binding → empty
    # Q3 latest username → username "Bob"
    name_row = MagicMock(user_id=200, username="Bob")
    session = _make_session_returning(
        _mock_result([agg_row]),
        _mock_result([]),
        _mock_result([name_row]),
    )
    out = await aggregate_ranking(
        session, guild_id=1, start=datetime(2026, 1, 1, tzinfo=timezone.utc),
        end=datetime(2026, 12, 31, tzinfo=timezone.utc),
    )
    assert len(out) == 1
    assert out[0].display_name == "Bob"


@pytest.mark.asyncio
async def test_resolve_display_names_empty():
    session = AsyncMock()
    out = await resolve_display_names(session, guild_id=1, user_ids=[])
    assert out == {}


@pytest.mark.asyncio
async def test_resolve_one_display_name_missing():
    session = _make_session_returning(_mock_result([]), _mock_result([]))
    out = await resolve_one_display_name(session, guild_id=1, user_id=999)
    assert out == "Unknown"
```

- [ ] **Step 1.3: Chạy test, verify pass**

```bash
pytest tests/test_ranking_utils.py -v --override-ini="addopts="
```
Expected: 5 passed.

- [ ] **Step 1.4: Commit**

```bash
git add utils/ranking_utils.py tests/test_ranking_utils.py
git commit -m "feat(utils): shared ranking_utils helper — aggregate by discord_id + display name resolver"
```

---

## Task 2 — Refactor `web/routers/dashboard.py` `/overview` top5

**Files:** Modify `web/routers/dashboard.py:143-205`

- [ ] **Step 2.1: Thay top5 block bằng helper call**

Tìm block từ comment `# Top 5 — group by user_id only ...` đến `# Batch resolve Discord avatars cho top5` và replace bằng:

```python
    # Top 5 — gộp theo discord_user_id (dùng helper chung)
    from utils.ranking_utils import aggregate_ranking
    top5_rows = await aggregate_ranking(
        session, guild_id=guild_id, start=start, end=end, order="desc", limit=5,
    )
    _top5_uids = {r.user_id for r in top5_rows}

    # Batch resolve Discord avatars cho top5
    from web.utils.discord_resolver import batch_resolve_user_info
    _top5_info = await batch_resolve_user_info(_top5_uids) if _top5_uids else {}
```

Đổi `top5` list comprehension:

```python
        "top5": [
            {
                "user_id": str(r.user_id) if r.user_id else None,
                "username": r.display_name,
                "avatar_url": (_top5_info.get(r.user_id) or {}).get("avatar_url"),
                "total_minutes": r.total_minutes,
                "total_hhmm": minutes_to_hhmm(r.total_minutes),
                "sessions": r.sessions,
            }
            for r in top5_rows
        ],
```

- [ ] **Step 2.2: Smoke import + manual JSON shape check**

```bash
python -X utf8 -c "from web.routers.dashboard import router; print('OK')"
```

- [ ] **Step 2.3: Commit**

```bash
git add web/routers/dashboard.py
git commit -m "refactor(web): /overview top5 dùng ranking_utils.aggregate_ranking"
```

---

## Task 3 — Refactor `web/routers/dashboard.py` `/ranking`

**Files:** Modify `web/routers/dashboard.py:681-770`

- [ ] **Step 3.1: Thay query + name resolution block bằng helper**

Tìm block từ `# Gộp theo discord_user_id duy nhất` đến trước `return {`. Replace bằng:

```python
    from utils.ranking_utils import aggregate_ranking
    rank_rows = await aggregate_ranking(
        session, guild_id=guild_id, start=start, end=end,
        order=order, limit=page_size, offset=offset,
    )
    user_ids_in_page = [r.user_id for r in rank_rows]

    # Batch resolve Discord avatars
    from web.utils.discord_resolver import batch_resolve_user_info
    info_map = await batch_resolve_user_info(set(user_ids_in_page)) if user_ids_in_page else {}
```

Đổi `items` list comp dùng `r.display_name` và `r.total_minutes`/`r.sessions`:

```python
    return {
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "rank": offset + i + 1,
                "user_id": str(r.user_id) if r.user_id else None,
                "username": r.display_name,
                "avatar_url": (info_map.get(r.user_id) or {}).get("avatar_url"),
                "total_minutes": r.total_minutes,
                "total_hhmm": minutes_to_hhmm(r.total_minutes),
                "sessions": r.sessions,
            }
            for i, r in enumerate(rank_rows)
        ],
    }
```

- [ ] **Step 3.2: Smoke import**

```bash
python -X utf8 -c "from web.routers.dashboard import router; print('OK')"
```

- [ ] **Step 3.3: Commit**

```bash
git add web/routers/dashboard.py
git commit -m "refactor(web): /ranking dùng ranking_utils.aggregate_ranking"
```

---

## Task 4 — Fix `/attendance` endpoint

**Files:** Modify `web/routers/dashboard.py:257-274`

- [ ] **Step 4.1: Đổi group_by + resolve display name**

Thay query block tại line ~257-273:

```python
    # Aggregate query: per-user stats. Group by user_id only (gộp các username
    # khác nhau cùng 1 discord user). Resolve display_name qua helper.
    rows = await session.execute(
        select(
            DutyLog.user_id,
            func.count(DutyLog.id).label("session_count"),
            func.coalesce(func.sum(DutyLog.duration_minutes), 0).label("total_minutes"),
            func.max(DutyLog.duration_minutes).label("longest"),
            func.min(DutyLog.duration_minutes).label("shortest"),
            func.min(DutyLog.started_at).label("first_log_at"),
            func.max(DutyLog.started_at).label("last_log_at"),
        )
        .where(DutyLog.guild_id == guild_id)
        .where(DutyLog.user_id.isnot(None))
        .where(DutyLog.started_at >= start)
        .where(DutyLog.started_at <= end)
        .group_by(DutyLog.user_id)
        .order_by(func.sum(DutyLog.duration_minutes).desc())
    )
    log_data = rows.all()

    # Resolve display name qua helper
    from utils.ranking_utils import resolve_display_names
    _att_uids = [r.user_id for r in log_data if r.user_id]
    name_map = await resolve_display_names(
        session, guild_id=guild_id, user_ids=_att_uids, start=start, end=end,
    )
```

- [ ] **Step 4.2: Tìm chỗ format output dùng `r.username` → đổi sang `name_map.get(r.user_id) or "—"`**

Đọc tiếp file đến chỗ build response, thay mọi `r.username` thành `name_map.get(r.user_id) or "—"`.

- [ ] **Step 4.3: Smoke + commit**

```bash
python -X utf8 -c "from web.routers.dashboard import router; print('OK')"
git add web/routers/dashboard.py
git commit -m "fix(web): /attendance gộp theo discord_user_id"
```

---

## Task 5 — Fix `web/routers/export.py`

**Files:** Modify `web/routers/export.py:155-165` (verify range)

- [ ] **Step 5.1: Đọc context export.py**
- [ ] **Step 5.2: Đổi group_by(user_id, username) → group_by(user_id) + resolve display name qua helper**

```python
    from utils.ranking_utils import resolve_display_names
    rows = await session.execute(
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
        .order_by(func.sum(DutyLog.duration_minutes).desc())
    )
    rank_data = rows.all()
    uids = [r.user_id for r in rank_data]
    name_map = await resolve_display_names(
        session, guild_id=guild_id, user_ids=uids, start=start, end=end,
    )
```

Sau đó chỗ build Excel/CSV row dùng `name_map.get(r.user_id) or "—"` thay vì `r.username`.

- [ ] **Step 5.3: Smoke + commit**

```bash
python -X utf8 -c "from web.routers.export import router; print('OK')"
git add web/routers/export.py
git commit -m "fix(web): export ranking gộp theo discord_user_id"
```

---

## Task 6 — Fix `bot/cogs/ranking.py`

**Files:** Modify `bot/cogs/ranking.py:30-80` (around line 47)

- [ ] **Step 6.1: Đọc context bot/cogs/ranking.py**
- [ ] **Step 6.2: Đổi query sang dùng `aggregate_ranking` helper**

Thay logic build embed: dùng `r.display_name` thay vì `r.username`.

- [ ] **Step 6.3: Smoke + commit**

```bash
python -X utf8 -c "from bot.cogs import ranking; print('OK')"
git add bot/cogs/ranking.py
git commit -m "fix(bot): /top /bottom gộp theo discord_user_id"
```

---

## Task 7 — Fix `bot/cogs/control_panel.py` 4 panels

**Files:** Modify `bot/cogs/control_panel.py:131,272,343,503` (4 build_*_embed functions)

- [ ] **Step 7.1: Đọc context — xác định chính xác 4 chỗ**
- [ ] **Step 7.2: Mỗi chỗ thay group_by(user_id, username) → gọi `aggregate_ranking` helper**

Pattern cho mỗi panel:

```python
from utils.ranking_utils import aggregate_ranking
rows = await aggregate_ranking(
    session, guild_id=guild_id, start=start, end=end,
    order="desc", limit=N,
)
# rows[i].user_id, rows[i].display_name, rows[i].total_minutes, rows[i].sessions
```

Chỗ render embed dùng `r.display_name` thay vì `r.username`.

- [ ] **Step 7.3: Smoke + commit**

```bash
python -X utf8 -c "from bot.cogs import control_panel; print('OK')"
git add bot/cogs/control_panel.py
git commit -m "fix(bot): 5 panel embed gộp theo discord_user_id"
```

---

## Task 8 — Frontend Topbar "Tùy chỉnh" chip

**Files:**
- Modify: `homie-medic-dashboard/src/components/layout/Topbar.tsx`
- Modify: `homie-medic-dashboard/src/components/layout/RootLayout.tsx`
- Modify: `homie-medic-dashboard/src/pages/RankingsPage.tsx`
- Modify: `homie-medic-dashboard/src/hooks/useApi.ts`

- [ ] **Step 8.1: Mở rộng `Period` type + thêm `PeriodState`**

```ts
export type Period = 'day' | 'week' | 'month' | 'quarter' | 'custom';

export interface PeriodState {
  period: Period;
  customRange: { from: string; to: string } | null;  // ISO YYYY-MM-DD
}
```

- [ ] **Step 8.2: Topbar: thêm chip "📅 Tùy chỉnh" + popover**

Click chip → popover với 2 `<input type="date">` + nút Áp dụng. Validation: `to >= from`. Áp dụng → set `period='custom'`, `customRange={from,to}`. Click chip khác (day/week/...) → reset `customRange = null`.

- [ ] **Step 8.3: RootLayout propagate PeriodState qua outlet**

`<Outlet context={{ period, customRange }} />`

- [ ] **Step 8.4: useRanking hook nhận customRange**

```ts
export function useRanking(
  guildId: string | null,
  period: string,
  mode: 'top' | 'bottom' = 'top',
  limit = 20,
  customRange?: { from: string; to: string } | null,
) {
  return useAsync<RankingRow[]>(
    () => guildId
      ? api.ranking(guildId, period, mode, limit,
          period === 'custom' ? customRange?.from : undefined,
          period === 'custom' ? customRange?.to : undefined)
      : Promise.resolve([]),
    [guildId, period, mode, limit, customRange?.from, customRange?.to],
  );
}
```

- [ ] **Step 8.5: RankingsPage**

Bỏ 2 input date cục bộ. Dùng `customRange` từ outlet context.

- [ ] **Step 8.6: Build + smoke**

```bash
cd homie-medic-dashboard && npm run build
```
Expected: build success không error TypeScript.

- [ ] **Step 8.7: Commit**

```bash
git add homie-medic-dashboard/src
git commit -m "feat(web): Topbar chip 'Tùy chỉnh' apply global date range"
```

---

## Task 9 — Verification

- [ ] **Step 9.1: Smoke import (full)**

```bash
python -X utf8 -c "
from utils.ranking_utils import aggregate_ranking, resolve_display_names, resolve_one_display_name
from web.routers.dashboard import router as r1
from web.routers.export import router as r2
from bot.cogs import ranking, control_panel
print('All imports OK')
"
```

- [ ] **Step 9.2: Full test suite**

```bash
pytest --override-ini="addopts=" -q
```
Expected: tất cả pass, không regression.

- [ ] **Step 9.3: Grep verify — đảm bảo không còn `group_by(DutyLog.user_id, DutyLog.username)`**

```bash
grep -rn "group_by(DutyLog\.user_id, DutyLog\.username)" --include="*.py"
```
Expected: 0 matches.

- [ ] **Step 9.4: Frontend build clean**

```bash
cd homie-medic-dashboard && npm run build 2>&1 | tail -20
```
Expected: built successfully, không TS error.

- [ ] **Step 9.5: Verification report**

Báo cáo cho user mỗi mục ✅/❌/⚠️:
- Smoke import
- Unit test pass count
- Grep verify
- Frontend build
- Manual integration: chưa làm được nếu không có Discord bot + DB chạy

---

## Risk register

| Risk | Mitigation |
|---|---|
| `aggregate_ranking` SQL chạy chậm vì dùng index khác hơn block cũ | Block cũ đã dùng `func.sum(...)` + `group_by(user_id)` — helper giữ nguyên signature, index `ix_duty_logs_ranking_cover` vẫn áp dụng. |
| Mock test không catch lỗi SQL thực | Tin cậy vào pattern đã proven trong `/api/dashboard/ranking` (đã deploy). Helper giữ EXACT cùng SQL pattern. |
| Frontend breaking change `Period` type | Compile-time check qua TS. Chỉ 1 page (`RankingsPage`) đang dùng `customRange`. |
| Discord bot không restart sau commit | Out of scope — user tự deploy/restart. |
