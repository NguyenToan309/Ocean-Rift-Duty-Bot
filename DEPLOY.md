# 🚀 Hướng dẫn deploy Duty Logger 24/24

3 phương án phổ biến — chọn 1 phù hợp:

| Option | Chi phí | Độ khó | Phù hợp với |
|---|---|---|---|
| **A. VPS Linux + Docker** ⭐ | $4-10/tháng | Trung bình | Production thật, ổn định 24/24 |
| **B. Cloud platform** | Free $5 credit | Dễ | Test nhanh, không quản lý server |
| **C. Local Windows 24/24** | $0 | Dễ | Máy luôn bật, mạng nhà ổn định |

---

## 🅰️ Option A: VPS Linux (RECOMMENDED)

### Bước 1: Mua VPS

Provider gợi ý:
- **Vultr** — $4/tháng (1GB RAM) https://vultr.com
- **DigitalOcean** — $6/tháng (1GB RAM) https://digitalocean.com
- **Hostinger VPS** — ~$5/tháng (2GB RAM) https://hostinger.com
- **Linode/Akamai** — $5/tháng

Chọn:
- **OS**: Ubuntu 22.04 LTS hoặc 24.04 LTS
- **RAM**: ≥1GB (2GB nếu dùng OCR thường xuyên — EasyOCR ăn RAM)
- **Region**: Singapore / Tokyo (gần Việt Nam, ping thấp)

Sau khi tạo, ghi lại:
- IP public (vd `123.45.67.89`)
- Root password hoặc SSH key

### Bước 2: SSH vào VPS

```bash
ssh root@123.45.67.89
```

### Bước 3: Chạy 1-command setup

```bash
curl -fsSL https://raw.githubusercontent.com/YOUR_GITHUB/duty-bot/main/scripts/deploy-vps.sh | bash
```

**Hoặc** copy `scripts/deploy-vps.sh` lên VPS rồi chạy:
```bash
chmod +x deploy-vps.sh
./deploy-vps.sh
```

Script sẽ tự động:
- Cài Docker + Docker Compose
- Clone repo (hoặc bạn rsync code lên)
- Tạo `.env` với secrets random
- Build + start containers
- Setup Nginx reverse proxy
- (Optional) Cài Let's Encrypt SSL

### Bước 4: Cấu hình `.env`

```bash
nano /opt/duty-logger/.env
```

Điền:
```env
DISCORD_BOT_TOKEN=your_token_here
DISCORD_CLIENT_ID=your_client_id
DISCORD_CLIENT_SECRET=your_client_secret
DISCORD_REDIRECT_URI=https://your-domain.com/auth/callback
ALLOWED_ORIGINS=https://your-domain.com
DEBUG=False
```

(Các secret khác — `SECRET_KEY`, `FERNET_KEY`, `HMAC_SECRET`, DB/Redis password — đã được script generate random.)

### Bước 5: Restart services

```bash
cd /opt/duty-logger
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

### Bước 6: Discord Developer Portal

Vào https://discord.com/developers/applications → app của bạn → OAuth2 → Redirects → thêm:
```
https://your-domain.com/auth/callback
```

→ Save Changes.

### Bước 7: Verify

```bash
docker-compose ps               # Tất cả phải Up (healthy)
docker-compose logs -f bot      # Bot online?
curl https://your-domain.com/health   # Web ok?
```

Bot và web giờ chạy 24/24. Auto-restart nếu crash, auto-start sau reboot.

---

## 🅱️ Option B: Cloud platform (Railway/Render)

### B1. Railway (https://railway.app)

1. Đăng ký + connect GitHub
2. New Project → Deploy from GitHub → chọn repo `duty-bot`
3. Railway sẽ detect `docker-compose.yml` → tạo services tự động
4. Vào Variables → add các env từ `.env`
5. Add Postgres + Redis services từ Railway templates
6. Generate domain trong Settings → tab Networking
7. Update `DISCORD_REDIRECT_URI` thành domain Railway

**Chi phí**: Free $5/tháng credit, đủ để chạy bot nhỏ.

### B2. Render (https://render.com)

1. New Web Service → connect GitHub repo
2. Tạo PostgreSQL + Redis trên Render
3. Tạo Background Worker cho bot (`python -m bot.main`)
4. Tạo Web Service cho FastAPI (`uvicorn web.main:app --host 0.0.0.0 --port $PORT`)
5. Env vars từ `.env`
6. Connect domain

**Chi phí**: Free tier (limit 750h/month), $7/tháng cho always-on.

---

## 🅲 Option C: Chạy 24/24 trên Windows local

⚠️ Yêu cầu máy bật 24/24 + mạng ổn định + UPS (phòng mất điện).

### C1. Docker Desktop với restart policy

`docker-compose.yml` đã có `restart: unless-stopped` — Docker tự khởi động lại container nếu crash hoặc Docker Desktop được start.

### C2. Bật Docker tự động khi Windows boot

```powershell
# Mở Docker Desktop → Settings → General
# Tick "Start Docker Desktop when you sign in"
# Tick "Open Docker Dashboard at startup"
```

### C3. Auto-start docker-compose sau Docker Desktop khởi động

Tôi tạo sẵn script `scripts/setup-windows-autostart.ps1`. Run với quyền **Administrator**:

```powershell
cd E:\Discord\Bot\Duty-bot
.\scripts\setup-windows-autostart.ps1
```

Script sẽ tạo Task Scheduler entry → mỗi lần Windows login, chạy `docker-compose up -d` tự động.

### C4. Bot chạy ngay trên host (không qua Docker)

Nếu muốn bot chạy native (faster cold start):

```powershell
.\scripts\install-bot-windows-service.ps1
```

→ Tạo Windows Service "DutyBot" tự khởi động khi boot, restart nếu crash.

---

## 🔁 Backup tự động

Script `scripts/backup_db.sh` đã có. Chạy daily qua cron (Linux) hoặc Task Scheduler (Windows):

**Linux** (VPS):
```bash
crontab -e
# Thêm:
0 3 * * * /opt/duty-logger/scripts/backup_db.sh > /var/log/duty-backup.log 2>&1
```

→ Backup DB mỗi 3:00 AM, giữ 7 bản gần nhất.

---

## 📊 Monitor

```bash
# VPS
docker-compose logs -f bot         # Bot logs realtime
docker-compose logs -f web         # Web logs realtime
docker-compose ps                  # Status services
docker stats                       # CPU/RAM usage

# Disk usage
docker system df
```

Web có endpoint `/health` để check uptime.

---

## ❗ Troubleshooting

| Lỗi | Fix |
|---|---|
| `Bot offline sau reboot` | Check `docker-compose ps`, nếu `Restarting` → `docker-compose logs bot` |
| `Web 502 Bad Gateway` | Nginx ok nhưng web container down — restart `docker-compose restart web` |
| `Redirect URI mismatch` | Discord Portal → OAuth2 → Redirects → đảm bảo URL đúng (có `/auth/callback`) |
| `Out of memory` | Tăng VPS RAM hoặc disable EasyOCR (`/log forward` thay `/log upload`) |
| `Database connection refused` | `docker-compose ps postgres` — nếu unhealthy, check disk full / volume issue |
