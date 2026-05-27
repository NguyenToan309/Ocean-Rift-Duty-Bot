# Admin Overview — Bot Installations & OAuth2 Authorizations

**Ngày**: 2026-05-28
**Trạng thái**: approved, sẵn sàng implement
**Người duyệt**: bot owner (toantringuyen.309@gmail.com)

## Mục đích

Cho phép bot owner xem qua web dashboard:
1. Danh sách server bot đang được cài (tương ứng "Số lượt cài đặt" Discord Developer Portal)
2. Danh sách user đã OAuth2 vào web (tương ứng "Số lượng ủy quyền")

Mỗi mục có toàn bộ metadata có thể lấy được (chi tiết khách quan nhất), với graceful degradation cho field nào không lấy được.

## Phạm vi truy cập

Chỉ user có `discord_id` nằm trong env `BOT_OWNER_IDS` (comma-separated). Tất cả user khác → 403.

## API design

### Endpoint 1: lấy data

**`GET /api/admin/overview`**

- Auth: JWT access token + `require_bot_owner()` dependency (2 layers)
- Rate limit: `10/minute` per IP
- Response: JSON shape ở section "Response shape"
- Cache: in-memory dict, TTL 300s (5 phút)
- Side effect: ghi `AuditLog(action='ADMIN_OVERVIEW_VIEWED', user_id=owner_id)`

### Endpoint 2: invalidate cache

**`POST /api/admin/overview/refresh`**

- Auth: như trên
- Action: xoá `_OVERVIEW_CACHE`, không trả data
- Response: `{"refreshed": true, "ts": <iso>}`
- Side effect: ghi `AuditLog(action='ADMIN_OVERVIEW_REFRESHED')`

## Data thu thập

### Per installation (mỗi guild)

| Field | Nguồn | Nullable | Lý do null |
|---|---|---|---|
| `guild_id` | Discord GET /users/@me/guilds | Không | — |
| `guild_name` | Discord GET /users/@me/guilds | Không | — |
| `icon_url` | Discord GET /users/@me/guilds (hash → CDN URL) | Có | Guild chưa set icon |
| `banner_url` | Discord GET /guilds/{id} | Có | Guild chưa boost đủ |
| `member_count` | Discord GET /users/@me/guilds?with_counts=true | Có | API rate limit |
| `presence_count` | Discord GET /users/@me/guilds?with_counts=true | Có | Như trên |
| `boost_level` | Discord GET /guilds/{id} | Có | API rate limit |
| `boost_count` | Discord GET /guilds/{id} | Có | Như trên |
| `features` | Discord GET /guilds/{id} | Có | Như trên |
| `preferred_locale` | Discord GET /guilds/{id} | Có | Như trên |
| `owner` (id, username, avatar) | Discord GET /guilds/{id}.owner_id + resolver | Có | API fail / user bị xoá |
| `inviter` (id, username) | Discord GET /guilds/{id}/audit-logs?action_type=28 | Có (thường null) | Bot thiếu VIEW_AUDIT_LOG / log expire 90 ngày / log bị xoá |
| `bot_joined_at` | Discord GET /guilds/{id}/members/{bot_id}.joined_at | Có | Bot thiếu perm |
| `bot_permissions` | Discord GET /users/@me/guilds.permissions (bitfield) | Không | — |
| `setup_status` | DB `guild_configs` WHERE guild_id=? | Không | "configured" / "pending" |
| `setup_at` | DB `guild_configs.created_at` | Có | Chưa setup |
| `log_channel_id` | DB `guild_configs.log_channel_id` | Có | Chưa setup hoặc setup mà chưa /setup channel |
| `timezone` | DB `guild_configs.timezone` | Có | Chưa setup |
| `is_active` | DB `guild_configs.is_active` | Có | Chưa setup |
| `role_map_count` | DB `guild_configs.role_map` (chỉ trả count, không expose role id) | Có | Chưa setup roles |
| `duty_log_count` | DB COUNT(duty_logs) WHERE guild_id=? | Không | 0 nếu chưa có log |
| `last_duty_log_at` | DB MAX(duty_logs.created_at) WHERE guild_id=? | Có | Chưa có log nào |
| `unique_users_logged` | DB COUNT DISTINCT user_id WHERE guild_id=? | Không | 0 nếu chưa có log |

### Per authorization (mỗi user OAuth2)

| Field | Nguồn | Nullable |
|---|---|---|
| `discord_id` | DB users | Không |
| `username` | DB users | Không |
| `discriminator` | DB users | Có (user dùng username system mới không có) |
| `avatar_url` | DB users | Có |
| `first_login_at` | DB users.created_at | Không |
| `last_login_at` | DB users.last_login_at | Có (user tạo nhưng chưa login lại) |
| `last_login_ip` | DB users.last_login_ip | Có |
| `is_2fa_enabled` | DB users.is_2fa_enabled | Không |
| `failed_login_attempts` | DB users.failed_login_attempts | Không (default 0) |
| `locked_until` | DB users.locked_until | Có (không bị lock) |
| `total_logins` | DB COUNT(audit_logs WHERE action='LOGIN_SUCCESS' AND user_id=?) | Không |
| `last_action_at` | DB MAX(audit_logs.created_at WHERE user_id=?) | Có |

### Totals (summary)

| Field | Công thức |
|---|---|
| `total_installs` | `len(installations)` |
| `configured` | count installations có setup_status='configured' |
| `pending` | total_installs - configured |
| `total_authorizations` | `len(authorizations)` |
| `with_2fa` | count authorizations is_2fa_enabled=True |
| `active_last_7d` | count authorizations có last_login_at >= now-7d |
| `total_duty_logs` | SUM(duty_log_count) across installations |
| `unique_users_global` | DB COUNT DISTINCT user_id FROM duty_logs |

## Response shape

```json
{
  "installations": [
    {
      "guild_id": "123",
      "guild_name": "Ocean Rift",
      "icon_url": "https://cdn.discordapp.com/icons/123/abc.png",
      "banner_url": null,
      "member_count": 1234,
      "presence_count": 87,
      "boost_level": 0,
      "boost_count": 0,
      "features": ["COMMUNITY"],
      "preferred_locale": "vi",
      "owner": {"id": "456", "username": "tom", "avatar_url": "..."},
      "inviter": null,
      "bot_joined_at": "2026-04-01T10:00:00Z",
      "bot_permissions": "8",
      "setup_status": "configured",
      "setup_at": "2026-04-01T10:30:00Z",
      "log_channel_id": "789",
      "timezone": "Asia/Ho_Chi_Minh",
      "is_active": true,
      "role_map_count": 3,
      "duty_log_count": 1523,
      "last_duty_log_at": "2026-05-27T08:30:00Z",
      "unique_users_logged": 42
    }
  ],
  "authorizations": [
    {
      "discord_id": "789",
      "username": "alice",
      "discriminator": null,
      "avatar_url": "...",
      "first_login_at": "2026-05-01T...",
      "last_login_at": "2026-05-27T...",
      "last_login_ip": "10.0.0.1",
      "is_2fa_enabled": true,
      "failed_login_attempts": 0,
      "locked_until": null,
      "total_logins": 15,
      "last_action_at": "2026-05-27T..."
    }
  ],
  "totals": {
    "total_installs": 4,
    "configured": 2,
    "pending": 2,
    "total_authorizations": 2,
    "with_2fa": 1,
    "active_last_7d": 2,
    "total_duty_logs": 5000,
    "unique_users_global": 150
  },
  "fetched_at": "2026-05-28T10:00:00Z",
  "cache_hit": false
}
```

## Cache strategy

**In-memory** (single-worker; multi-worker → defer Redis migration #2 từ audit gốc):

```python
_OVERVIEW_CACHE: {data: dict | None, ts: float}
TTL: 300s
```

Cache key duy nhất "overview" — không cần per-user vì chỉ owner xem.

POST refresh → set `_OVERVIEW_CACHE['ts'] = 0` → next GET miss.

Mỗi Discord helper (`fetch_guild_detail`, `fetch_guild_bot_member`, `fetch_guild_audit_inviter`) có cache riêng cấp granular hơn (cache per-guild) để partial refresh không lãng phí.

## Error handling

| Tình huống | Hành vi |
|---|---|
| Bot token revoke (Discord 401) | 503 + log error + alert (không leak token vào response) |
| Discord 429 rate limit | Return cached + header `X-Cache-Stale: true` + log warning |
| Discord 403 (thiếu perm cho guild N) | Field N.audit_inviter=null, N.bot_joined_at=null, không fail endpoint |
| Audit log expire (>90 ngày) | inviter=null, log debug |
| User không phải bot owner | 403 với message "Endpoint này chỉ dành cho bot owner" |
| `BOT_OWNER_IDS` không config | 500 + log critical (config error) |
| DB unreachable | 500 standard (existing handler) |
| `BOT_OWNER_IDS` parse fail (vd "abc,123") | App startup → log warning, skip giá trị invalid, dùng giá trị int hợp lệ còn lại |

## Security

- `BOT_OWNER_IDS` parse strict: chỉ accept comma-separated int, ignore whitespace, reject empty values, log warning nếu env trống/missing
- Endpoint require JWT access token + `require_bot_owner()` (2 layers)
- Cookie `access_token` đã HttpOnly + Secure (existing)
- Bot token KHÔNG bao giờ vào response/log message — chỉ dùng làm Authorization header
- Frontend: page chỉ render khi `/api/admin/overview` trả 200, ẩn link admin nếu user không phải owner
- IP của user mask trong response: chỉ owner thấy; hiển thị first 3 octet + .xxx (privacy)

## Components

### Backend

| File | Loại | Trách nhiệm |
|---|---|---|
| `bot/config.py` | sửa | Parse `BOT_OWNER_IDS` env → `set[int]`, validate format |
| `.env.example` | sửa | Thêm `BOT_OWNER_IDS=123,456,789` + comment hướng dẫn |
| `models/audit_log.py` | sửa | Thêm 2 enum values: `ADMIN_OVERVIEW_VIEWED`, `ADMIN_OVERVIEW_REFRESHED` |
| `web/middleware/auth_guard.py` | sửa | Thêm `require_bot_owner()` dependency |
| `web/utils/discord_resolver.py` | sửa | Thêm 4 hàm cached: `fetch_bot_guilds_with_counts()`, `fetch_guild_detail(id)`, `fetch_guild_bot_member(id, bot_id)`, `fetch_guild_audit_inviter(id)` |
| `web/routers/admin.py` | mới | 2 endpoint + cache + audit log writes |
| `web/main.py` | sửa | Register `admin.router` |
| `tests/test_admin_endpoint.py` | mới | 12 test cases (xem mục Testing) |

### Frontend

| File | Loại | Trách nhiệm |
|---|---|---|
| `homie-medic-dashboard/src/pages/AdminOverview.tsx` | mới | Layout 3 phần: cards + 2 table |
| `homie-medic-dashboard/src/components/AdminOverviewSummary.tsx` | mới | 8 summary cards |
| `homie-medic-dashboard/src/components/InstallationsTable.tsx` | mới | Table có sort/search/expand row |
| `homie-medic-dashboard/src/components/AuthorizationsTable.tsx` | mới | Table có sort/search/pagination |
| `homie-medic-dashboard/src/api/admin.ts` | mới | Fetch wrapper cho 2 endpoint |
| React Router config | sửa | Route `/admin/overview` (chỉ render khi current_user.discord_id ∈ owner set — check qua /api/auth/me thêm field is_bot_owner) |

### `/api/auth/me` cập nhật

Thêm field `is_bot_owner: bool` vào response → frontend dùng để hiển thị/ẩn link "Admin" trong nav.

## Data flow

```
1. User mở /admin/overview
2. React fetch GET /api/admin/overview
3. Middleware: csrf_origin_guard → security_headers → CORS
4. Dependency: get_current_user → require_bot_owner
   - Decode JWT (existing decode_token: check exp + jti + type)
   - Check int(payload["sub"]) ∈ settings.BOT_OWNER_IDS
   - Else: raise HTTPException(403, "Endpoint này chỉ dành cho bot owner")
5. Check cache _OVERVIEW_CACHE
   - Hit (ts > now - 300s): return cached với cache_hit=true
   - Miss: continue
6. Parallel asyncio.gather:
   a. fetch_bot_guilds_with_counts() — Discord 1 call trả [{id, name, icon, owner, permissions, approximate_member_count, approximate_presence_count}, ...]
   b. db_users = await session.execute(select(User).order_by(User.last_login_at.desc()))
   c. db_configs = await session.execute(select(GuildConfig))
   d. duty_aggregate = await session.execute(select guild_id, count, max(created_at), count(distinct user_id) from duty_logs group by guild_id)
   e. login_aggregate = await session.execute(select user_id, count, max(created_at) from audit_logs where action='LOGIN_SUCCESS' group by user_id)
7. Với mỗi guild, parallel asyncio.gather (semaphore 5 để tránh rate limit Discord):
   a. fetch_guild_detail(guild_id) → {features, banner, boost_level, preferred_locale, ...}
   b. fetch_guild_bot_member(guild_id, bot_user_id) → {joined_at}
   c. fetch_guild_audit_inviter(guild_id) → {inviter_id} | None
8. Resolve owner/inviter usernames qua batch_resolve_user_info (existing)
9. Merge tất cả vào response shape
10. Ghi AuditLog(ADMIN_OVERVIEW_VIEWED)
11. Cache + return JSON với cache_hit=false
```

## Frontend UX

**Summary cards row** (8 cards, responsive grid):
- Tổng server, Đã setup, Chưa setup, Tổng user OAuth2, Có 2FA, Active 7d, Tổng duty log, Unique users

**Installations table**:
- Columns: Avatar+Name, ID (copy button), Members, Owner (avatar+username), Setup status (badge: configured xanh / pending xám), Inviter (badge "(không xác định)" nếu null), Duty logs, Last log, Joined
- Sort theo bất kỳ cột nào
- Search: name / owner username / guild_id
- Click row → expand panel: log_channel, timezone, role_map_count, banner preview, features chips, boost level, bot_permissions translate

**Authorizations table**:
- Columns: Avatar+Name, ID (copy), 2FA (✓/✗ badge), Last login, Last IP (masked X.X.X.xxx), Failed attempts, Total logins, First seen
- Sort theo bất kỳ cột nào
- Search: username / discord_id
- Pagination 20 rows/page
- Highlight row nếu `locked_until > now` (background đỏ nhạt)

**Toolbar**:
- Refresh button (gọi POST /api/admin/overview/refresh rồi fetch lại)
- Last refresh: "Cập nhật N phút trước"
- Export CSV button (download CSV của full data, dùng existing `sign_file()`)
- Nếu `cache_hit=true` hiển thị badge "📦 cached"
- Nếu header `X-Cache-Stale: true` hiển thị warning "⚠️ Discord rate limit, dữ liệu có thể không mới nhất"

## Testing

`tests/test_admin_endpoint.py`:

1. `test_parse_bot_owner_ids_edge_cases` — "1,2,", " 3 ,4", "1,,2", "" → handle đúng (skip empty, log warning, parse int)
2. `test_require_bot_owner_no_config` — BOT_OWNER_IDS empty → 500
3. `test_require_bot_owner_not_in_list` — user khác → 403
4. `test_require_bot_owner_in_list` — owner → pass
5. `test_overview_happy_path` — mock Discord + DB → full response shape
6. `test_overview_discord_401` → 503 (bot token revoke)
7. `test_overview_discord_429` → return cached + `X-Cache-Stale: true` header
8. `test_overview_audit_log_403` → inviter=null cho guild đó, các guild khác vẫn có data đúng
9. `test_overview_no_setup` → setup_status='pending', setup_at=null, log_channel_id=null
10. `test_overview_cache_hit` → 2 lần fetch trong 5 phút chỉ 1 Discord call, lần 2 có cache_hit=true
11. `test_overview_refresh_invalidates` → POST refresh → next GET miss cache
12. `test_audit_log_written` — mỗi GET /overview ghi 1 AuditLog(ADMIN_OVERVIEW_VIEWED) row
13. `test_refresh_endpoint_audit_logged` — POST /refresh ghi AuditLog(ADMIN_OVERVIEW_REFRESHED)
14. `test_refresh_non_owner_403` — POST /refresh với non-owner → 403, không xoá cache
15. `test_auth_me_has_is_bot_owner` — GET /api/auth/me trả `is_bot_owner` đúng theo BOT_OWNER_IDS

Mọi test dùng pattern hiện có (`override_db`, `AsyncClient`, mock httpx).

## Deployment checklist

1. Cập nhật `.env`: thêm `BOT_OWNER_IDS=<discord_id của bạn>` (lấy từ Discord → Settings → Advanced → Developer Mode → right-click avatar → Copy User ID)
2. `git pull` + `pip install -r requirements.txt` (không deps mới)
3. Frontend rebuild: `cd homie-medic-dashboard && npm run build`
4. `alembic upgrade head` — KHÔNG cần (không migration mới)
5. Restart `web` (bot không cần restart)
6. Verify smoke test: login bot owner → mở `/admin/overview` → thấy data đầy đủ

## Verification gate sau implementation

**User explicit request**: phải double-check sau khi sửa còn lỗi gì không. Implementation plan PHẢI có verification step cuối cùng:

1. Smoke import:
   - `python -X utf8 -c "from web.main import app"` → OK
   - `python -X utf8 -c "from web.routers.admin import router"` → OK
2. Unit test:
   - `pytest tests/test_admin_endpoint.py -v` → all pass
   - `pytest --override-ini="addopts="` → 266+N/266+N pass (no regression)
3. Type check (nếu có sẵn): `mypy web/routers/admin.py` hoặc `ruff check`
4. Manual integration (start dev server):
   - Bot owner login → `/admin/overview` → response 200 + data đầy đủ
   - Non-owner user → `/admin/overview` → response 403
   - Test refresh button → invalidate cache, fetch lại, cache_hit=false → true lần 2
   - Test 1 guild bot không có VIEW_AUDIT_LOG perm → inviter=null, page vẫn render đủ
5. Audit log verify: query `SELECT * FROM audit_logs WHERE action='ADMIN_OVERVIEW_VIEWED' ORDER BY created_at DESC LIMIT 5` → có row mới
6. Performance check: time GET /overview cold cache với 10 guild → <3s
7. Log scan: không có warning/error mới trong console khi fetch

Báo cáo trạng thái mỗi mục: ✅ / ❌ / ⚠️. Nếu ❌ ở mục nào → quay lại fix trước khi đánh dấu complete.

## Trade-off đã chấp nhận

| Trade-off | Tại sao chấp nhận |
|---|---|
| 1 + N×3 Discord API call mỗi cold cache | Cache 5 phút giảm rate limit risk; admin page không xem liên tục |
| Inviter thường null | Best-effort, graceful degradation, không phá UI |
| Single-worker only | Phù hợp scope hiện tại; multi-worker defer Redis migration |
| Không real-time push | Admin overview không cần realtime, refresh button đủ |
| In-memory cache không shared | Acceptable với single-worker; refactor sang Redis khi cần |

## Phụ thuộc

- Không thêm Python dependency
- Không thêm npm dependency (giả sử project React đã có table/card component cơ bản; nếu chưa, dùng plain HTML + Tailwind có sẵn)

## Migration

Không cần migration mới — chỉ thêm 2 enum value vào `AuditAction` (Python const, không phải DB schema).

## Out of scope (defer)

- Multi-worker support (cần Redis cho cache)
- Real-time updates qua WebSocket
- Slash command `/owner installs` (per user decision: chỉ web)
- Audit log lookup cho field "ai invite bot" hiện best-effort; cải tiến chính xác hơn defer
- Owner management UI (thêm/xoá bot owner qua web) — hiện chỉ qua env

## Memory & feedback

User feedback ghi nhận: sau khi sửa xong phải double-check thật kỹ — không dừng ở "tests pass" mà phải verify cả manual integration, performance, log scan, audit log row mới. Áp dụng cho mọi feature implementation tương lai.
