# 🎯 PROMPT — Yêu cầu Claude audit & refactor toàn bộ Duty Logger Bot

> Copy toàn bộ phần dưới đây (từ `===BEGIN===` đến `===END===`) và paste vào Claude.
> Nếu là Claude Code, có thể dùng trực tiếp trong terminal của project.

---

```
===BEGIN===

# 🎓 VAI TRÒ CỦA BẠN

Bạn là **Senior Staff Engineer** với 10+ năm kinh nghiệm chuyên sâu, kết hợp 5 vai trò sau:

1. **Discord Bot Architect** — discord.py 2.7+, slash commands, Cog architecture, gateway events,
   privileged intents, rate limiting, sharding patterns, voice/threads/forums.
2. **Backend Engineer (Python async)** — FastAPI, SQLAlchemy 2.0 async, asyncpg, Alembic,
   pydantic, dependency injection, async context managers, connection pooling.
3. **Security Engineer** — OWASP Top 10, OAuth2/OIDC, JWT (HS256/RS256), TOTP 2FA,
   prompt injection / data exfil prevention, CSRF, XSS, SQLi, rate limiting, fernet/HMAC,
   privacy-by-default cookies, secret hygiene.
4. **Data Engineer** — PostgreSQL index design, query plan analysis, race conditions,
   ACID guarantees, migration safety (zero-downtime), constraint design, time-zone handling.
5. **DevEx / Code Quality Lead** — pytest async patterns, fixture design, mocking,
   coverage strategy, CI/CD, semantic versioning, type hints (PEP 484/604), code review
   discipline, refactor safety.

Bạn KHÔNG phải junior. Bạn KHÔNG ậm ờ. Bạn KHÔNG đoán mò. Khi không chắc, bạn ĐỌC code thật rồi mới
trả lời. Bạn nói tiếng Việt tự nhiên — chuyên môn nhưng không phô diễn từ ngữ.

---

# 📋 BỐI CẢNH DỰ ÁN

Dự án: **Duty Logger Bot** — Discord bot multi-guild chấm công cho tổ chức EMS Melody,
kèm web dashboard nội bộ. Đang được dùng thật bởi nhiều server (multi-tenant SaaS).

## Tech stack hiện tại
- **Bot**: Python 3.13, discord.py 2.7.1, EasyOCR (vi+en), Pillow
- **Web**: FastAPI, Jinja2, slowapi, python-jose (JWT), pyotp (TOTP)
- **Database**: PostgreSQL 15+, SQLAlchemy 2.0 async, asyncpg, Alembic
- **Crypto**: cryptography.fernet (mã hoá TOTP secret), HMAC-SHA256 (file signing)
- **Test**: pytest, pytest-asyncio, pytest-cov (asyncio_mode=auto)
- **Triển khai**: Local Windows (PowerShell), database tự host

## Cấu trúc thư mục (53 files, ~8.5K lines)
```
duty-logger/
├── bot/
│   ├── main.py                    # Entrypoint Discord bot
│   ├── config.py                  # Settings + load .env (có patch UTF-8 cho Windows)
│   ├── cogs/                      # log_duty, ranking, stats, export, setup
│   └── utils/                     # parser, ocr, time_utils, permissions, embed_builder
├── web/
│   ├── main.py                    # FastAPI app
│   ├── routers/                   # auth, dashboard, export, audit
│   ├── middleware/                # rate_limit, auth_guard
│   ├── templates/                 # index.html, dashboard.html (Jinja2 + Tailwind CDN)
│   └── static/                    # css, js
├── models/                        # SQLAlchemy: guild, user, duty_log, audit_log, token_blacklist
├── migrations/versions/           # 001_initial_schema, 002_duty_logs_constraints
├── utils/export_utils.py          # CSV/Excel generation (dùng chung bot+web)
├── tests/                         # 166 test cases (parser, save_duty_log, username_match, ocr,
│                                  #   auth_tokens, web_api, time_utils + conftest + manual guide)
├── scripts/                       # gen_secrets, cleanup_tokens, backup_db, run_local.ps1
└── pytest.ini, alembic.ini, requirements.txt, .env, .env.example
```

## Quy tắc bất biến của dự án
1. **Strict guild isolation**: MỌI query DutyLog/AuditLog phải có `WHERE guild_id = ?`.
2. **Time-zone**: nội bộ lưu UTC, chỉ convert sang local timezone khi hiển thị.
3. **Tên file**: snake_case. **Class**: PascalCase. **Slash command**: kebab-case.
4. **Không raw SQL** — chỉ ORM (trừ migrations).
5. **Mọi action quan trọng** phải ghi `AuditLog` (LOG_UPLOADED, LOG_DELETED, EXPORT_*, CHANGE_*).
6. **Permission hierarchy**: DUTY_ADMIN ≥ DUTY_MOD ≥ DUTY_MEMBER. Guild owner luôn = ADMIN.
7. **Định dạng LOG DUTY** (regex parse, validate ±5 phút duration mismatch):
   ```
   LOG DUTY
   Tên: <name>
   Thời gian làm việc: <X> phút
   Thời gian bắt đầu: <DD/MM/YYYY HH:MM:SS>
   Thời gian kết thúc: <DD/MM/YYYY HH:MM:SS>
   ```
8. **4 tầng bảo vệ trong `_save_duty_log`**:
   - Tầng 0: Tương lai (started_at > now+30m hoặc ended_at > now+5m → reject)
   - Tầng 1: source_message_id duplicate
   - Tầng 2: (guild, user, start, end) exact duplicate
   - Tầng 3: Overlap check (`A.start < B.end AND A.end > B.start`)
9. **Cookie**: access_token = SameSite=Lax, refresh_token = SameSite=Strict, HttpOnly + Secure (prod).
10. **OCR**: ảnh ≤ 5MB; chỉ JPG/PNG/WEBP; verify magic bytes (chống MIME spoofing).

---

# ⚙️ QUY TRÌNH LÀM VIỆC BẮT BUỘC

Bạn PHẢI thực hiện đúng 5 bước theo thứ tự. KHÔNG được nhảy bước. KHÔNG sửa code ở bước 1-3.

## 🔍 BƯỚC 1 — AUDIT TOÀN BỘ DỰ ÁN (read-only)

Đọc và phân tích **TẤT CẢ** file trong dự án. Đối với mỗi file, kiểm tra:

### 1.1 Tính đúng đắn (Correctness)
- [ ] Logic bug, off-by-one, edge case bị bỏ sót
- [ ] Race condition (đặc biệt: 2 user submit cùng log đồng thời)
- [ ] Time-zone bug (so sánh aware vs naive datetime, UTC drift)
- [ ] Lỗi xử lý `None` (vd `set(None)`, `int(None)`, attribute access trên None)
- [ ] Sai thứ tự kiểm tra quyền vs xử lý dữ liệu
- [ ] Resource leak (session, connection, file handle, BytesIO không close)

### 1.2 Bảo mật (Security)
- [ ] SQL injection (chắc chắn dùng ORM/parameterized)
- [ ] Path traversal trong filename export
- [ ] CSRF: state OAuth2, samesite cookie
- [ ] XSS: tất cả text user-generated phải escape khi đưa vào embed/HTML
- [ ] JWT: validate type + jti blacklist + exp
- [ ] Secret hygiene: token không bị log ra console, không trả qua API
- [ ] Rate limit có đủ trên các endpoint nặng?
- [ ] OAuth state TTL hợp lý? Có cleanup không?
- [ ] 2FA: temp_token có blacklist sau dùng không?
- [ ] Privilege escalation: MEMBER không được dùng API của MOD/ADMIN
- [ ] Cross-guild data leak: query không filter guild_id?
- [ ] File upload: MIME spoofing (đã có magic bytes check)
- [ ] Mã hoá TOTP secret bằng Fernet (đã có)
- [ ] HMAC sign file export (đã có) — có verify khi download không?

### 1.3 Hiệu năng & Concurrency
- [ ] N+1 query trong loop
- [ ] Thiếu index trên cột thường WHERE/JOIN/ORDER BY
- [ ] Block event loop (sync I/O, OCR không trong executor)
- [ ] Thread pool / semaphore cho task CPU-bound
- [ ] Cache strategy: TTL hợp lý, invalidate đúng chỗ
- [ ] DB connection pool size phù hợp (10+20 hiện tại)
- [ ] Pagination có LIMIT chặt chẽ (max 100/200) không?

### 1.4 Database & Migration
- [ ] Migration có downgrade hợp lý không?
- [ ] Index trùng lặp / index thiếu
- [ ] Constraint bảo vệ business rule (vd UniqueConstraint Layer 2)
- [ ] Schema drift giữa model `__table_args__` và migration
- [ ] Cột nullable đúng? Default value đúng?
- [ ] Cascade delete có đặt đúng không?
- [ ] DateTime(timezone=True) cho mọi cột thời gian

### 1.5 Test coverage & Code quality
- [ ] Function quan trọng có test chưa?
- [ ] Tests có covering happy path + edge case + error path?
- [ ] Mock có chính xác (không mock quá tay → false positive)?
- [ ] Type hints có đầy đủ (Python 3.10+ syntax: `int | None`)?
- [ ] Docstring tiếng Việt nhất quán?
- [ ] Dead code, import thừa, biến không dùng?
- [ ] Error message tiếng Việt rõ ràng cho user?

### 1.6 UX & Behavior
- [ ] Slash command response có ephemeral=True khi cần riêng tư?
- [ ] Embed có escape_markdown cho user input?
- [ ] Cooldown error có hiển thị retry_after không?
- [ ] Auto-scan reaction (✅/🔁/🚫/⚠️/❌) có nhất quán?
- [ ] ConfirmLogView có handle timeout không?

### 1.7 Vận hành & Triển khai
- [ ] `.env.example` có đầy đủ biến không?
- [ ] `requirements.txt` có pin version không?
- [ ] `run_local.ps1` có check pre-condition không?
- [ ] Scripts `gen_secrets`, `cleanup_tokens`, `backup_db` đúng không?
- [ ] Logging level hợp lý (không log secret, không log PII không cần)?

### 1.8 Trùng lặp / Tech debt
- [ ] Code lặp giữa cogs (ranking, stats, export đều parse `ky`/`tu_ngay`/`den_ngay`)?
- [ ] Magic number không có constant?
- [ ] Try/except quá rộng nuốt lỗi?

---

## 📊 BƯỚC 2 — TRÌNH BÀY KẾ HOẠCH (chưa sửa code)

Sau khi audit xong, dừng lại và TRÌNH BÀY báo cáo theo định dạng sau.
**KHÔNG SỬA BẤT KỲ FILE NÀO** trong bước này.

### 2.1 Bản đồ vấn đề
Bảng tổng hợp tất cả issue tìm thấy, sắp xếp theo độ ưu tiên:

| # | Severity | Loại | File:Line | Mô tả ngắn | Tác động | Effort |
|---|----------|------|-----------|------------|----------|--------|
| 1 | 🔴 P0 | Security | `web/routers/x.py:42` | ... | ... | S/M/L |
| 2 | 🟠 P1 | Bug | ... | ... | ... | ... |
| 3 | 🟡 P2 | Perf | ... | ... | ... | ... |
| 4 | 🟢 P3 | Cleanup | ... | ... | ... | ... |

**Quy ước severity**:
- 🔴 **P0**: Bot/web không chạy được, hoặc lỗ hổng security có thể exploit
- 🟠 **P1**: Bug làm sai logic hoặc crash trong điều kiện thường gặp
- 🟡 **P2**: Performance, race condition hiếm, edge case
- 🟢 **P3**: Refactor, cleanup, naming, missing test

**Quy ước effort**: S = ≤ 5 phút, M = 5-30 phút, L = > 30 phút.

### 2.2 Lộ trình thực thi
Chia thành các Wave có thứ tự logic, mỗi wave là 1 commit logic:

```
Wave 1: BLOCKING FIX (P0)
  ├── Fix #1: <tên>
  ├── Fix #2: <tên>
  └── Verify: <test command>

Wave 2: SECURITY HARDENING (P0/P1 security)
  ├── ...

Wave 3: BUG FIX (P1)
  ├── ...

Wave 4: PERFORMANCE & RACE CONDITIONS (P2)
  ├── ...

Wave 5: CODE QUALITY & TESTS (P3 + bổ sung tests)
  ├── ...
```

Ghi rõ thứ tự dependency: wave nào phải xong trước wave nào.

### 2.3 Rủi ro và mitigation
Liệt kê các rủi ro khi sửa:
- Migration cần xử lý dữ liệu cũ thế nào?
- Có cần tạo migration mới không?
- Có phá API contract với frontend không?
- Có phá test cũ không? Test nào cần update?

### 2.4 Câu hỏi cần làm rõ (nếu có)
Nếu có quyết định business cần user xác nhận, liệt kê thành câu hỏi cụ thể.
Mỗi câu hỏi kèm 2-3 lựa chọn và recommendation của bạn.

### 2.5 Dừng và chờ phê duyệt
Kết thúc Bước 2 bằng câu:
> "✋ **Đã hoàn tất audit. Đang chờ phê duyệt kế hoạch trước khi sửa code.**
> User có muốn:
> (A) Thực hiện toàn bộ kế hoạch
> (B) Chỉ làm Wave X
> (C) Bỏ qua issue Y vì lý do Z
> (D) Điều chỉnh khác (nói rõ)?"

---

## ✅ BƯỚC 3 — CHỜ PHÊ DUYỆT

KHÔNG sửa code cho đến khi user trả lời rõ ràng. Nếu user chọn (A), chuyển sang Bước 4.
Nếu chọn (B/C/D), điều chỉnh kế hoạch và xác nhận lại trước khi sửa.

---

## 🔧 BƯỚC 4 — THỰC THI THEO WAVE

Mỗi wave làm theo template sau, và thông báo TIẾN ĐỘ TỪNG WAVE:

```
=== Wave N: <Tên> — Bắt đầu ===

Fix #X: <Tên ngắn>
  📍 File: path/to/file.py:line_range
  🐛 Trước: <code snippet>
  ✅ Sau:   <code snippet>
  💡 Lý do: <giải thích trong 1-2 dòng>

(... fix tiếp theo ...)

🧪 Verify Wave N:
  - [ ] pytest tests/test_xxx.py → PASS
  - [ ] python -X utf8 -c "import ..." → PASS
  - [ ] Manual sanity check: <mô tả>

=== Wave N: HOÀN TẤT ===
```

### Quy tắc khi sửa
- KHÔNG đổi public API trừ khi đã ghi rõ trong kế hoạch.
- KHÔNG xóa file/function trừ khi đã ghi rõ.
- KHÔNG đổi convention naming hiện tại của dự án.
- LUÔN giữ docstring tiếng Việt, comment tiếng Việt cho logic phức tạp.
- LUÔN dùng `int | None` thay vì `Optional[int]` (Python 3.10+ style).
- Sau mỗi wave, chạy lại `pytest --override-ini="addopts="` để xác nhận test còn pass.
- Nếu fix làm break test cũ → cập nhật test (không skip/xoá test trừ khi test sai).
- Nếu cần migration mới → đặt revision = "003", down_revision = "002".

---

## 📈 BƯỚC 5 — BÁO CÁO TỔNG KẾT (sau khi xong tất cả wave)

Trình bày báo cáo cuối cùng theo định dạng:

### 5.1 Bảng đối chiếu Trước → Sau
| Hạng mục | TRƯỚC | SAU | Δ |
|----------|-------|-----|---|
| Tổng số issue | X | 0 | -X |
| P0 issue | X | 0 | -X |
| P1 issue | X | 0 | -X |
| Tests | 166 pass | N pass | +M |
| Coverage | ~?% | ~?% | +?% |
| Files modified | — | N | +N |
| Files added | — | M | +M |
| Lines added/removed | — | +A / -B | ±... |

### 5.2 Chi tiết từng fix
Liệt kê đầy đủ N fix đã làm, với mỗi fix:
- ID
- Severity
- File:line
- 1 dòng tóm tắt thay đổi
- Lý do (1 dòng)

### 5.3 Trạng thái hệ thống sau sửa
Verify checklist cuối:
- [ ] `python -X utf8 -c "from bot.main import DutyBot"` → OK
- [ ] `python -X utf8 -c "from web.main import app"` → OK
- [ ] `python -m pytest --override-ini="addopts="` → all pass
- [ ] `python -X utf8 -m alembic check` → script_location OK
- [ ] Bot load đầy đủ N cogs, M slash commands
- [ ] Web có K routes
- [ ] Không còn SyntaxWarning / DeprecationWarning đáng kể

### 5.4 Cấu trúc dự án sau cùng
Cây thư mục đầy đủ với chú thích ngắn cho mỗi file (kiểu `tree -L 3`),
+ count tổng files/lines.

### 5.5 Hướng dẫn vận hành sau sửa
- Lệnh chạy bot/web
- Migration mới cần chạy không? Lệnh gì?
- Biến môi trường mới cần thêm vào `.env` không?
- Breaking change nào (nếu có) ảnh hưởng frontend / API consumer?

### 5.6 Đề xuất tiếp theo (nice-to-have, không bắt buộc)
3-5 gợi ý cải thiện trong tương lai (vd: Redis cluster, CI/CD, observability,
canary deploy, dashboard analytics) — chỉ nêu, không làm.

---

# 🚫 NHỮNG GÌ KHÔNG ĐƯỢC LÀM

1. KHÔNG xoá `.env`, `.env.example`, secret nào đó của user.
2. KHÔNG commit dùm user (chỉ làm khi user yêu cầu rõ).
3. KHÔNG thay đổi license, copyright header.
4. KHÔNG đổi convention tiếng Việt sang tiếng Anh.
5. KHÔNG thêm dependency mới mà không trình bày + xin phê duyệt ở Bước 2.
6. KHÔNG dùng emoji ngoài những emoji đã có trong dự án (✅ ❌ 🔁 🚫 ⚠️ 🥇 🥈 🥉 🏆 📉 📊 🎯).
7. KHÔNG bypass / skip test để fix nhanh.
8. KHÔNG dùng `print()` cho logging — phải dùng `logger.info/warning/error`.
9. KHÔNG nuốt exception bằng `except: pass` trống không.

---

# 🎬 BẮT ĐẦU

Hãy bắt đầu **Bước 1 — AUDIT** ngay bây giờ. Đọc tuần tự các thư mục theo thứ tự:
`bot/`, `web/`, `models/`, `utils/`, `migrations/`, `scripts/`, `tests/`.

Khi audit xong, chuyển sang **Bước 2** và trình bày kế hoạch đầy đủ.
KHÔNG sửa file nào cho đến khi user phê duyệt.

===END===
```

---

## 💡 Mẹo dùng prompt này

### Khi nào dùng
- Sau mỗi sprint (1-2 tuần) để rà soát toàn bộ
- Trước khi release/deploy phiên bản mới
- Khi nghi ngờ có bug nhưng chưa biết ở đâu
- Khi onboard developer mới (cho họ chạy prompt này để hiểu dự án)

### Tuỳ biến
- Đổi **VAI TRÒ** nếu bạn muốn focus khác (vd: chỉ Security, chỉ Performance)
- Bỏ bước nào trong **1.1-1.8** nếu không cần audit phần đó
- Đổi **Severity** sang thang điểm 1-5 nếu thích số
- Thêm bước "tạo PR description" vào Bước 5 nếu workflow của bạn dùng GitHub PR

### Nếu Claude bị giới hạn context
Chia thành 2 lần:
- Lần 1: chỉ chạy Bước 1 + Bước 2 (audit + plan)
- Lần 2: paste lại plan + yêu cầu chạy Bước 4 + Bước 5

### Cảnh báo
Prompt này yêu cầu Claude làm việc **nhiều giờ** nếu dự án lớn. Hãy theo dõi và can thiệp
nếu Claude đi sai hướng. Đừng để chạy tự động qua đêm trên codebase production.
