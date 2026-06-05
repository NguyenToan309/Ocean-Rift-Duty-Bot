# Ranking Merge by Discord ID + Custom Date Range — Design

**Date:** 2026-06-06
**Status:** Approved (brainstorming)
**Related:** [[project-duty-logger]]

## Problem

Bảng xếp hạng (web `/rankings`, Dashboard top, panel Discord, `/top`, `/bottom`, `/stats`, export) đang
**group theo `(user_id, username)`**. Cùng 1 Discord user có nhiều tên ingame (admin chưa rebind hoặc
binding cũ) sẽ xuất hiện nhiều dòng riêng. Ví dụ thực tế trong screenshot:

- `Bò Biết bay` (ID `858644520035155988`) — rank 1 với `CP397446` (38h27m) **và** rank 10 với `Bò Biết Bay` (4h47m).
- `Diệp Phong` (ID `1023985584488460379`) — 3 dòng riêng (`CP159864`, `Gánh Cả Lũ`, `LoudGoose7415`).
- Tổng cộng ≥7 cặp/bộ trùng trong top 20.

Ngoài ra, web hiện chỉ có 4 period preset (Hôm nay / Tuần / Tháng / Quý). Người dùng cần lọc
**từ ngày X tới ngày Y** tùy ý — backend đã hỗ trợ `date_from`/`date_to` nhưng UI thiếu.

## Goals

1. Mọi nơi hiển thị tổng hợp xếp hạng → 1 Discord ID = 1 dòng duy nhất.
2. Tên hiển thị khi gộp: `DutyIdentityBinding.current_ingame_name` (fallback: username log mới nhất).
3. Web thêm chip **"Tùy chỉnh"** trên Topbar period → popover chọn from/to date.
4. Không hồi quy: lệnh Discord `/top`, `/bottom`, `/stats` giữ choices ngày/tuần/tháng/quý/custom hiện tại.

## Non-goals

- Không đổi schema DB.
- Không thêm option `date_from`/`date_to` riêng vào slash command Discord (giữ `custom` hiện có).
- Không đổi format export Excel/CSV — chỉ đổi danh sách rows.
- Không refactor toàn diện `control_panel.py` (đã có altitude finding riêng — xử lý trong task khác).

## Architecture

### Helper backend (mới): `utils/ranking_utils.py`

Đặt cạnh `utils/export_utils.py`. Chia sẻ giữa bot (`bot/cogs/*`) và web (`web/routers/*`).

```python
from dataclasses import dataclass
from datetime import datetime
from sqlalchemy import select, func, desc, asc, text
from sqlalchemy.ext.asyncio import AsyncSession
from models.duty_log import DutyLog
from models.duty_identity_binding import DutyIdentityBinding

@dataclass
class RankingRow:
    user_id: int
    display_name: str   # binding.current_ingame_name hoặc latest log username
    total_minutes: int
    sessions: int

async def aggregate_ranking(
    session: AsyncSession,
    *,
    guild_id: int,
    start: datetime,
    end: datetime,
    order: str = "desc",         # "desc" | "asc"
    limit: int | None = None,
    offset: int = 0,
) -> list[RankingRow]: ...

async def resolve_display_name(
    session: AsyncSession,
    *,
    guild_id: int,
    user_id: int,
) -> str:
    """Cho /stats single-user. Binding > latest log username > 'Unknown'."""
```

### SQL — 1 query duy nhất

```sql
WITH agg AS (
  SELECT
    user_id,
    SUM(duration_minutes) AS total_minutes,
    COUNT(*) AS sessions,
    (ARRAY_AGG(username ORDER BY started_at DESC))[1] AS latest_username
  FROM duty_logs
  WHERE guild_id = :gid
    AND user_id IS NOT NULL
    AND started_at >= :start
    AND started_at <= :end
  GROUP BY user_id
)
SELECT
  agg.user_id,
  COALESCE(b.current_ingame_name, agg.latest_username) AS display_name,
  agg.total_minutes,
  agg.sessions
FROM agg
LEFT JOIN duty_identity_binding b
  ON b.guild_id = :gid AND b.discord_user_id = agg.user_id
ORDER BY agg.total_minutes {DESC|ASC}
LIMIT :limit OFFSET :offset;
```

**Lý do dùng `ARRAY_AGG(username ORDER BY started_at DESC)[1]` thay vì window function:**
chạy 1 lần trong GROUP BY (1 layer SQL), tận dụng index `ix_duty_logs_ranking_cover`
trên `(guild_id, started_at, user_id, duration_minutes)`. Window function cần subquery + filter `rn=1`.

**Pagination đúng:** gộp xảy ra trong SQL trước khi `LIMIT/OFFSET` — luôn trả `page_size` dòng.

**Yêu cầu Postgres:** `ARRAY_AGG` là chuẩn Postgres. Test DB phải dùng Postgres (verify `tests/conftest.py`
trước khi triển khai — nếu SQLite, dùng fixture Postgres riêng).

### Caller refactor

| File | Mục đích | Hành động |
|---|---|---|
| `web/routers/dashboard.py` (overview top) | `/api/dashboard/overview` top users | `aggregate_ranking(limit=5)` |
| `web/routers/dashboard.py` (ranking endpoint) | `/api/dashboard/ranking` | `aggregate_ranking` + pagination |
| `web/routers/export.py` | Export Excel/CSV ranking | `aggregate_ranking(limit=None)` |
| `bot/cogs/ranking.py` | `/top`, `/bottom` | `aggregate_ranking` |
| `bot/cogs/stats.py` | `/stats [@user]` | `resolve_display_name` (single user) |
| `bot/cogs/control_panel.py` × 4 panels | Panels real-time | `aggregate_ranking` |

Mỗi caller chỉ thay query — output shape (JSON, embed) giữ nguyên: remap `username → display_name`.

### Frontend (`homie-medic-dashboard`)

#### Type change

```ts
// components/layout/Topbar.tsx
export type Period = 'today' | 'week' | 'month' | 'quarter' | 'custom';

export interface PeriodState {
  period: Period;
  customRange: { from: string; to: string } | null;  // ISO YYYY-MM-DD
}
```

`<Outlet context={...} />` ở `RootLayout.tsx` đổi từ `{ period }` thành `PeriodState`.
Mọi page dùng `useOutletContext<PeriodState>()`.

#### UI

Chip thứ 5 cạnh `Quý`:

```
[Hôm nay] [Tuần] [Tháng] [Quý] [📅 Tùy chỉnh ▾]
                                       │
                                       └─ Popover:
                                          Từ ngày: <input type="date">
                                          Đến ngày: <input type="date">
                                          [Hủy]  [Áp dụng]
```

- `<input type="date">` native — không thêm dependency.
- Default value khi mở popover: `customRange` hiện tại, hoặc (hôm qua → hôm nay).
- Validation realtime: `to >= from`, `from >= 2024-01-01`, `to <= today`. Disable nút "Áp dụng" nếu sai.
- Khi `period === 'custom'`, chip hiển thị `📅 03/06 → 06/06` (format theo locale `vi-VN`).
- Click period khác (today/week/month/quarter) → reset `customRange = null`.

#### Persistence

Lưu `{ period, customRange }` vào `localStorage['duty:period_state_v2']`.
Schema key có suffix `_v2` để invalidate cache cũ (phòng dữ liệu cũ chỉ là string `period`).

#### Hook update

`hooks/useApi.ts` — hooks dùng period (`useRanking`, `useOverview`, `useChart`, `useAttendance`,
`useLeavePending`) nhận thêm tham số `customRange?: { from, to } | null`:

```ts
if (period === 'custom' && customRange) {
  params.date_from = customRange.from;
  params.date_to = customRange.to;
} else {
  params.period = period;
}
```

Backend đã có nhánh `if date_from and date_to: ...` — không cần đổi server.

## Data flow

```
User clicks "Tùy chỉnh" → popover opens
  → user picks from=01/06 to=06/06 → "Áp dụng"
  → Topbar setState({ period: 'custom', customRange: { from, to } })
  → localStorage write
  → Outlet context propagates to RankingsPage
  → useRanking(guildId, 'custom', mode, 20, {from,to})
  → GET /api/dashboard/ranking?date_from=2026-06-01&date_to=2026-06-06&...
  → backend: get_custom_range(from, to, guild_tz) → (start_utc, end_utc)
  → aggregate_ranking(session, guild_id, start, end, order, limit, offset)
  → JSON items[] với username = display_name
  → Frontend render
```

## Error handling

| Layer | Case | Handle |
|---|---|---|
| Frontend | from > to | Disable "Áp dụng", hiện text đỏ "Từ ngày phải ≤ đến ngày" |
| Frontend | from invalid YYYY-MM-DD | `<input type=date>` tự reject |
| Frontend | API trả 400 | Toast "Khoảng ngày không hợp lệ" |
| Backend | `date_from` sai format | 400 với detail "invalid date_from format" (đã có trong `get_custom_range`) |
| Backend | `date_from > date_to` | 400 (verify hành vi hiện tại của `get_custom_range`; nếu chưa, thêm) |
| SQL | guild không có log | Trả `[]` (không exception) |
| SQL | user_id NULL trong log cũ | `WHERE user_id IS NOT NULL` loại bỏ ngay |
| SQL | binding tồn tại nhưng `current_ingame_name = ""` | `COALESCE` chấp nhận empty string; thêm `NULLIF(b.current_ingame_name, '')` để empty → fallback latest_username |

## Test plan

### Unit — `tests/test_ranking_aggregation.py` (mới)

1. Empty guild → `[]`.
2. 1 user có binding `current=Alice`, 3 log với username `Alice`/`Alicia`/`A` → 1 row, `display_name=Alice`, `total_minutes=sum`, `sessions=3`.
3. 1 user KHÔNG binding, 3 log username `X`/`Y`/`Z` theo `started_at` tăng dần → 1 row, `display_name=Z`.
4. 1 user có binding với `current_ingame_name=''` (empty) → fallback latest username.
5. 2 user khác nhau, `order=desc` → user lớn xếp trên.
6. `limit=1, offset=1` → đúng user thứ 2.
7. Custom date range loại bỏ log ngoài khoảng.
8. Khác `guild_id` → không lẫn dữ liệu giữa guild.

### Regression — `tests/test_dashboard_ranking_endpoint.py` (mở rộng nếu có)

1. `/api/dashboard/ranking` trả đúng shape (`items[].username` chính là display_name).
2. `date_from=2026-06-01&date_to=2026-06-06` filter đúng.
3. `date_from=invalid` → 400.
4. `date_from > date_to` → 400.
5. Chưa login → 401.

### E2E manual ([feedback_verification.md](memory/feedback_verification.md))

1. Smoke: `python -X utf8 -c "from utils.ranking_utils import aggregate_ranking, resolve_display_name"`.
2. `pytest --override-ini="addopts="` không regression.
3. UI: `/rankings` → Tháng → kiểm 1 row/user. Click Tùy chỉnh → pick range → verify số liệu khớp SUM manual.
4. Discord: `/top ky:thang` → kiểm 1 row/user trong embed.
5. Console không có WARNING/ERROR mới.
6. EXPLAIN ANALYZE query trên dataset thực tế → confirm dùng `ix_duty_logs_ranking_cover`.

## Rollout

7 commit độc lập, mỗi commit deploy được riêng:

1. Add `utils/ranking_utils.py` + unit tests. Không ai gọi → safe.
2. Refactor `web/routers/dashboard.py` (2 endpoint) + `web/routers/export.py`. Integration tests.
3. Refactor `bot/cogs/ranking.py` + `bot/cogs/stats.py`.
4. Refactor 4 panel trong `bot/cogs/control_panel.py`.
5. Frontend `Period` type + Topbar custom chip + popover.
6. Update page consumer (`RankingsPage`, `DashboardPage`, `DutyLogsPage`...) dùng `PeriodState`.
7. Optional: `scripts/backfill_identity_binding.py` chạy 1 lần production rồi xoá.

## Risk register

| Risk | Mitigation |
|---|---|
| `ARRAY_AGG` không có trên SQLite (test) | Verify `tests/conftest.py` dùng Postgres; nếu cần, fixture testcontainers. |
| Binding stale sau khi admin rebind | Đúng spec hiện tại — display_name update, log cũ giữ username cũ trong DB. Đây là feature. |
| Performance regression với dataset lớn | EXPLAIN trước/sau. Index `ix_duty_logs_ranking_cover` đã cover. |
| localStorage cache stale schema cũ | Bump key thành `duty:period_state_v2`. |
| User Discord ID = 0/NULL (log orphan) | `WHERE user_id IS NOT NULL AND user_id <> 0`. |
| Custom range > 6 tháng làm SQL chậm | Giới hạn UI: `to - from <= 365 days`, hiển thị text "Khoảng tối đa 1 năm" nếu vượt. |

## Out of scope (track riêng)

Theo code review trước đó:
- Extract `_render_table` helper cho 5 panel embed (altitude finding).
- Cache brand_name TTL (efficiency finding).
- `PANEL_REGISTRY` dispatch cho `_refresh_panels_tick` (altitude finding).
- Re-OCR overhead trong `/log upload` error path (efficiency finding).
