# 🚂 Deploy Duty Logger lên Railway

Railway = cloud platform, **không cần quản lý server**, có $5/tháng free credit. Bot và web chạy 24/24 với managed Postgres + Redis.

> ⏱️ Thời gian setup: ~15 phút

---

## 📋 Tổng quan kiến trúc

```
GitHub repo (private)
    ↓ auto-deploy
Railway Project
    ├── 🤖 Bot service       (Dockerfile.bot)
    ├── 🌐 Web service        (Dockerfile.web) → public domain
    ├── 🗄️ PostgreSQL plugin
    └── 📦 Redis plugin
```

---

## Bước 1: Push code lên GitHub

### 1.1. Tạo private repo trên GitHub

1. https://github.com/new → tên repo (vd `duty-bot`) → **Private** → Create
2. **KHÔNG init README/license** (để tránh conflict)

### 1.2. Push code

Trong terminal:

```powershell
cd E:\Discord\Bot\Duty-bot

# Đảm bảo .env KHÔNG bị commit (đã có trong .gitignore)
git status
# Xác nhận .env không xuất hiện trong list

# Init git nếu chưa có
git init
git branch -M main

# Add remote (đổi USERNAME thành Github username của bạn)
git remote add origin https://github.com/USERNAME/duty-bot.git

# Commit + push
git add .
git commit -m "Initial commit"
git push -u origin main
```

**⚠️ QUAN TRỌNG:** Mở https://github.com/USERNAME/duty-bot và **kiểm tra file `.env` KHÔNG có trong repo**. Nếu có → leak token Discord ngay lập tức! Cần `git rm --cached .env && git commit && git push`.

---

## Bước 2: Tạo Railway account

1. https://railway.com → **Login with GitHub**
2. Authorize Railway access vào GitHub
3. Verify email

---

## Bước 3: Tạo Project

### 3.1. New Project from GitHub

1. Dashboard → **New Project** → **Deploy from GitHub repo**
2. Chọn repo `duty-bot` → Deploy
3. Railway sẽ tự build với Dockerfile mặc định

### 3.2. Project sẽ có 1 service ban đầu — đó là **Web service**

Click vào service mới tạo, vào **Settings**:
- **Service Name**: đổi thành `web`
- **Source** → Watch Paths: `web/**`, `bot/utils/**`, `models/**`, `requirements.txt`, `Dockerfile.web`
- **Build** → Dockerfile Path: `Dockerfile.web`
- **Deploy** → Start Command: `uvicorn web.main:app --host 0.0.0.0 --port $PORT --workers 2`

→ **Save** → Railway redeploy.

---

## Bước 4: Add Postgres database

1. Trong project → **+ New** → **Database** → **Add PostgreSQL**
2. Railway tạo postgres service tự động
3. Click vào service → tab **Variables** → ghi nhận `DATABASE_URL` (Railway tự generate)

---

## Bước 5: Add Redis

1. **+ New** → **Database** → **Add Redis**
2. Tương tự, có `REDIS_URL` tự động

---

## Bước 6: Add Bot service (deploy cùng repo, khác Dockerfile)

### 6.1. Trong project → **+ New** → **GitHub Repo** → chọn lại `duty-bot`

### 6.2. Click vào service mới → **Settings**:
- **Service Name**: `bot`
- **Build** → Dockerfile Path: `Dockerfile.bot`
- **Deploy** → Start Command: `python -m bot.main` (hoặc để mặc định CMD trong Dockerfile)
- **Networking** → **KHÔNG** generate public domain (bot không expose port)

→ **Save**.

---

## Bước 7: Set environment variables (CHO CẢ web + bot)

Vào **mỗi service** (web và bot) → tab **Variables** → **Raw Editor** → paste:

```env
# Discord (lấy từ Discord Developer Portal)
DISCORD_BOT_TOKEN=your_bot_token_here
DISCORD_CLIENT_ID=your_client_id
DISCORD_CLIENT_SECRET=your_client_secret
DISCORD_REDIRECT_URI=https://YOUR_RAILWAY_DOMAIN/auth/callback

# Secrets — generate bằng: python -c "import secrets; print(secrets.token_hex(32))"
SECRET_KEY=put_random_64_hex_chars_here
HMAC_SECRET=put_another_random_64_hex_here

# Fernet — generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
FERNET_KEY=put_fernet_key_here

# Web config
ALLOWED_ORIGINS=https://YOUR_RAILWAY_DOMAIN
DEBUG=False

# JWT
ACCESS_TOKEN_EXPIRE_MINUTES=15
REFRESH_TOKEN_EXPIRE_DAYS=7

# Timezone + export
DEFAULT_TIMEZONE=Asia/Ho_Chi_Minh
EXPORT_DIR=/tmp/duty-exports
EXPORT_TTL_MINUTES=10

# Rate limit
RATE_LIMIT_DEFAULT=30/minute
RATE_LIMIT_EXPORT=2/5minutes
RATE_LIMIT_LOGIN=5/minute
```

### 7.1. Reference DATABASE_URL và REDIS_URL từ plugin services

Vẫn trong **Variables** của web service (và bot service):
1. Click **+ New Variable**
2. Variable name: `DATABASE_URL`
3. Value: click icon liên kết 🔗 → chọn **Postgres** service → **DATABASE_URL**

Tương tự cho `REDIS_URL` → chọn **Redis** → **REDIS_URL**.

→ Variables auto-sync khi DB credentials đổi.

---

## Bước 8: Generate public domain cho web

1. Vào **web service** → **Settings** → **Networking**
2. Click **Generate Domain**
3. Railway tạo URL kiểu `duty-logger-production-abcd.up.railway.app`
4. **Copy URL này** — sẽ dùng ở bước 9

### 8.1. Update env vars với domain thật

Quay lại **Variables** của web + bot:
```env
DISCORD_REDIRECT_URI=https://duty-logger-production-abcd.up.railway.app/auth/callback
ALLOWED_ORIGINS=https://duty-logger-production-abcd.up.railway.app
```

→ Railway redeploy tự động.

---

## Bước 9: Discord Developer Portal

1. https://discord.com/developers/applications → app của bạn
2. **OAuth2** → **Redirects** → click **Add Redirect**
3. Paste: `https://duty-logger-production-abcd.up.railway.app/auth/callback`
4. **Save Changes**

5. **Bot** tab → đảm bảo các Privileged Intents đã bật:
   - ✅ SERVER MEMBERS INTENT
   - ✅ MESSAGE CONTENT INTENT

---

## Bước 10: Run Alembic migrations (one-time)

Lần đầu deploy, DB rỗng → cần chạy migrations.

**Cách 1 — Một lần qua Railway CLI (recommended):**

```powershell
# Cài Railway CLI
npm install -g @railway/cli

# Login + link project
railway login
railway link  # chọn project đã tạo

# Chạy migration trong context của bot service
railway run --service bot alembic upgrade head
```

**Cách 2 — Tạm chỉnh start command:**

Vào **bot service** → Settings → Deploy → Start Command:
```
alembic upgrade head && python -m bot.main
```
→ Save → bot redeploy → migration chạy → bot start. Sau đó đổi lại thành `python -m bot.main`.

---

## Bước 11: Verify

### 11.1. Check service status

Railway dashboard → cả 4 services (web, bot, Postgres, Redis) phải có status **Active** (xanh).

### 11.2. Check bot logs

Click **bot service** → **Deployments** → tab **Logs** — phải thấy:
```
[INFO] Bot đã online: Duty Bot#xxxx (ID: xxx)
[INFO] Đang phục vụ X guild(s)
```

### 11.3. Check web

Mở browser → `https://YOUR_RAILWAY_DOMAIN`
- Trang login phải hiện đẹp với gradient indigo+purple
- Click **Đăng nhập bằng Discord** → OAuth flow → quay về dashboard

### 11.4. Health check

```
https://YOUR_RAILWAY_DOMAIN/health
```
→ trả `{"status":"ok"}`.

---

## 💰 Chi phí

Railway charge theo **resource usage**, không charge theo service count.

**Ước tính cho duty-bot:**
- Bot service: ~50MB RAM idle, ~200MB khi OCR → ~$2-3/tháng
- Web service: ~100MB RAM → ~$1/tháng
- Postgres: 1GB storage → ~$1/tháng
- Redis: 256MB → free tier
- **Total: ~$4-5/tháng** → vừa đủ free credit của Railway

Để tránh charge, set spending limit:
- Account Settings → Usage Limit → $5/month

---

## 🔄 Auto-deploy khi push code

Mặc định Railway watch branch `main`. Mỗi `git push origin main` → Railway tự rebuild + redeploy.

Để skip deploy cho commit cụ thể:
```bash
git commit -m "fix typo [skip ci]"
```

---

## ⚙️ Commands hữu ích (Railway CLI)

```bash
# Logs realtime
railway logs --service bot
railway logs --service web

# Run command trong context production
railway run --service bot alembic upgrade head
railway run --service bot python -c "from bot.config import settings; print(settings.DATABASE_URL)"

# Shell vào container (debug)
railway shell --service bot

# Restart service
railway redeploy --service bot
```

---

## ❗ Troubleshooting Railway

| Lỗi | Fix |
|---|---|
| `Build failed: out of memory` | Railway free build có 8GB RAM. EasyOCR install nặng — thử upgrade Builder plan hoặc dùng pre-built image |
| `Bot không online` | Check logs — chắc Privileged Intents đã bật trong Discord Portal + DISCORD_BOT_TOKEN đúng |
| `Web 502/503` | Web service crash — `railway logs --service web` xem traceback |
| `Database connection refused` | Đã reference DATABASE_URL từ Postgres plugin chưa? |
| `Redirect URI mismatch` | URL trong Discord Portal phải MATCH 100% với DISCORD_REDIRECT_URI env (kể cả `https://`) |
| `Image build quá lâu (>10p)` | Bình thường lần đầu — sau đó cache nhanh. Hoặc bỏ EasyOCR nếu không dùng OCR |

---

## 🎁 Bonus — Custom domain

1. Mua domain (Namecheap, Cloudflare ~$10/year)
2. Railway → web service → **Settings** → **Networking** → **Custom Domain**
3. Add domain → Railway show CNAME record cần add vào DNS
4. DNS provider của bạn → add CNAME như Railway hướng dẫn
5. Đợi 5-30 phút → Railway tự issue SSL cert
6. Update `DISCORD_REDIRECT_URI` + `ALLOWED_ORIGINS` thành custom domain
7. Update Discord Portal Redirect tương ứng

---

## 📦 Sao lưu DB

Railway Postgres backup tự động hàng ngày (giữ 7 ngày trên Hobby plan).

Tải backup thủ công:
```bash
railway run --service postgres pg_dump $DATABASE_URL > backup.sql
```

---

## ✅ Done!

Bot và web giờ:
- ✅ Chạy 24/24 trên Railway
- ✅ Auto-restart khi crash
- ✅ Auto-deploy khi push code
- ✅ Free SSL certificate
- ✅ Managed Postgres + Redis
- ✅ Backup tự động

Có lỗi → copy log Railway gửi tôi.
